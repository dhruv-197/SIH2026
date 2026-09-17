"""Parsing and validation of NASA FIRMS active-fire records (VIIRS 375 m and MODIS 1 km).

Records are rejected rather than filled with invented defaults: a detection without an
acquisition time or brightness temperatures cannot support a reliable classification.
"""
import csv
import hashlib
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

SATELLITE_NAMES = {
    "N": "Suomi NPP",
    "NPP": "Suomi NPP",
    "SNPP": "Suomi NPP",
    "SUOMI NPP": "Suomi NPP",
    "N20": "NOAA-20",
    "NOAA-20": "NOAA-20",
    "J1": "NOAA-20",
    "N21": "NOAA-21",
    "NOAA-21": "NOAA-21",
    "J2": "NOAA-21",
    "T": "Terra",
    "TERRA": "Terra",
    "A": "Aqua",
    "AQUA": "Aqua",
}

VIIRS_CONFIDENCE = {"l": "low", "n": "nominal", "h": "high", "low": "low", "nominal": "nominal", "high": "high"}


class RecordValidationError(ValueError):
    """Raised when a record cannot support a reliable inference."""


def _first(record: Dict[str, Any], *names: str) -> Optional[str]:
    for name in names:
        value = record.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _number(record: Dict[str, Any], *names: str, label: str, required: bool = True) -> Optional[float]:
    raw = _first(record, *names)
    if raw is None:
        if required:
            raise RecordValidationError(f"missing required field: {label}")
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise RecordValidationError(f"{label} is not a number: {raw!r}") from exc


def normalize_record(record: Dict[str, Any], data_source: str) -> Dict[str, Any]:
    rec = {str(k).strip().lower(): v for k, v in record.items() if k is not None}

    lat = _number(rec, "latitude", "lat", label="latitude")
    lon = _number(rec, "longitude", "lon", "lng", label="longitude")
    frp = _number(rec, "frp", label="frp")
    has_viirs_columns = _first(rec, "bright_ti4") is not None
    bright_mir = _number(rec, "bright_ti4", "brightness", "bright_mir", label="bright_ti4 (VIIRS) or brightness (MODIS)")
    bright_tir = _number(rec, "bright_ti5", "bright_t31", "bright_tir", label="bright_ti5 (VIIRS) or bright_t31 (MODIS)")

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise RecordValidationError("latitude/longitude are outside the valid range")
    if not (0 <= frp <= 50000):
        raise RecordValidationError("frp must be between 0 and 50000 MW")
    if not (200 <= bright_mir <= 550):
        raise RecordValidationError("mid-infrared brightness temperature must be between 200 and 550 K")
    if not (150 <= bright_tir <= 420):
        raise RecordValidationError("thermal-infrared brightness temperature must be between 150 and 420 K")

    instrument = (_first(rec, "instrument") or ("VIIRS" if has_viirs_columns else "MODIS")).upper()
    if instrument not in ("VIIRS", "MODIS"):
        instrument = "VIIRS" if has_viirs_columns else "MODIS"

    date_raw = _first(rec, "acq_date")
    time_raw = _first(rec, "acq_time")
    if not date_raw or time_raw is None:
        raise RecordValidationError("acq_date (YYYY-MM-DD) and acq_time (HHMM, UTC) are required")
    time_digits = time_raw.replace(":", "")
    if not time_digits.isdigit() or len(time_digits) > 4:
        raise RecordValidationError(f"acq_time must be HHMM in UTC, got {time_raw!r}")
    time_digits = time_digits.zfill(4)
    try:
        acquired = datetime.strptime(f"{date_raw} {time_digits}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RecordValidationError("acq_date must be YYYY-MM-DD and acq_time HHMM (UTC)") from exc

    daynight = (_first(rec, "daynight") or "").upper()
    if daynight not in ("D", "N"):
        raise RecordValidationError("daynight must be 'D' or 'N'")

    satellite_raw = (_first(rec, "satellite") or "").upper()
    satellite = SATELLITE_NAMES.get(satellite_raw, satellite_raw.title() if satellite_raw else "Unknown")

    confidence_raw = (_first(rec, "confidence") or "").lower()
    if instrument == "VIIRS":
        confidence = VIIRS_CONFIDENCE.get(confidence_raw, confidence_raw or "unknown")
    else:
        try:
            value = float(confidence_raw)
            confidence = "low" if value < 30 else ("nominal" if value < 80 else "high")
        except ValueError:
            confidence = confidence_raw or "unknown"

    fingerprint = f"{satellite}|{acquired:%Y%m%d%H%M}|{lat:.5f}|{lon:.5f}"
    detection_id = "D" + hashlib.sha1(fingerprint.encode()).hexdigest()[:19].upper()

    return {
        "detection_id": detection_id,
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "acq_datetime": acquired.strftime("%Y-%m-%dT%H:%MZ"),
        "acq_date": acquired.strftime("%Y-%m-%d"),
        "acq_time": acquired.strftime("%H%M"),
        "satellite": satellite,
        "instrument": instrument,
        "confidence": confidence,
        "version": _first(rec, "version") or "unknown",
        "daynight": daynight,
        "bright_mir": round(bright_mir, 2),
        "bright_tir": round(bright_tir, 2),
        "frp": round(frp, 2),
        "scan": _number(rec, "scan", label="scan", required=False),
        "track": _number(rec, "track", label="track", required=False),
        # FIRMS standard processing only: 0 presumed vegetation fire, 1 volcano, 2 other static land source, 3 offshore
        "firms_type": int(firms_type) if (firms_type := _first(rec, "type")) in ("0", "1", "2", "3") else None,
        "data_source": data_source,
    }


def parse_csv_text(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in reader]


def validate_records(records: List[Dict[str, Any]], data_source: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (valid, rejected). Row numbers count the CSV header as row 1."""
    valid, rejected = [], []
    for row_number, record in enumerate(records, start=2):
        try:
            valid.append(normalize_record(record, data_source))
        except RecordValidationError as exc:
            rejected.append({"row": row_number, "reason": str(exc)})
    return valid, rejected

"""Operator-adjustable settings stored in SQLite, with validation."""
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ..db.models import SystemSettingsModel, utcnow_iso
from .severity import SeverityConfig

DEFAULTS: Dict[str, Any] = {
    "zscore_threshold": 4.0,
    "frp_threshold_mw": 50.0,
    "cross_alert_km": 2.0,
    "high_intensity_frp_mw": 100.0,
    "auto_sync_interval_mins": 180,
    "satellite_auto_polling": True,
    "retention_days": 45,
    "webhook_url": "",
    "notify_incidents": True,
    "notify_min_severity": "HIGH",
    "dashboard_url": "",
    "firms_api_key": "",
}

NUMERIC_RANGES = {
    "zscore_threshold": (2.0, 10.0),
    "frp_threshold_mw": (5.0, 5000.0),
    "cross_alert_km": (0.5, 10.0),
    "high_intensity_frp_mw": (20.0, 5000.0),
    "auto_sync_interval_mins": (15, 1440),
    "retention_days": (7, 365),
}
INTEGER_KEYS = {"auto_sync_interval_mins", "retention_days"}
SECRET_KEYS = {"firms_api_key"}


class SettingsError(ValueError):
    pass


def _coerce(key: str, raw: str) -> Any:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return str(raw).lower() == "true"
    if key in INTEGER_KEYS:
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return raw


def load_settings(db) -> Dict[str, Any]:
    values = dict(DEFAULTS)
    for row in db.query(SystemSettingsModel).all():
        if row.key in DEFAULTS:
            try:
                values[row.key] = _coerce(row.key, row.value)
            except (TypeError, ValueError):
                pass
    return values


def public_settings(values: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in values.items() if k not in SECRET_KEYS}
    out["firms_api_key_configured"] = bool(values.get("firms_api_key"))
    return out


def validate_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"Unsupported setting(s): {', '.join(sorted(unknown))}")
    clean: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in NUMERIC_RANGES:
            try:
                number = int(value) if key in INTEGER_KEYS else float(value)
            except (TypeError, ValueError):
                raise SettingsError(f"{key} must be a number")
            low, high = NUMERIC_RANGES[key]
            if not low <= number <= high:
                raise SettingsError(f"{key} must be between {low} and {high}")
            clean[key] = number
        elif key == "satellite_auto_polling":
            if not isinstance(value, bool):
                raise SettingsError("satellite_auto_polling must be true or false")
            clean[key] = value
        elif key in ("webhook_url", "dashboard_url"):
            value = (value or "").strip()
            if value:
                parsed = urlparse(value)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    raise SettingsError(f"{key} must be an http(s) URL or empty")
            clean[key] = value.rstrip("/") if key == "dashboard_url" else value
        elif key == "notify_incidents":
            if not isinstance(value, bool):
                raise SettingsError("notify_incidents must be true or false")
            clean[key] = value
        elif key == "notify_min_severity":
            if value not in ("HIGH", "CRITICAL"):
                raise SettingsError("notify_min_severity must be HIGH or CRITICAL")
            clean[key] = value
        elif key == "firms_api_key":
            value = (value or "").strip()
            if value and (len(value) < 20 or not value.isalnum()):
                raise SettingsError("firms_api_key must be the 32-character MAP_KEY from NASA FIRMS")
            clean[key] = value
    return clean


def save_settings(db, clean: Dict[str, Any], updated_by: Optional[str]) -> None:
    for key, value in clean.items():
        row = db.query(SystemSettingsModel).filter(SystemSettingsModel.key == key).first()
        stored = str(value).lower() if isinstance(value, bool) else str(value)
        if row:
            row.value, row.updated_at, row.updated_by = stored, utcnow_iso(), updated_by
        else:
            db.add(SystemSettingsModel(key=key, value=stored, updated_at=utcnow_iso(), updated_by=updated_by))
    db.commit()


def severity_config(values: Dict[str, Any]) -> SeverityConfig:
    return SeverityConfig(
        zscore_threshold=float(values["zscore_threshold"]),
        frp_threshold_mw=float(values["frp_threshold_mw"]),
        cross_alert_km=float(values["cross_alert_km"]),
        high_intensity_frp_mw=float(values["high_intensity_frp_mw"]),
    )

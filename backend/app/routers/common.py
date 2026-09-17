"""Shared helpers for filtering the in-memory analysis snapshot."""
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from fastapi import HTTPException

SEVERITY_RANK = {"NORMAL": 0, "HIGH": 1, "CRITICAL": 2}


def parse_bbox(bbox: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    if not bbox:
        return None
    try:
        west, south, east, north = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox must be 'west,south,east,north' in decimal degrees")
    if west >= east or south >= north:
        raise HTTPException(status_code=422, detail="bbox must satisfy west < east and south < north")
    return west, south, east, north


def filter_detections(
    items: Iterable[Dict[str, Any]],
    class_code: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    facility_id: Optional[str] = None,
    source_id: Optional[int] = None,
    data_source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    bbox: Optional[str] = None,
    min_frp: Optional[float] = None,
    verification_required: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    box = parse_bbox(bbox)
    severities = {s.strip().upper() for s in severity.split(",")} if severity else None
    out = []
    for d in items:
        if class_code and d["class_code"] != class_code:
            continue
        if category and d["category"] != category:
            continue
        if severities and d["severity"] not in severities:
            continue
        if facility_id and d["facility_id"] != facility_id:
            continue
        if source_id is not None and d["source_id"] != source_id:
            continue
        if data_source and d["data_source"] != data_source:
            continue
        if start_date and d["acq_date"] < start_date:
            continue
        if end_date and d["acq_date"] > end_date:
            continue
        if min_frp is not None and d["frp"] < min_frp:
            continue
        if verification_required is not None and d["verification_required"] != verification_required:
            continue
        if box and not (box[0] <= d["longitude"] <= box[2] and box[1] <= d["latitude"] <= box[3]):
            continue
        out.append(d)
    return out


def date_range(start: str, end: str) -> List[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first + timedelta(days=k)).isoformat() for k in range((last - first).days + 1)]


def daily_series(detections: Sequence[Dict[str, Any]], window: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per day of the observation window; days without detections have null FRP."""
    if not window:
        return []
    by_day: Dict[str, List[float]] = {}
    for d in detections:
        by_day.setdefault(d["acq_date"], []).append(float(d["frp"]))
    return [
        {
            "date": day,
            "detections": len(by_day.get(day, [])),
            "max_frp": round(max(by_day[day]), 2) if day in by_day else None,
            "median_frp": round(float(np.median(by_day[day])), 2) if day in by_day else None,
        }
        for day in date_range(window["start"], window["end"])
    ]


def robust_stats(values: Sequence[float], days: int, min_detections: int = 6, min_days: int = 3) -> Optional[Dict[str, float]]:
    if len(values) < min_detections or days < min_days:
        return None
    arr = np.asarray(values, dtype=float)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    return {"median_mw": round(median, 2), "mad_mw": round(mad, 2), "scale_mw": round(max(1.4826 * mad, 0.25 * median, 0.5), 2), "n": int(len(arr)), "days": int(days)}

"""Wind at a detection from Open-Meteo: weather-model analyses for recent days, the ERA5 reanalysis for older dates.

Wind matters when a vegetation fire burns near a facility: a fire upwind of a plant can spread towards it, and its
smoke drifts downwind. The wind is context for the analyst; it never changes a classification or a severity.
Weather data by Open-Meteo.com (CC BY 4.0); ERA5 from the Copernicus Climate Change Service.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import DetectionModel, IncidentModel, utcnow_iso
from .approach import angle_between, bearing_deg, compass

RECENT_DAYS = 60  # the forecast API serves recent past days; older dates come from the ERA5 archive
TOWARDS_HALF_ANGLE_DEG = 45.0
CALM_KMH = 5.0
OPEN_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
_cache: Dict[str, Dict[str, Any]] = {}


def wind_relation(wind_from_deg: float, speed_kmh: float, fire_lat: float, fire_lon: float, target_lat: float, target_lon: float) -> str:
    """Whether the wind blows from the fire towards the facility, away from it, across that line, or is calm."""
    if speed_kmh < CALM_KMH:
        return "calm"
    blowing_towards = (wind_from_deg + 180.0) % 360.0
    angle = angle_between(blowing_towards, bearing_deg(fire_lat, fire_lon, target_lat, target_lon))
    if angle <= TOWARDS_HALF_ANGLE_DEG:
        return "towards"
    if angle >= 180.0 - TOWARDS_HALF_ANGLE_DEG:
        return "away"
    return "across"


def describe_wind(wind: Dict[str, Any], relation: Optional[str], facility: Optional[str]) -> str:
    text = f"Wind at {wind['time_utc'][11:16]} UTC: {wind['speed_kmh']:.0f} km/h from the {wind['from_compass']}"
    if relation == "calm":
        return text + " (near calm)"
    if relation and facility:
        text += {
            "towards": f", blowing from the fire towards {facility}",
            "away": f", blowing away from {facility}",
            "across": f", blowing across the line from the fire to {facility}",
        }[relation]
    return text


async def wind_at(lat: float, lon: float, when: datetime) -> Dict[str, Any]:
    """Hourly 10 m wind at the hour nearest to `when` (UTC)."""
    if settings.OFFLINE:
        return {"status": "unavailable", "reason": "offline mode"}
    when = when.astimezone(timezone.utc) if when.tzinfo else when.replace(tzinfo=timezone.utc)
    hour = when.replace(minute=0, second=0, microsecond=0) + (timedelta(hours=1) if when.minute >= 30 else timedelta())
    key = f"{lat:.2f}:{lon:.2f}:{hour:%Y-%m-%dT%H}"
    if key in _cache:
        return _cache[key]
    recent = datetime.now(timezone.utc) - hour <= timedelta(days=RECENT_DAYS)
    url = settings.OPEN_METEO_FORECAST_API if recent else settings.OPEN_METEO_ARCHIVE_API
    day = hour.strftime("%Y-%m-%d")
    params = {"latitude": round(lat, 3), "longitude": round(lon, 3), "hourly": "wind_speed_10m,wind_direction_10m",
              "start_date": day, "end_date": day, "wind_speed_unit": "kmh", "timezone": "GMT"}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": settings.HTTP_USER_AGENT}) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        hourly = response.json()["hourly"]
        index = hourly["time"].index(hour.strftime("%Y-%m-%dT%H:00"))
        speed, direction = hourly["wind_speed_10m"][index], hourly["wind_direction_10m"][index]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"status": "error", "reason": f"{type(exc).__name__} from Open-Meteo"}
    if speed is None or direction is None:
        return {"status": "unavailable", "reason": "no wind value for that hour"}
    result = {
        "status": "ok",
        "time_utc": hour.strftime("%Y-%m-%dT%H:%MZ"),
        "speed_kmh": round(float(speed), 1),
        "from_deg": round(float(direction)),
        "from_compass": compass(float(direction)),
        "source": "Open-Meteo weather-model analysis" if recent else "Open-Meteo ERA5 reanalysis archive",
        "attribution": ATTRIBUTION,
    }
    _cache[key] = result
    return result


async def wind_for_fire(lat: float, lon: float, when: datetime, facility_lat: Optional[float] = None,
                        facility_lon: Optional[float] = None, facility: Optional[str] = None) -> Dict[str, Any]:
    """Wind at a fire and, when a facility is given, how it blows relative to that facility."""
    wind = await wind_at(lat, lon, when)
    if wind["status"] != "ok":
        return wind
    relation = None
    if facility_lat is not None and facility_lon is not None:
        relation = wind_relation(wind["from_deg"], wind["speed_kmh"], lat, lon, facility_lat, facility_lon)
    return {**wind, "relation": relation, "facility": facility, "summary": describe_wind(wind, relation, facility)}


async def annotate_cross_alerts(limit: int = 25) -> Dict[str, int]:
    """Record the wind at the latest detection of open cross-alert incidents (once per detection) with a history note."""
    summary = {"annotated": 0, "not_available": 0}
    if settings.OFFLINE:
        return summary
    targets = []
    with SessionLocal() as db:
        rows = db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN_INCIDENT_STATUSES), IncidentModel.incident_type == "CROSS_ALERT").all()
        for row in rows:
            details = json.loads(row.details_json or "{}")
            if (details.get("wind") or {}).get("detection_id") == row.detection_id:
                continue
            detection = db.query(DetectionModel).filter(DetectionModel.detection_id == row.detection_id).first()
            if detection is not None:
                targets.append((row.id, row.detection_id, detection.latitude, detection.longitude, detection.acq_datetime, details.get("fire_approach") or {}))
    for incident_id, detection_id, lat, lon, acquired, approach in targets[:limit]:
        when = datetime.strptime(acquired[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        wind = await wind_for_fire(lat, lon, when, approach.get("facility_latitude"), approach.get("facility_longitude"), approach.get("facility"))
        if wind["status"] != "ok":
            summary["not_available"] += 1
            continue
        with SessionLocal() as db:
            row = db.get(IncidentModel, incident_id)
            if row is None or row.detection_id != detection_id:
                continue
            details = json.loads(row.details_json or "{}")
            details["wind"] = {**wind, "detection_id": detection_id}
            history = json.loads(row.history_json or "[]")
            history.append({"at": utcnow_iso(), "by": "system", "status": row.status, "note": wind["summary"]})
            row.details_json, row.history_json = json.dumps(details), json.dumps(history)
            db.commit()
        summary["annotated"] += 1
    return summary

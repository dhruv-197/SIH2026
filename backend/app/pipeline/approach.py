"""Direction of travel of a fire front relative to a facility.

A vegetation fire correctly classified as natural can still threaten an industrial site - the reason cross-alerts
exist. Whether the fire is moving towards the site is measured from the detections themselves:

1. Take the vegetation-fire detections within 10 km of the facility over the 5 days up to the alerting detection,
   on the same side of the facility as the alerting fire (within 60 degrees of its bearing), so that fires on other
   sides do not mix in.
2. Keep one front only: walking back from the alerting day, an earlier day belongs to the front when its fires lie
   within 3 km of the next day's fires (at most one day may be missing, for cloud). Separate fires in other fields or
   forests on other days are not a moving front.
3. On each day of the front, the detection closest to the facility marks it. A front that closed in by at least 1 km,
   at 0.5 km/day or more, is approaching; the reverse is receding; anything else is holding. A front seen on a single
   day cannot show a direction.

375 m pixels and missed overpasses (cloud, smoke) make this an indicator for the analyst, not a forecast.
"""
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from shapely.geometry import Point
from shapely.ops import nearest_points

from .features import parse_acq_datetime
from .geo_context import EARTH_RADIUS_KM, haversine_km

SEARCH_KM = 10.0
LOOKBACK_DAYS = 5
SECTOR_HALF_ANGLE_DEG = 60.0
CONTINUITY_KM = 3.0  # a front's fires on one day lie within this distance of its fires on the next
MAX_DAY_GAP = 2  # days between observations of one front (a cloudy day may hide it)
MIN_CLOSING_KM = 1.0
MIN_RATE_KM_PER_DAY = 0.5
COMPASS_POINTS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def compass(degrees: float) -> str:
    return COMPASS_POINTS[int(((degrees % 360.0) + 22.5) // 45.0) % 8]


def angle_between(a: float, b: float) -> float:
    """Smallest angle between two bearings (0-180 degrees)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def distance_to_km(geometry, lat: float, lon: float) -> float:
    point = Point(lon, lat)
    if geometry.geom_type in ("Polygon", "MultiPolygon") and geometry.contains(point):
        return 0.0
    _, nearest = nearest_points(point, geometry)
    return haversine_km(lat, lon, nearest.y, nearest.x)


def _min_separation_km(first: Sequence[Tuple[float, float, float]], second: Sequence[Tuple[float, float, float]]) -> float:
    """Smallest great-circle distance between two sets of (lat, lon, ...) points."""
    a = np.radians(np.array([(p[0], p[1]) for p in first]))
    b = np.radians(np.array([(p[0], p[1]) for p in second]))
    dlat = a[:, None, 0] - b[None, :, 0]
    dlon = a[:, None, 1] - b[None, :, 1]
    h = np.sin(dlat / 2.0) ** 2 + np.cos(a[:, None, 0]) * np.cos(b[None, :, 0]) * np.sin(dlon / 2.0) ** 2
    return float(2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(h.min(), 0.0, 1.0))))


def fire_approach(records: Sequence[Dict[str, Any]], alert: Dict[str, Any], facility_geometry, facility_name: str) -> Dict[str, Any]:
    """records: vegetation-fire detections (latitude, longitude, acq_datetime); alert: the alerting detection."""
    centre = facility_geometry.centroid
    alert_time = parse_acq_datetime(alert)
    reference = bearing_deg(centre.y, centre.x, float(alert["latitude"]), float(alert["longitude"]))
    side = compass(reference)
    min_lon, min_lat, max_lon, max_lat = facility_geometry.bounds
    dlat = SEARCH_KM / 110.57
    dlon = SEARCH_KM / (111.32 * max(math.cos(math.radians(centre.y)), 0.2))

    points_by_day: Dict[str, List[Tuple[float, float, float]]] = defaultdict(list)
    for record in records:
        lat, lon = float(record["latitude"]), float(record["longitude"])
        if not (min_lat - dlat <= lat <= max_lat + dlat and min_lon - dlon <= lon <= max_lon + dlon):
            continue
        when = parse_acq_datetime(record)
        if when > alert_time or when < alert_time - timedelta(days=LOOKBACK_DAYS):
            continue
        if angle_between(bearing_deg(centre.y, centre.x, lat, lon), reference) > SECTOR_HALF_ANGLE_DEG:
            continue
        distance = distance_to_km(facility_geometry, lat, lon)
        if distance > SEARCH_KM:
            continue
        points_by_day[when.strftime("%Y-%m-%d")].append((lat, lon, distance))

    days = sorted(points_by_day)
    front = days[-1:]
    for day in reversed(days[:-1]):
        later = front[0]
        if (date.fromisoformat(later) - date.fromisoformat(day)).days > MAX_DAY_GAP:
            break
        if _min_separation_km(points_by_day[day], points_by_day[later]) > CONTINUITY_KM:
            break
        front.insert(0, day)
    closest = {day: min(point[2] for point in points_by_day[day]) for day in front}
    base = {
        "facility": facility_name,
        "facility_latitude": round(centre.y, 5),
        "facility_longitude": round(centre.x, 5),
        "side": side,
        "bearing_from_facility_deg": round(reference),
        "detections_used": sum(len(points_by_day[day]) for day in front),
        "separate_fire_days": len(days) - len(front),
        "front_by_day": [{"date": day, "closest_km": round(closest[day], 2)} for day in front],
    }
    if len(front) < 2:
        latest = closest[front[-1]] if front else distance_to_km(facility_geometry, float(alert["latitude"]), float(alert["longitude"]))
        where = f"at {facility_name}" if latest < 0.1 else f"{latest:.1f} km {side} of {facility_name}"
        if len(days) >= 2:
            summary = f"Fire {where}; the fires seen nearby on earlier days were separate, so no front's direction of travel can be measured"
        else:
            summary = f"Fire seen on one day only, {where}: its direction of travel is not measurable yet"
        return {**base, "status": "insufficient_data", "first_km": None, "latest_km": round(latest, 2), "closing_rate_km_per_day": None, "summary": summary}

    offsets = np.array([(date.fromisoformat(day) - date.fromisoformat(front[0])).days for day in front], dtype=float)
    distances = np.array([closest[day] for day in front])
    slope = float(np.polyfit(offsets, distances, 1)[0])
    first, latest = float(distances[0]), float(distances[-1])
    span = int(offsets[-1])
    if first - latest >= MIN_CLOSING_KM and slope <= -MIN_RATE_KM_PER_DAY:
        status = "approaching"
        summary = (f"Fire front closed in on {facility_name} from {first:.1f} km to {latest:.1f} km over {span} day(s) "
                   f"({-slope:.1f} km/day), coming from the {side}")
    elif latest - first >= MIN_CLOSING_KM and slope >= MIN_RATE_KM_PER_DAY:
        status = "receding"
        summary = f"Fire front moved away from {facility_name}, from {first:.1f} km to {latest:.1f} km over {span} day(s)"
    else:
        status = "holding"
        summary = f"Fire front held {distances.min():.1f}-{distances.max():.1f} km {side} of {facility_name} over {len(front)} days"
    return {**base, "status": status, "first_km": round(first, 2), "latest_km": round(latest, 2),
            "closing_rate_km_per_day": round(-slope, 2), "summary": summary}

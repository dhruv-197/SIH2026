"""Feature extraction shared by model training and live classification.

Training (simulated detection streams) and serving (real FIRMS detections) both call
build_feature_table(). Using one implementation prevents training/serving skew: the model
only ever sees features computed exactly this way, from observations alone. Nothing in a
detection record can override a feature.
"""
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.neighbors import BallTree

from .geo_context import CONTEXT_CATEGORIES, EARTH_RADIUS_KM, MAX_CONTEXT_KM, haversine_km
from .landcover import LANDCOVER_FEATURES

PERSISTENCE_RADIUS_KM = 0.75  # ~2 VIIRS pixels: geolocation scatter of a fixed source
CONCURRENT_RADIUS_KM = 2.0
CONCURRENT_WINDOW_HOURS = 1.5  # same overpass
EVENT_RADIUS_KM = 5.0
EVENT_WINDOW_DAYS = 3
GRID_CELL_DEG = 0.005
VIIRS_MIR_SATURATION_K = 367.0
MODIS_MIR_SATURATION_K = 500.0

FEATURE_COLUMNS = [
    # radiometry of this detection
    "frp_log", "bright_mir", "bright_tir", "delta_t", "mir_saturated", "is_night", "is_modis", "pixel_area_km2",
    # recurrence at this location across the observation window
    "persistence_days", "persistence_ratio", "detections_750m", "night_fraction_750m", "frp_median_750m_log", "frp_cv_750m",
    # spatial pattern of the surrounding fire activity
    "concurrent_pixels_2km", "event_cells_5km", "event_days_5km", "spread_km_day", "isolation_other_cells_5km",
    # geographic context (OSM industrial features, facility catalog)
    "dist_oil_gas_km", "dist_heavy_industry_km", "dist_mining_km", "inside_industrial",
    # ESA WorldCover fractions in the pixel footprint (NaN when unavailable)
    *LANDCOVER_FEATURES,
]


def parse_acq_datetime(record: Dict[str, Any]) -> datetime:
    value = record.get("acq_datetime")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value:
        text = str(value).rstrip("Z")
        return datetime.strptime(text[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    return datetime.strptime(f"{record['acq_date']} {str(record['acq_time']).zfill(4)}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)


def _grid_code(lat: float, lon: float) -> int:
    return (math.floor(lat / GRID_CELL_DEG) + 40000) * 200000 + (math.floor(lon / GRID_CELL_DEG) + 80000)


def build_feature_table(
    detections: Sequence[Dict[str, Any]],
    context_lookup: Callable[[float, float], Dict[str, Any]],
    landcover_lookup: Callable[[float, float], Dict[str, float]],
    observation_days: Optional[int] = None,
) -> Tuple[List[Dict[str, float]], List[Dict[str, Any]]]:
    """Compute model features and human-readable evidence for every detection.

    detections: dicts with latitude, longitude, acq_datetime (or acq_date + acq_time),
        daynight, frp, bright_mir, bright_tir, instrument and optionally scan / track.
    context_lookup: GeoContext.lookup-compatible callable.
    landcover_lookup: returns LANDCOVER_FEATURES values (NaN when unavailable).
    observation_days: length of the observation window; derived from the data when None.
    """
    n = len(detections)
    if n == 0:
        return [], []

    lat = np.array([float(d["latitude"]) for d in detections])
    lon = np.array([float(d["longitude"]) for d in detections])
    times = [parse_acq_datetime(d) for d in detections]
    hours = np.array([t.timestamp() / 3600.0 for t in times])
    day_ord = np.array([t.date().toordinal() for t in times])
    if observation_days is None:
        observation_days = int(day_ord.max() - day_ord.min()) + 1
    observation_days = max(int(observation_days), 1)

    is_night = np.array([1.0 if str(d.get("daynight", "D")).upper() == "N" else 0.0 for d in detections])
    frp = np.array([max(float(d.get("frp") or 0.0), 0.0) for d in detections])
    cells = np.array([_grid_code(la, lo) for la, lo in zip(lat, lon)], dtype=np.int64)

    coords = np.radians(np.column_stack([lat, lon]))
    tree = BallTree(coords, metric="haversine")
    near_idx = tree.query_radius(coords, r=PERSISTENCE_RADIUS_KM / EARTH_RADIUS_KM)
    conc_idx = tree.query_radius(coords, r=CONCURRENT_RADIUS_KM / EARTH_RADIUS_KM)
    event_idx = tree.query_radius(coords, r=EVENT_RADIUS_KM / EARTH_RADIUS_KM)

    rows: List[Dict[str, float]] = []
    evidence: List[Dict[str, Any]] = []
    for i, det in enumerate(detections):
        near = near_idx[i]
        near_days = np.unique(day_ord[near])
        near_frp = frp[near]
        frp_median = float(np.median(near_frp))
        frp_mean = float(np.mean(near_frp))
        frp_cv = float(np.std(near_frp) / frp_mean) if len(near) > 1 and frp_mean > 0 else 0.0

        concurrent = conc_idx[i][np.abs(hours[conc_idx[i]] - hours[i]) <= CONCURRENT_WINDOW_HOURS]
        event = event_idx[i][np.abs(day_ord[event_idx[i]] - day_ord[i]) <= EVENT_WINDOW_DAYS]
        event_cells = np.unique(cells[event])
        isolation = len(np.setdiff1d(event_cells, np.unique(cells[near]), assume_unique=True))
        event_days = np.unique(day_ord[event])

        spread = 0.0
        if len(event_days) >= 2:
            centroids = []
            for day in event_days:
                members = event[day_ord[event] == day]
                centroids.append((int(day), float(lat[members].mean()), float(lon[members].mean())))
            for (d0, la0, lo0), (d1, la1, lo1) in zip(centroids, centroids[1:]):
                spread = max(spread, haversine_km(la0, lo0, la1, lo1) / max(d1 - d0, 1))
        spread = min(spread, 30.0)

        context = context_lookup(float(lat[i]), float(lon[i]))
        landcover = landcover_lookup(float(lat[i]), float(lon[i]))

        instrument = str(det.get("instrument") or "VIIRS").upper()
        modis = instrument == "MODIS"
        bright_mir = float(det["bright_mir"]) if det.get("bright_mir") is not None else float("nan")
        bright_tir = float(det["bright_tir"]) if det.get("bright_tir") is not None else float("nan")
        saturation = MODIS_MIR_SATURATION_K if modis else VIIRS_MIR_SATURATION_K
        scan, track = det.get("scan"), det.get("track")
        pixel_area = float(scan) * float(track) if scan and track else (1.0 if modis else 0.14)

        row = {
            "frp_log": math.log1p(frp[i]),
            "bright_mir": bright_mir,
            "bright_tir": bright_tir,
            "delta_t": bright_mir - bright_tir,
            "mir_saturated": 1.0 if bright_mir >= saturation - 0.5 else 0.0,
            "is_night": float(is_night[i]),
            "is_modis": 1.0 if modis else 0.0,
            "pixel_area_km2": pixel_area,
            "persistence_days": float(len(near_days)),
            "persistence_ratio": len(near_days) / observation_days,
            "detections_750m": float(len(near)),
            "night_fraction_750m": float(is_night[near].mean()),
            "frp_median_750m_log": math.log1p(frp_median),
            "frp_cv_750m": frp_cv,
            "concurrent_pixels_2km": float(len(concurrent)),
            "event_cells_5km": float(len(event_cells)),
            "event_days_5km": float(len(event_days)),
            "spread_km_day": spread,
            "isolation_other_cells_5km": float(isolation),
            "inside_industrial": 1.0 if context.get("inside_industrial") else 0.0,
        }
        for category in CONTEXT_CATEGORIES:
            row[f"dist_{category}_km"] = min(float(context.get(f"dist_{category}_km", MAX_CONTEXT_KM)), MAX_CONTEXT_KM)
        for name in LANDCOVER_FEATURES:
            row[name] = float(landcover.get(name, float("nan")))

        rows.append(row)
        evidence.append({
            "persistence_days": int(len(near_days)),
            "observation_days": observation_days,
            "detections_within_750m": int(len(near)),
            "night_fraction_within_750m": round(float(is_night[near].mean()), 3),
            "frp_median_within_750m": round(frp_median, 2),
            "concurrent_pixels_within_2km": int(len(concurrent)),
            "active_cells_within_5km_3d": int(len(event_cells)),
            "spread_km_per_day": round(spread, 2),
            "nearest_industrial_feature": context.get("nearest"),
            "inside_feature": context.get("inside_feature"),
            "nearest_by_category": context.get("nearest_by_category", {}),
        })
    return rows, evidence

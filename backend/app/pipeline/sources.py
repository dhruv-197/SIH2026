"""Grouping detections into persistent thermal sources, transient fire events and same-overpass clusters."""
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
from scipy.stats import theilslopes
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

from .features import CONCURRENT_RADIUS_KM, CONCURRENT_WINDOW_HOURS, PERSISTENCE_RADIUS_KM, parse_acq_datetime
from .geo_context import EARTH_RADIUS_KM, haversine_km

SOURCE_MIN_ACTIVE_DAYS = 2
EVENT_RADIUS_KM = 3.0
EVENT_MAX_GAP_DAYS = 3.0


def cluster_persistent_sources(detections: Sequence[Dict[str, Any]], feature_rows: Sequence[Dict[str, float]]) -> np.ndarray:
    """Label detections that belong to a location active on >= 2 separate days (-1 otherwise)."""
    labels = np.full(len(detections), -1, dtype=int)
    candidates = [i for i, row in enumerate(feature_rows) if row["persistence_days"] >= SOURCE_MIN_ACTIVE_DAYS]
    if len(candidates) < 2:
        return labels
    coords = np.radians([[detections[i]["latitude"], detections[i]["longitude"]] for i in candidates])
    fitted = DBSCAN(eps=PERSISTENCE_RADIUS_KM / EARTH_RADIUS_KM, min_samples=2, metric="haversine", algorithm="ball_tree").fit(coords)
    next_label = 0
    for cluster in sorted(set(fitted.labels_) - {-1}):
        members = [candidates[k] for k, lab in enumerate(fitted.labels_) if lab == cluster]
        days = {parse_acq_datetime(detections[i]).date() for i in members}
        if len(days) >= SOURCE_MIN_ACTIVE_DAYS:
            labels[members] = next_label
            next_label += 1
    return labels


def cluster_events(detections: Sequence[Dict[str, Any]], indices: Sequence[int]) -> Dict[int, int]:
    """Group transient detections into fire events: <= 3 km apart and no gap longer than 3 days."""
    if not indices:
        return {}
    coords = np.radians([[detections[i]["latitude"], detections[i]["longitude"]] for i in indices])
    spatial = DBSCAN(eps=EVENT_RADIUS_KM / EARTH_RADIUS_KM, min_samples=1, metric="haversine", algorithm="ball_tree").fit(coords).labels_
    by_cluster: Dict[int, List[int]] = {}
    for idx, lab in zip(indices, spatial):
        by_cluster.setdefault(int(lab), []).append(idx)
    assignment: Dict[int, int] = {}
    event_id = 0
    for members in by_cluster.values():
        members.sort(key=lambda i: parse_acq_datetime(detections[i]))
        previous = None
        for i in members:
            t = parse_acq_datetime(detections[i])
            if previous is not None and (t - previous).total_seconds() / 86400.0 > EVENT_MAX_GAP_DAYS:
                event_id += 1
            assignment[i] = event_id
            previous = t
        event_id += 1
    return assignment


def overpass_clusters(detections: Sequence[Dict[str, Any]], indices: Sequence[int]) -> Dict[int, Dict[str, float]]:
    """Size and total FRP of the same-overpass group within 2 km around each detection in `indices`,
    counting only detections in `indices`. One hot event is often seen as several adjacent pixels."""
    if not indices:
        return {}
    coords = np.radians([[detections[i]["latitude"], detections[i]["longitude"]] for i in indices])
    hours = np.array([parse_acq_datetime(detections[i]).timestamp() / 3600.0 for i in indices])
    frp = np.array([float(detections[i]["frp"]) for i in indices])
    neighbours = BallTree(coords, metric="haversine").query_radius(coords, r=CONCURRENT_RADIUS_KM / EARTH_RADIUS_KM)
    clusters = {}
    for k, i in enumerate(indices):
        same_pass = neighbours[k][np.abs(hours[neighbours[k]] - hours[k]) <= CONCURRENT_WINDOW_HOURS]
        clusters[i] = {"detections": int(len(same_pass)), "frp_mw": round(float(frp[same_pass].sum()), 2)}
    return clusters


def frp_trend(detections: Sequence[Dict[str, Any]], members: Sequence[int]) -> Tuple[str, float]:
    """Theil-Sen slope of FRP over time (MW/day) for the latest 20 detections."""
    ordered = sorted(members, key=lambda i: parse_acq_datetime(detections[i]))[-20:]
    if len(ordered) < 4:
        return "insufficient_data", 0.0
    t0 = parse_acq_datetime(detections[ordered[0]])
    days = np.array([(parse_acq_datetime(detections[i]) - t0).total_seconds() / 86400.0 for i in ordered])
    frp = np.array([float(detections[i]["frp"]) for i in ordered])
    if np.ptp(days) < 1.0:
        return "insufficient_data", 0.0
    slope = float(theilslopes(frp, days)[0])
    relative = slope / max(float(np.median(frp)), 0.5)
    if relative > 0.1:
        return "rising", round(slope, 3)
    if relative < -0.1:
        return "falling", round(slope, 3)
    return "stable", round(slope, 3)


def summarize_source(detections: Sequence[Dict[str, Any]], members: Sequence[int], observation_days: int) -> Dict[str, Any]:
    lats = np.array([detections[i]["latitude"] for i in members], dtype=float)
    lons = np.array([detections[i]["longitude"] for i in members], dtype=float)
    center_lat, center_lon = float(np.median(lats)), float(np.median(lons))
    times = [parse_acq_datetime(detections[i]) for i in members]
    frp = np.array([float(detections[i]["frp"]) for i in members])
    night = np.mean([1.0 if str(detections[i].get("daynight")).upper() == "N" else 0.0 for i in members])
    active_days = len({t.date() for t in times})
    extent = max(haversine_km(center_lat, center_lon, la, lo) for la, lo in zip(lats, lons))
    trend, slope = frp_trend(detections, members)
    return {
        "latitude": round(center_lat, 5),
        "longitude": round(center_lon, 5),
        "first_seen": min(times).strftime("%Y-%m-%dT%H:%MZ"),
        "last_seen": max(times).strftime("%Y-%m-%dT%H:%MZ"),
        "detection_count": len(members),
        "active_days": active_days,
        "observation_days": observation_days,
        "persistence_ratio": round(active_days / max(observation_days, 1), 3),
        "night_fraction": round(float(night), 3),
        "frp_median": round(float(np.median(frp)), 2),
        "frp_p90": round(float(np.percentile(frp, 90)), 2),
        "frp_max": round(float(frp.max()), 2),
        "extent_km": round(float(extent), 3),
        "trend": trend,
        "trend_slope_mw_per_day": slope,
    }

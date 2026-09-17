"""Severity assessment and alerting rules.

The rules are statistical and transparent: every alert lists the measured values that triggered it, both as
sentences and as machine-readable reason codes, and names the version of the alert policy (rules plus thresholds)
that raised it. Thermal data alone cannot confirm an explosion or a gas leak, so industrial excursions are reported
as "suspected" and always require verification.
"""
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Sequence

import numpy as np

from .taxonomy import CLASS_LABELS, INDUSTRIAL_ACCIDENT

# Bump when the alert rules change. The thresholds in force are fingerprinted separately (policy_info).
POLICY_RULES_VERSION = "2.2"


@dataclass
class SeverityConfig:
    zscore_threshold: float = 4.0  # robust z-score of FRP against the source's own history
    # FRP that is abnormal at an industrial site without history: one pixel, or the total of a
    # same-overpass cluster at a location with no detections on other days.
    frp_threshold_mw: float = 50.0
    cross_alert_km: float = 2.0  # vegetation fire this close to mapped industry
    high_intensity_frp_mw: float = 100.0  # very intense vegetation fire
    large_event_cells: int = 25  # widespread vegetation fire activity (cells within 5 km, 3 days)
    min_baseline_detections: int = 6
    min_baseline_days: int = 3
    # Large complexes flare in bursts: an excursion must also clear the source's own 90th percentile.
    excursion_p90_factor: float = 2.5
    # Cross-alerts need a fire of some size, or a confidently classified fire spread over several cells, so small
    # ambiguous pixels inside mines or plants do not raise infrastructure alerts.
    cross_alert_min_confidence: float = 0.75
    cross_alert_min_frp_mw: float = 5.0
    # Detections this close to a mapped industrial feature count as being at the site: pixel size,
    # geolocation error, and OSM outlines that often cover only part of a complex.
    industrial_site_km: float = 1.0


AUTHORITIES = {
    "INDUSTRIAL_EXCURSION": ["Facility safety officer", "State industrial safety / factory inspectorate", "District emergency operations centre"],
    "INDUSTRIAL_HIGH_INTENSITY": ["Facility safety officer", "State industrial safety / factory inspectorate", "District emergency operations centre"],
    "CROSS_ALERT": ["District fire and emergency services", "Facility safety officer", "State forest department"],
    "HIGH_INTENSITY_VEGETATION_FIRE": ["State forest department", "District administration"],
}

# Machine-readable reasons attached to alerts, shown as chips in the dashboard and sent with notifications.
REASON_CODES = {
    "ABN_BASELINE_EXCEEDED": "FRP far above this source's own robust baseline",
    "ABN_ABOVE_P90": "FRP several times this source's own 90th percentile",
    "NEW_HEAT_AT_SITE": "Intense heat at a mapped industrial site with no detections there on other days",
    "MULTI_PIXEL_CLUSTER": "Several adjacent hot pixels in one overpass",
    "NO_BASELINE": "Too little history at this location for a baseline",
    "VEG_FIRE_NEAR_INFRA": "Vegetation fire within the cross-alert distance of critical infrastructure",
    "FIRE_SPREAD_CELLS": "Fire activity spread over several nearby cells",
    "CONF_LOW": "Industrial-versus-vegetation classification is uncertain",
    "FIRE_APPROACHING": "Fire front moved towards the facility over successive days",
    "VEG_FRP_HIGH": "Very intense vegetation fire",
    "VEG_LARGE_EVENT": "Widespread vegetation fire activity",
}


def policy_info(config: SeverityConfig) -> Dict[str, Any]:
    """The alert policy in force: the rules version plus a fingerprint of the thresholds. Stored with every alert, it
    ties the alert to the exact rules and values that raised it."""
    thresholds = asdict(config)
    fingerprint = hashlib.sha1(json.dumps(thresholds, sort_keys=True).encode()).hexdigest()[:8]
    return {
        "version": f"{POLICY_RULES_VERSION}+{fingerprint}",
        "rules_version": POLICY_RULES_VERSION,
        "thresholds_fingerprint": fingerprint,
        "thresholds": thresholds,
    }


def robust_baseline(prior_frp: Sequence[float], prior_days: int, config: SeverityConfig) -> Optional[Dict[str, float]]:
    if len(prior_frp) < config.min_baseline_detections or prior_days < config.min_baseline_days:
        return None
    values = np.asarray(prior_frp, dtype=float)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = max(1.4826 * mad, 0.25 * median, 0.5)
    return {
        "median_mw": round(median, 2),
        "mad_mw": round(mad, 2),
        "scale_mw": round(scale, 2),
        "p90_mw": round(float(np.percentile(values, 90)), 2),
        "n": int(len(values)),
        "days": int(prior_days),
    }


def assess(
    frp: float,
    category: str,
    class_code: str,
    dist_industrial_km: float,
    inside_industrial: bool,
    event_cells: int,
    baseline: Optional[Dict[str, float]],
    config: SeverityConfig,
    category_confidence: float = 1.0,
    new_activity: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """new_activity: for a detection at a location with no detections on other days, the size and total FRP
    of its same-overpass cluster, {"detections": n, "frp_mw": total}. None for persistent sources."""
    z = None
    if baseline:
        z = (frp - baseline["median_mw"]) / baseline["scale_mw"]
    site_frp = max(frp, new_activity["frp_mw"]) if new_activity else frp

    components = {
        "baseline_excursion": round(min(1.0, max(0.0, z / config.zscore_threshold)), 3) if z is not None else 0.0,
        "intensity": round(min(1.0, site_frp / config.frp_threshold_mw if category == "industrial" else frp / config.high_intensity_frp_mw), 3),
        "industrial_proximity": round(max(0.0, 1.0 - dist_industrial_km / (2 * config.cross_alert_km)), 3) if category == "vegetation" else 0.0,
    }

    severity, incident_type, triggers, codes = "NORMAL", None, [], []
    override_class = None
    near_site = inside_industrial or dist_industrial_km <= config.industrial_site_km

    if (
        category == "industrial"
        and z is not None
        and z >= config.zscore_threshold
        and frp >= max(3 * baseline["median_mw"], config.excursion_p90_factor * baseline["p90_mw"])
        and frp - baseline["median_mw"] >= 10.0
    ):
        severity, incident_type = "CRITICAL", "INDUSTRIAL_EXCURSION"
        override_class = INDUSTRIAL_ACCIDENT
        triggers.append(
            f"FRP {frp:.1f} MW is {z:.1f} robust standard deviations above this source's median of {baseline['median_mw']:.1f} MW "
            f"and {frp / max(baseline['p90_mw'], 0.1):.1f}x its 90th percentile ({baseline['n']} prior detections over {baseline['days']} days)"
        )
        codes += ["ABN_BASELINE_EXCEEDED", "ABN_ABOVE_P90"]
    elif category == "industrial" and baseline is None and near_site and site_frp >= config.frp_threshold_mw:
        severity, incident_type = "HIGH", "INDUSTRIAL_HIGH_INTENSITY"
        codes += ["NEW_HEAT_AT_SITE", "NO_BASELINE"]
        if new_activity and new_activity["detections"] > 1:
            triggers.append(
                f"{new_activity['detections']} detections totalling {new_activity['frp_mw']:.0f} MW in one overpass at a mapped industrial site "
                f"with no detections there on other days (threshold {config.frp_threshold_mw:.0f} MW): possible fire or emergency flaring"
            )
            codes.append("MULTI_PIXEL_CLUSTER")
        else:
            history = "with no detections there on other days" if new_activity else "with no baseline yet"
            triggers.append(f"FRP {frp:.1f} MW at a mapped industrial site {history} (threshold {config.frp_threshold_mw:.0f} MW)")
    elif (
        category == "vegetation"
        and dist_industrial_km <= config.cross_alert_km
        and (frp >= config.cross_alert_min_frp_mw or (event_cells >= 3 and category_confidence >= config.cross_alert_min_confidence))
    ):
        severity, incident_type = "HIGH", "CROSS_ALERT"
        trigger = (f"Vegetation fire ({category_confidence:.0%} confidence, FRP {frp:.1f} MW) {dist_industrial_km:.2f} km from mapped "
                   f"critical infrastructure (threshold {config.cross_alert_km:.1f} km)")
        codes.append("VEG_FIRE_NEAR_INFRA")
        if event_cells >= 3:
            codes.append("FIRE_SPREAD_CELLS")
        if category_confidence < config.cross_alert_min_confidence:
            trigger += "; the classification is uncertain, so verify with imagery or on site"
            codes.append("CONF_LOW")
        triggers.append(trigger)
    elif category == "vegetation" and (frp >= config.high_intensity_frp_mw or event_cells >= config.large_event_cells):
        severity, incident_type = "HIGH", "HIGH_INTENSITY_VEGETATION_FIRE"
        if frp >= config.high_intensity_frp_mw:
            triggers.append(f"FRP {frp:.1f} MW exceeds {config.high_intensity_frp_mw:.0f} MW")
            codes.append("VEG_FRP_HIGH")
        if event_cells >= config.large_event_cells:
            triggers.append(f"{event_cells} active fire cells within 5 km over 3 days")
            codes.append("VEG_LARGE_EVENT")

    score = 100.0 * max(components["baseline_excursion"], 0.8 * components["intensity"], 0.7 * components["industrial_proximity"])
    if severity == "CRITICAL":
        score = max(score, 80.0)
    elif severity == "HIGH":
        score = max(score, 60.0)

    return {
        "severity": severity,
        "severity_score": round(score, 1),
        "score_components": components,
        "incident_type": incident_type,
        "is_cross_alert": incident_type == "CROSS_ALERT",
        "robust_zscore": round(z, 2) if z is not None else None,
        "baseline": baseline,
        "triggers": triggers,
        "reason_codes": codes,
        "override_class": override_class,
        "recommended_action": recommended_action(incident_type, class_code if not override_class else override_class),
        "authorities": AUTHORITIES.get(incident_type, []),
    }


def apply_fire_approach(severity: Dict[str, Any], approach: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach the fire front's direction of travel (pipeline/approach.py) to a cross-alert. A front approaching the
    facility makes the alert critical: a correct "vegetation fire" label must not route the alert away from the plant
    the fire is moving towards."""
    if severity.get("incident_type") != "CROSS_ALERT" or not approach:
        return severity
    out = dict(severity, fire_approach=approach)
    if approach.get("status") == "approaching":
        out.update({
            "severity": "CRITICAL",
            "severity_score": max(float(severity["severity_score"]), 85.0),
            "triggers": severity["triggers"] + [approach["summary"]],
            "reason_codes": severity["reason_codes"] + ["FIRE_APPROACHING"],
            "recommended_action": ("Dual response now: alert district fire services and the facility safety officer together - the fire front "
                                   "is moving towards the facility. Track it on every overpass."),
        })
    return out


def recommended_action(incident_type: Optional[str], class_code: str) -> str:
    if incident_type == "INDUSTRIAL_EXCURSION":
        return ("Contact the facility operator and check the latest Sentinel-2 / Sentinel-1 imagery immediately. "
                "A thermal excursion alone cannot confirm an explosion, fire or leak.")
    if incident_type == "INDUSTRIAL_HIGH_INTENSITY":
        return ("Ask the facility operator whether this is planned flaring, an upset or a fire; check the latest "
                "Sentinel-2 / Sentinel-1 imagery and watch the next overpass.")
    if incident_type == "CROSS_ALERT":
        return "Alert district fire services and the facility safety officer; track spread towards the facility on the next overpass."
    if incident_type == "HIGH_INTENSITY_VEGETATION_FIRE":
        return "Notify the state forest department / district administration and check spread on the next overpass."
    if class_code in ("gas_flare", "heavy_industry", "mining_coal_fire"):
        return f"Routine: log as {CLASS_LABELS[class_code].lower()} and keep the source baseline updated."
    return "Routine monitoring."

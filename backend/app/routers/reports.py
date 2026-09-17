import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import IncidentModel, IngestionRunModel
from ..pipeline.funnel import alert_funnel
from ..pipeline.imagery import cached_evidence
from ..pipeline.regions import region_summaries
from ..pipeline.reviews import review_stats
from ..pipeline.service import service
from ..pipeline.settings_store import load_settings, severity_config
from ..pipeline.severity import REASON_CODES, policy_info
from ..pipeline.taxonomy import CLASS_LABELS, INDUSTRIAL_ACCIDENT, MODEL_CLASSES, category_for

router = APIRouter(prefix="/reports", tags=["Reports"])
OPEN = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")


@router.get("/briefing")
def briefing() -> Dict[str, Any]:
    detections = service.snapshot["detections"]
    sources = service.snapshot["sources"]
    window = service.snapshot["window"]
    class_counts = Counter(d["class_code"] for d in detections)

    with SessionLocal() as db:
        incidents = [row.to_dict() for row in db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN)).all()]
        runs = [row.to_dict() for row in db.query(IngestionRunModel).order_by(IngestionRunModel.id.desc()).limit(5).all()]
        policy = policy_info(severity_config(load_settings(db)))

    report = None
    if os.path.exists(settings.EVALUATION_REPORT_PATH):
        with open(settings.EVALUATION_REPORT_PATH, encoding="utf-8") as f:
            report = json.load(f)

    facility_rows = []
    for fac in service.facilities:
        dets = [d for d in detections if d["facility_id"] == fac["id"]]
        if dets:
            facility_rows.append({
                "id": fac["id"], "name": fac["name"], "sector": fac["sector"], "state": fac["state"],
                "detections": len(dets), "active_days": len({d["acq_date"] for d in dets}),
                "median_frp": round(sorted(d["frp"] for d in dets)[len(dets) // 2], 2),
                "open_incidents": sum(1 for i in incidents if i["facility_id"] == fac["id"]),
            })
    facility_rows.sort(key=lambda r: (-r["open_incidents"], -r["detections"]))

    severity_order = {"CRITICAL": 0, "HIGH": 1}
    top_incidents = sorted(incidents, key=lambda i: (severity_order.get(i["severity"], 2), i["created_at"] or ""))[:15]
    evidence = cached_evidence(i["detection_id"] for i in top_incidents)
    for incident in top_incidents:
        found = evidence.get(incident["detection_id"])
        incident["imagery_evidence"] = {key: found.get(key) for key in ("status", "supports", "headline")} if found else None
    codes_used = sorted({code for incident in top_incidents for code in incident.get("reason_codes") or []})

    industrial = sum(1 for d in detections if d["category"] == "industrial")
    return {
        "title": "Thermal anomaly briefing",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"label": settings.DATASET_LABEL or None, "static": settings.STATIC_DATASET},
        "observation_window": window,
        "headline": {
            "detections": len(detections),
            "industrial_detections": industrial,
            "vegetation_detections": len(detections) - industrial,
            "persistent_sources": len(sources),
            "open_incidents": len(incidents),
            "critical_incidents": sum(1 for i in incidents if i["severity"] == "CRITICAL"),
            "detections_needing_verification": sum(1 for d in detections if d["verification_required"]),
            "detections_awaiting_review": sum(1 for d in detections if d["verification_required"] and not d.get("review_label")),
        },
        "funnel": alert_funnel(detections, sources, len(incidents)),
        "regions": [region for region in region_summaries(detections, sources, incidents) if region["detections"]],
        "by_class": [
            {"code": code, "label": CLASS_LABELS[code], "category": category_for(code), "detections": class_counts.get(code, 0)}
            for code in MODEL_CLASSES + [INDUSTRIAL_ACCIDENT]
        ],
        "open_incidents": top_incidents,
        "alert_policy": {"version": policy["version"], "reason_codes": {code: REASON_CODES[code] for code in codes_used if code in REASON_CODES}},
        "analyst_reviews": review_stats(detections),
        "most_active_facilities": facility_rows[:15],
        "top_persistent_sources": [
            {k: s.get(k) for k in ("id", "latitude", "longitude", "class_label", "active_days", "detection_count", "frp_median", "frp_max", "facility_id", "trend")}
            for s in sorted(sources, key=lambda s: (-s["active_days"], -s["frp_median"]))[:15]
        ],
        "data_provenance": {
            "detections": "NASA FIRMS active fire products (VIIRS 375 m: Suomi NPP, NOAA-20, NOAA-21; MODIS 1 km: Terra, Aqua)",
            "industrial_context": f"OpenStreetMap extract ({service.osm_feature_count} thermally relevant features, ODbL) plus a {len(service.facilities)}-site facility catalog",
            "land_cover": "ESA WorldCover 10 m 2021 v200 via Microsoft Planetary Computer",
            "satellite_imagery": "Copernicus Sentinel-2 L2A via Microsoft Planetary Computer - shortwave-infrared hot-spot and burn-scar checks for incidents",
            "weather": "Wind at cross-alerts from Open-Meteo.com (CC BY 4.0): weather-model analyses for recent days, ERA5 reanalysis for older dates",
            "recent_ingestion_runs": runs,
        },
        "model": {
            "metadata": service.classifier.metadata,
            "simulation_category_accuracy": (report or {}).get("simulation", {}).get("category_accuracy"),
            "real_data_checks": (report or {}).get("real_data_checks", {}).get("summary"),
            "archive_data_checks": (report or {}).get("archive_data_checks", {}).get("summary"),
        },
        "limitations": [
            "Classification accuracy is measured on held-out simulated scenes plus proxy checks on real detections; it is not field-validated.",
            "Industrial excursions are statistical alerts. Thermal data alone cannot confirm an explosion, fire or gas leak.",
            "OpenStreetMap coverage of Indian industry is incomplete; unmapped sites rely on persistence and radiometry.",
            "Clouds and missed overpasses create gaps; days without detections are not evidence that a source was inactive.",
            "Sentinel-2 passes in the morning every few days, so a missing hot spot or burn scar does not rule out a fire.",
            "A fire front's direction of travel is measured from 375 m detections on separate days; cloud or missed overpasses can hide or distort it.",
            "Analyst labels are the start of a validation set: agreement is counted only on the reviewed, mostly uncertain, detections.",
        ],
    }

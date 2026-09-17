import json
import os
from collections import Counter, defaultdict
from typing import Any, Dict

from fastapi import APIRouter

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import IncidentModel, IngestionRunModel
from ..pipeline.funnel import alert_funnel
from ..pipeline.regions import region_summaries
from ..pipeline.reviews import review_stats
from ..pipeline.service import service
from ..pipeline.taxonomy import CATEGORY_LABELS, CLASS_COLORS, CLASS_LABELS, INDUSTRIAL_ACCIDENT, MODEL_CLASSES, category_for, taxonomy_payload
from .common import date_range

router = APIRouter(prefix="/stats", tags=["Statistics"])
OPEN = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")


@router.get("/summary")
def summary() -> Dict[str, Any]:
    detections = service.snapshot["detections"]
    sources = service.snapshot["sources"]
    window = service.snapshot["window"]

    class_counts = Counter(d["class_code"] for d in detections)
    source_counts = Counter(s["class_code"] for s in sources)
    classes = [
        {
            "code": code,
            "label": CLASS_LABELS[code],
            "category": category_for(code),
            "color": CLASS_COLORS[code],
            "detections": class_counts.get(code, 0),
            "persistent_sources": source_counts.get(code, 0),
        }
        for code in MODEL_CLASSES + [INDUSTRIAL_ACCIDENT]
    ]

    daily = []
    if window:
        per_day = defaultdict(Counter)
        for d in detections:
            per_day[d["acq_date"]][d["category"]] += 1
        daily = [{"date": day, "industrial": per_day[day]["industrial"], "vegetation": per_day[day]["vegetation"]} for day in date_range(window["start"], window["end"])]

    hourly = [{"hour_utc": h, "industrial": 0, "vegetation": 0} for h in range(24)]
    for d in detections:
        hourly[int(d["acq_time"][:2])][d["category"]] += 1

    with SessionLocal() as db:
        open_incidents = [row.to_dict() for row in db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN)).all()]
        last_run = db.query(IngestionRunModel).order_by(IngestionRunModel.id.desc()).first()

    return {
        "window": window,
        "generated_at": service.snapshot["generated_at"],
        "totals": {
            "detections": len(detections),
            "persistent_sources": len(sources),
            "industrial_detections": sum(1 for d in detections if d["category"] == "industrial"),
            "vegetation_detections": sum(1 for d in detections if d["category"] == "vegetation"),
            "verification_required": sum(1 for d in detections if d["verification_required"]),
            "verification_pending": sum(1 for d in detections if d["verification_required"] and not d.get("review_label")),
            "reviewed_detections": sum(1 for d in detections if d.get("review_label")),
            "facilities_with_detections": len({d["facility_id"] for d in detections if d["facility_id"]}),
            "catalog_facilities": len(service.facilities),
        },
        "categories": CATEGORY_LABELS,
        "classes": classes,
        "severity": dict(Counter(d["severity"] for d in detections)),
        "satellites": dict(Counter(d["satellite"] for d in detections)),
        "data_sources": dict(Counter(d["data_source"] for d in detections)),
        "daynight": dict(Counter(d["daynight"] for d in detections)),
        "daily": daily,
        "hourly_utc": hourly,
        "latest_detection": detections[0]["acq_datetime"] if detections else None,
        "open_incidents": dict(Counter(i["severity"] for i in open_incidents)),
        "last_ingestion": last_run.to_dict() if last_run else None,
        "funnel": alert_funnel(detections, sources, len(open_incidents)),
        "regions": region_summaries(detections, sources, open_incidents),
    }


@router.get("/persistence")
def persistence() -> Dict[str, Any]:
    detections = service.snapshot["detections"]
    sources = service.snapshot["sources"]
    window = service.snapshot["window"]
    days = window["days"] if window else 0

    active_days = Counter(s["active_days"] for s in sources)
    recurring_share = {}
    for category in ("industrial", "vegetation"):
        group = [d for d in detections if d["category"] == category]
        recurring = sum(1 for d in group if d["source_id"] is not None)
        recurring_share[category] = {"detections": len(group), "at_persistent_sources": recurring, "share": round(recurring / len(group), 3) if group else None}

    night_by_class = {}
    for code in MODEL_CLASSES + [INDUSTRIAL_ACCIDENT]:
        group = [d for d in detections if d["class_code"] == code]
        if group:
            night_by_class[code] = {"label": CLASS_LABELS[code], "detections": len(group), "night_share": round(sum(1 for d in group if d["daynight"] == "N") / len(group), 3)}

    spread_buckets = Counter()
    for d in detections:
        value = d.get("spread_km_day") or 0.0
        bucket = "< 0.5 km/day" if value < 0.5 else "0.5 - 2 km/day" if value < 2 else "2 - 5 km/day" if value < 5 else ">= 5 km/day"
        spread_buckets[(d["category"], bucket)] += 1

    top = sorted(sources, key=lambda s: (-s["active_days"], -s["detection_count"]))[:20]
    return {
        "window": window,
        "persistent_sources": len(sources),
        "active_days_histogram": [{"active_days": k, "sources": active_days.get(k, 0)} for k in range(2, max(days, 2) + 1)],
        "recurring_share": recurring_share,
        "night_share_by_class": night_by_class,
        "spread_distribution": [{"category": c, "bucket": b, "detections": n} for (c, b), n in sorted(spread_buckets.items())],
        "most_persistent_sources": top,
        "definition": "A persistent source is a location (750 m) with detections on at least 2 separate days in the observation window.",
    }


@router.get("/model")
def model() -> Dict[str, Any]:
    report = None
    if os.path.exists(settings.EVALUATION_REPORT_PATH):
        with open(settings.EVALUATION_REPORT_PATH, encoding="utf-8") as f:
            report = json.load(f)
    return {"metadata": service.classifier.metadata, "report": report, "taxonomy": taxonomy_payload(),
            "analyst_reviews": review_stats(service.snapshot["detections"])}


@router.get("/taxonomy")
def taxonomy() -> Dict[str, Any]:
    return taxonomy_payload()

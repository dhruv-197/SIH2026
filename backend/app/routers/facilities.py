from collections import Counter
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from ..db.database import SessionLocal
from ..db.models import IncidentModel
from ..pipeline.service import service
from ..pipeline.settings_store import load_settings
from .common import SEVERITY_RANK, daily_series, robust_stats

router = APIRouter(prefix="/facilities", tags=["Catalog facilities"])
OPEN = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")


def _open_incidents_by_facility() -> Dict[str, List[Dict[str, Any]]]:
    with SessionLocal() as db:
        rows = db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN), IncidentModel.facility_id.isnot(None)).all()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            out.setdefault(row.facility_id, []).append(row.to_dict())
        return out


def _facility_view(facility: Dict[str, Any], open_incidents: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    detections = [d for d in service.snapshot["detections"] if d["facility_id"] == facility["id"]]
    real = [d for d in detections if d["data_source"] != "drill"]
    sources = [s for s in service.snapshot["sources"] if s["facility_id"] == facility["id"]]
    incidents = open_incidents.get(facility["id"], [])
    max_severity = max((d["severity"] for d in detections), key=lambda s: SEVERITY_RANK[s], default=None)
    if incidents:
        status = "ALERT"
    elif detections:
        status = "ACTIVE"
    else:
        status = "NO_DETECTIONS"
    baseline = robust_stats([d["frp"] for d in real], len({d["acq_date"] for d in real}))
    return {
        **facility,
        "status": status,
        "detections": len(detections),
        "active_days": len({d["acq_date"] for d in detections}),
        "last_detection": max((d["acq_datetime"] for d in detections), default=None),
        "median_frp": round(sorted(d["frp"] for d in detections)[len(detections) // 2], 2) if detections else None,
        "max_frp": max((d["frp"] for d in detections), default=None),
        "max_severity": max_severity,
        "classes": dict(Counter(d["class_code"] for d in detections)),
        "persistent_sources": [{"id": s["id"], "class_code": s["class_code"], "class_label": s["class_label"], "active_days": s["active_days"]} for s in sources],
        "open_incidents": len(incidents),
        "baseline": baseline,
        "baseline_note": None if baseline else "A baseline needs at least 6 detections on 3 separate days.",
    }


@router.get("")
def list_facilities() -> Dict[str, Any]:
    open_incidents = _open_incidents_by_facility()
    items = [_facility_view(f, open_incidents) for f in service.facilities]
    return {"total": len(items), "items": items, "window": service.snapshot["window"]}


@router.get("/{facility_id}")
def get_facility(facility_id: str) -> Dict[str, Any]:
    facility = next((f for f in service.facilities if f["id"] == facility_id), None)
    if facility is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    view = _facility_view(facility, _open_incidents_by_facility())
    view["detection_list"] = sorted((d for d in service.snapshot["detections"] if d["facility_id"] == facility_id), key=lambda d: d["acq_datetime"], reverse=True)
    view["incidents"] = _open_incidents_by_facility().get(facility_id, [])
    return view


@router.get("/{facility_id}/timeseries")
def facility_timeseries(facility_id: str) -> Dict[str, Any]:
    facility = next((f for f in service.facilities if f["id"] == facility_id), None)
    if facility is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    detections = [d for d in service.snapshot["detections"] if d["facility_id"] == facility_id]
    real = [d for d in detections if d["data_source"] != "drill"]
    baseline = robust_stats([d["frp"] for d in real], len({d["acq_date"] for d in real}))
    with SessionLocal() as db:
        z = float(load_settings(db)["zscore_threshold"])
    return {
        "facility": facility,
        "window": service.snapshot["window"],
        "series": daily_series(detections, service.snapshot["window"]),
        "baseline": baseline,
        "alert_threshold_mw": round(baseline["median_mw"] + z * baseline["scale_mw"], 2) if baseline else None,
        "zscore_threshold": z,
        "note": "Days without a detection have no value - the satellite either saw no fire or the view was cloudy.",
    }

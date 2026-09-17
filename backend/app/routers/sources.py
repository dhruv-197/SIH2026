from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from ..pipeline.service import service
from .common import daily_series, parse_bbox, robust_stats

router = APIRouter(prefix="/sources", tags=["Persistent thermal sources"])


@router.get("")
def list_sources(
    class_code: Optional[str] = None,
    category: Optional[Literal["industrial", "vegetation"]] = None,
    facility_id: Optional[str] = None,
    min_active_days: int = Query(0, ge=0),
    verification_required: Optional[bool] = None,
    bbox: Optional[str] = None,
) -> Dict[str, Any]:
    box = parse_bbox(bbox)
    items = []
    for s in service.snapshot["sources"]:
        if class_code and s["class_code"] != class_code:
            continue
        if category and s["category"] != category:
            continue
        if facility_id and s["facility_id"] != facility_id:
            continue
        if s["active_days"] < min_active_days:
            continue
        if verification_required is not None and s["verification_required"] != verification_required:
            continue
        if box and not (box[0] <= s["longitude"] <= box[2] and box[1] <= s["latitude"] <= box[3]):
            continue
        items.append(s)
    return {"total": len(items), "items": items, "window": service.snapshot["window"]}


@router.get("/{source_id}")
def get_source(source_id: int) -> Dict[str, Any]:
    source = next((s for s in service.snapshot["sources"] if s["id"] == source_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="Persistent source not found")
    detections = sorted((d for d in service.snapshot["detections"] if d["source_id"] == source_id), key=lambda d: d["acq_datetime"])
    real = [d for d in detections if d["data_source"] != "drill"]
    return {
        **source,
        "detections": detections,
        "daily": daily_series(detections, service.snapshot["window"]),
        "baseline": robust_stats([d["frp"] for d in real], len({d["acq_date"] for d in real})),
    }

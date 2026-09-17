import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import DetectionModel, IncidentModel
from ..pipeline import audit, reviews
from ..pipeline.imagery import cached_evidence
from ..pipeline.normalize import RecordValidationError, parse_csv_text
from ..pipeline.service import describe_place, service
from ..pipeline.taxonomy import CATEGORY_LABELS, CLASS_COLORS, CLASS_LABELS, REVIEW_EVIDENCE, REVIEW_LABELS
from ..security import require
from .common import filter_detections
from .ingestion import STATIC_DATASET_MESSAGE

router = APIRouter(prefix="/detections", tags=["Detections"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EXPORT_KEYS = ("detection_id", "acq_datetime", "satellite", "instrument", "daynight", "frp", "bright_mir", "bright_tir", "confidence",
               "data_source", "class_code", "class_label", "category", "confidence_pct", "verification_required", "severity",
               "severity_score", "is_cross_alert", "source_id", "event_id", "facility_id", "facility_name", "place", "persistence_days",
               "review_label", "reviewed_by", "reviewed_at")
CSV_COLUMNS = ("latitude", "longitude") + EXPORT_KEYS


@router.get("")
def list_detections(
    class_code: Optional[str] = None,
    category: Optional[Literal["industrial", "vegetation"]] = None,
    severity: Optional[str] = Query(None, description="Comma-separated: NORMAL, HIGH, CRITICAL"),
    facility_id: Optional[str] = None,
    source_id: Optional[int] = None,
    data_source: Optional[str] = None,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    bbox: Optional[str] = Query(None, description="west,south,east,north"),
    min_frp: Optional[float] = Query(None, ge=0),
    verification_required: Optional[bool] = None,
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    items = filter_detections(service.snapshot["detections"], class_code, category, severity, facility_id, source_id, data_source,
                              start_date, end_date, bbox, min_frp, verification_required)
    return {
        "total": len(items),
        "offset": offset,
        "limit": limit,
        "items": items[offset:offset + limit],
        "window": service.snapshot["window"],
        "generated_at": service.snapshot["generated_at"],
    }


@router.get("/export.geojson")
def export_geojson(
    class_code: Optional[str] = None,
    category: Optional[Literal["industrial", "vegetation"]] = None,
    severity: Optional[str] = None,
    facility_id: Optional[str] = None,
    data_source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    bbox: Optional[str] = None,
    min_frp: Optional[float] = None,
    verification_required: Optional[bool] = None,
):
    items = filter_detections(service.snapshot["detections"], class_code, category, severity, facility_id, None, data_source,
                              start_date, end_date, bbox, min_frp, verification_required)
    filters = {"class_code": class_code, "category": category, "severity": severity, "facility_id": facility_id, "data_source": data_source,
               "start_date": start_date, "end_date": end_date, "bbox": bbox, "min_frp": min_frp, "verification_required": verification_required}
    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "observation_window": service.snapshot["window"],
            "filters": {k: v for k, v in filters.items() if v is not None},
            "sources": "NASA FIRMS active fire detections; OpenStreetMap (ODbL); ESA WorldCover 2021",
        },
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [d["longitude"], d["latitude"]]}, "properties": {k: d.get(k) for k in EXPORT_KEYS}}
            for d in items
        ],
    }
    return JSONResponse(collection, media_type="application/geo+json",
                        headers={"Content-Disposition": 'attachment; filename="thermal_detections.geojson"'})


@router.get("/export.csv")
def export_csv(
    class_code: Optional[str] = None,
    category: Optional[Literal["industrial", "vegetation"]] = None,
    severity: Optional[str] = None,
    facility_id: Optional[str] = None,
    data_source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    bbox: Optional[str] = None,
    min_frp: Optional[float] = None,
    verification_required: Optional[bool] = None,
):
    """Filtered detections as CSV (one row per FIRMS pixel, with classification, severity and analyst label)."""
    items = filter_detections(service.snapshot["detections"], class_code, category, severity, facility_id, None, data_source,
                              start_date, end_date, bbox, min_frp, verification_required)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    for d in items:
        writer.writerow(["" if d.get(column) is None else d.get(column) for column in CSV_COLUMNS])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="thermal_detections.csv"'})


class WhatIfRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    frp: float = Field(..., ge=0, le=50000, description="Fire radiative power, MW")
    bright_ti4: float = Field(..., ge=200, le=550, description="MIR brightness temperature, K")
    bright_ti5: float = Field(..., ge=150, le=420, description="TIR brightness temperature, K")
    daynight: Literal["D", "N"]
    acq_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    acq_time: Optional[str] = Field(None, pattern=r"^\d{3,4}$")
    instrument: Literal["VIIRS", "MODIS"] = "VIIRS"


@router.post("/what-if")
async def what_if(req: WhatIfRequest) -> Dict[str, Any]:
    if not service.classifier.available:
        raise HTTPException(status_code=503, detail="Classifier model is not trained yet")
    payload = req.model_dump()
    window = service.snapshot.get("window")
    payload["acq_date"] = payload["acq_date"] or (window["end"] if window else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    payload["acq_time"] = payload["acq_time"] or ("0800" if req.daynight == "D" else "2000")
    try:
        return await service.what_if(payload)
    except RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/upload")
async def upload_csv(file: UploadFile = File(...), user: Dict[str, Any] = Depends(require("upload_data"))) -> Dict[str, Any]:
    if settings.STATIC_DATASET:
        raise HTTPException(status_code=409, detail=STATIC_DATASET_MESSAGE)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 20 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    rows = parse_csv_text(text)
    if not rows:
        raise HTTPException(status_code=422, detail="The file has no data rows. Expected a NASA FIRMS CSV with a header line.")
    result = await service.ingest(rows, "user_upload", f"CSV upload '{file.filename}' by {user['username']}", landcover_deadline_s=120.0)
    audit.record(user["username"], "data.upload", f"Uploaded '{file.filename}': {result['message']}", "ingestion_run", result["run_id"])
    if result["records_valid"] == 0:
        raise HTTPException(status_code=422, detail={"message": "No valid FIRMS records in the file", "rejected_sample": result["rejected_sample"]})
    return result


@router.get("/{detection_id}")
def get_detection(detection_id: str) -> Dict[str, Any]:
    with SessionLocal() as db:
        row = db.query(DetectionModel).filter(DetectionModel.detection_id == detection_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Detection not found")
        detail = row.to_detail()
        incidents = [inc.to_dict() for inc in db.query(IncidentModel).filter(IncidentModel.detection_id == detection_id).all()]
    detail["class_label"] = CLASS_LABELS.get(detail["class_code"], detail["class_code"])
    detail["class_color"] = CLASS_COLORS.get(detail["class_code"])
    detail["category_label"] = CATEGORY_LABELS.get(detail["category"])
    detail["facility_name"] = (detail["analysis"].get("facility") or {}).get("name")
    detail["place"] = describe_place(detail["analysis"])
    detail["imagery_evidence"] = cached_evidence([detection_id]).get(detection_id)
    detail["incidents"] = incidents
    detail["reviews"] = reviews.reviews_for(detail)
    detail["current_review"] = detail["reviews"][0] if detail["reviews"] else None
    detail["location"] = reviews.location_info(detail, service.snapshot["detections"])
    return detail


class ReviewRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=32)
    scope: Literal["detection", "location"] = "detection"
    note: Optional[str] = Field(None, max_length=1000)
    evidence: List[str] = Field(default_factory=list, max_length=len(REVIEW_EVIDENCE))


@router.post("/{detection_id}/reviews")
def review_detection(detection_id: str, req: ReviewRequest, background: BackgroundTasks,
                     user: Dict[str, Any] = Depends(require("review_detections"))) -> Dict[str, Any]:
    """Label a detection, or its whole location, as an analyst. The label is stored next to the model's output, never over it."""
    try:
        review, noted = reviews.create_review(detection_id, req.label, req.scope, user["username"], req.note, req.evidence)
    except reviews.ReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if review is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    service.refresh_reviews()
    background.add_task(service.refresh_gis_store)
    detection = next((d for d in service.snapshot["detections"] if d["detection_id"] == detection_id), None) or {"detection_id": detection_id}
    location = reviews.location_info(detection, service.snapshot["detections"])
    target = f"location {location['group_key']} ({location['detections']} detections)" if req.scope == "location" else f"detection {detection_id}"
    model_label = CLASS_LABELS.get(review["model_class_code"], review["model_class_code"])
    audit.record(user["username"], "review.create", f"Labelled {target} as {REVIEW_LABELS[req.label]['label']} (model: {model_label})",
                 "detection", detection_id, {"review_id": review["id"], "label": req.label, "scope": req.scope, "incidents_noted": noted})
    return {"review": review, "incidents_noted": noted, "location": location, "reviews": reviews.reviews_for(detection)}

"""Analyst reviews: the review queue, recorded labels, agreement with the model and a training-data export.
Labels are created with POST /api/detections/{detection_id}/reviews."""
from typing import Any, Dict

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ..pipeline import reviews
from ..pipeline.service import service

router = APIRouter(prefix="/reviews", tags=["Analyst reviews"])


@router.get("/queue")
def review_queue(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """Locations flagged for verification that no analyst has labelled yet, most urgent first."""
    return reviews.review_queue(service.snapshot["detections"], limit)


@router.get("")
def list_reviews(limit: int = Query(200, ge=1, le=2000)) -> Dict[str, Any]:
    """Recorded reviews (newest first) and their agreement with the model."""
    return {"items": reviews.list_reviews(limit), "stats": reviews.review_stats(service.snapshot["detections"])}


@router.get("/export.csv")
def export_labels():
    """Every labelled detection as a training row: FIRMS record, model output, analyst label with provenance, 30 features."""
    return Response(reviews.export_csv(service.snapshot["detections"]), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="analyst_labels.csv"'})

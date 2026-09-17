import asyncio
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..pipeline import audit
from ..pipeline.service import service
from ..security import require
from .ingestion import STATIC_DATASET_MESSAGE

router = APIRouter(prefix="/drills", tags=["Drills"])


class DrillRequest(BaseModel):
    kind: Literal["industrial_excursion", "wildfire_near_facility"]
    facility_id: str


@router.post("")
async def run_drill(req: DrillRequest, user: Dict[str, Any] = Depends(require("run_drills"))) -> Dict[str, Any]:
    """Inject clearly labelled simulated detections (data_source='drill') to exercise alerting."""
    if settings.STATIC_DATASET:
        raise HTTPException(status_code=409, detail=STATIC_DATASET_MESSAGE)
    try:
        rows = service.drill_rows(req.kind, req.facility_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    result = await service.ingest(rows, "drill", f"Drill '{req.kind}' at {req.facility_id} by {user['username']}", landcover_deadline_s=30.0)
    audit.record(user["username"], "drill.run", f"Drill '{req.kind}' at {req.facility_id}: {result['records_inserted']} simulated detections",
                 "facility", req.facility_id, {"run_id": result["run_id"]})
    result["note"] = "Drill data is simulated and labelled data_source='drill'. Remove it with DELETE /api/drills."
    return result


@router.delete("")
async def purge_drills(user: Dict[str, Any] = Depends(require("run_drills"))) -> Dict[str, Any]:
    removed = service.purge_drills()
    if service.classifier.available:
        await asyncio.to_thread(service.analyze)
    audit.record(user["username"], "drill.purge",
                 f"Removed {removed['detections_removed']} drill detections and {removed['incidents_removed']} drill incidents", details=removed)
    return removed

from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import scheduler
from ..config import settings
from ..db.database import SessionLocal
from ..db.models import IngestionRunModel
from ..pipeline import audit
from ..pipeline.firms_client import FirmsError
from ..security import require

router = APIRouter(prefix="/ingestion", tags=["Data ingestion"])
STATIC_DATASET_MESSAGE = "This server shows a fixed dataset, so FIRMS sync, uploads and drills are off. Use the live server to add detections."


class SyncRequest(BaseModel):
    mode: Literal["auto", "public_feed", "map_key_api"] = "auto"
    window: Literal["24h", "48h", "7d"] = "24h"
    day_range: int = Field(2, ge=1, le=10)


@router.post("/sync")
async def sync(req: SyncRequest, user: Dict[str, Any] = Depends(require("sync_feed"))) -> Dict[str, Any]:
    if settings.STATIC_DATASET:
        raise HTTPException(status_code=409, detail=STATIC_DATASET_MESSAGE)
    try:
        result = await scheduler.sync_latest(trigger=f"manual:{user['username']}", mode=req.mode, window=req.window, day_range=req.day_range)
    except FirmsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit.record(user["username"], "data.sync", f"FIRMS sync ({req.mode}): {result.get('message', '')}", "ingestion_run", result.get("run_id"))
    return result


@router.get("/runs")
def runs(limit: int = 30) -> Dict[str, Any]:
    with SessionLocal() as db:
        items = [row.to_dict() for row in db.query(IngestionRunModel).order_by(IngestionRunModel.id.desc()).limit(max(1, min(limit, 200))).all()]
    return {"items": items}

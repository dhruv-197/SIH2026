import json
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db.database import SessionLocal
from ..db.models import IncidentModel, utcnow_iso
from ..pipeline import audit
from ..pipeline.imagery import cached_evidence
from ..security import require

router = APIRouter(prefix="/incidents", tags=["Incidents"])

TRANSITIONS = {
    "OPEN": {"ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"},
    "ACKNOWLEDGED": {"INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"},
    "INVESTIGATING": {"RESOLVED", "FALSE_POSITIVE"},
    "RESOLVED": {"OPEN"},
    "FALSE_POSITIVE": {"OPEN"},
}
STATUS_ORDER = {"OPEN": 0, "ACKNOWLEDGED": 1, "INVESTIGATING": 2, "RESOLVED": 3, "FALSE_POSITIVE": 4}
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2}


def _with_imagery(items):
    """Attach the stored Sentinel-2 finding for each incident's latest detection."""
    evidence = cached_evidence(item["detection_id"] for item in items)
    for item in items:
        found = evidence.get(item["detection_id"])
        item["imagery_evidence"] = {key: found.get(key) for key in ("status", "supports", "headline", "checked_at")} if found else None
    return items


class IncidentUpdate(BaseModel):
    status: Literal["OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"]
    note: Optional[str] = Field(None, max_length=1000)


@router.get("")
def list_incidents(status: Optional[str] = None, severity: Optional[str] = None, include_drills: bool = True) -> Dict[str, Any]:
    with SessionLocal() as db:
        query = db.query(IncidentModel)
        if status:
            query = query.filter(IncidentModel.status.in_([s.strip().upper() for s in status.split(",")]))
        if severity:
            query = query.filter(IncidentModel.severity.in_([s.strip().upper() for s in severity.split(",")]))
        if not include_drills:
            query = query.filter(IncidentModel.is_drill.is_(False))
        items = _with_imagery([row.to_dict() for row in query.all()])
    items.sort(key=lambda i: (STATUS_ORDER.get(i["status"], 9), SEVERITY_ORDER.get(i["severity"], 9), -_timestamp(i["updated_at"])))
    return {"total": len(items), "items": items}


def _timestamp(value: Optional[str]) -> float:
    try:
        return datetime.fromisoformat(value).timestamp() if value else 0.0
    except ValueError:
        return 0.0


@router.get("/{incident_id}")
def get_incident(incident_id: int) -> Dict[str, Any]:
    with SessionLocal() as db:
        row = db.get(IncidentModel, incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return _with_imagery([row.to_dict()])[0]


@router.patch("/{incident_id}")
def update_incident(incident_id: int, update: IncidentUpdate, user: Dict[str, Any] = Depends(require("triage_incidents"))) -> Dict[str, Any]:
    note = (update.note or "").strip() or None
    with SessionLocal() as db:
        row = db.get(IncidentModel, incident_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        if update.status != row.status and update.status not in TRANSITIONS.get(row.status, set()):
            raise HTTPException(status_code=409, detail=f"Cannot move an incident from {row.status} to {update.status}")
        previous = row.status
        history = json.loads(row.history_json or "[]")
        history.append({"at": utcnow_iso(), "by": user["username"], "from": previous, "status": update.status, "note": note})
        row.status = update.status
        row.history_json = json.dumps(history)
        row.updated_at = utcnow_iso()
        row.updated_by = user["username"]
        db.commit()
        result = _with_imagery([row.to_dict()])[0]
    change = previous if previous == update.status else f"{previous} -> {update.status}"
    audit.record(user["username"], "incident.status", f"Incident #{incident_id} ({result['title']}): {change}" + (f' - "{note}"' if note else ""),
                 "incident", incident_id, {"from": previous, "to": update.status, "note": note})
    return result

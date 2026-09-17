"""Append-only audit log of human actions: sign-ins, settings changes, incident triage, reviews, drills, uploads
and data syncs. What the system does on its own is recorded where it happens (incident history, ingestion runs)."""
import json
from typing import Any, Dict, List, Optional

from ..db.database import SessionLocal
from ..db.models import AuditLogModel, utcnow_iso


def record(actor: str, action: str, summary: str, entity_type: Optional[str] = None, entity_id: Any = None,
           details: Optional[Dict[str, Any]] = None) -> None:
    with SessionLocal() as db:
        db.add(AuditLogModel(
            at=utcnow_iso(), actor=(actor or "unknown")[:64], action=action, entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id)[:64], summary=summary,
            details_json=json.dumps(details, default=str) if details else None,
        ))
        db.commit()


def entries(limit: int = 200, action: Optional[str] = None, actor: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest first. action filters by prefix, e.g. "settings" or "incident"."""
    with SessionLocal() as db:
        query = db.query(AuditLogModel)
        if action:
            query = query.filter(AuditLogModel.action.like(f"{action}%"))
        if actor:
            query = query.filter(AuditLogModel.actor == actor)
        return [row.to_dict() for row in query.order_by(AuditLogModel.id.desc()).limit(max(1, min(limit, 1000))).all()]

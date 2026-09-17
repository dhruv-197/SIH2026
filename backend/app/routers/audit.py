"""Audit log of human actions, for signed-in users."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from ..pipeline import audit
from ..security import require

router = APIRouter(prefix="/audit", tags=["Audit log"])


@router.get("")
def audit_log(
    limit: int = Query(200, ge=1, le=1000),
    action: Optional[str] = Query(None, max_length=48, description="Action prefix, e.g. settings, incident, review, auth"),
    actor: Optional[str] = Query(None, max_length=64),
    user: Dict[str, Any] = Depends(require("view_audit")),
) -> Dict[str, Any]:
    return {"items": audit.entries(limit, action, actor)}

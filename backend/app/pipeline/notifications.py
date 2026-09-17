"""Automatic incident notifications.

New and re-opened incidents are sent as JSON to the webhook configured in Settings - for example a
Slack or Microsoft Teams incoming webhook (both display the "text" field) or an alerting relay that
forwards to SMS or email. Every delivery attempt is written to the incident's history, so the log shows
when the alert went out and whether it arrived. Nothing is sent in offline mode.
"""
import json
from typing import Any, Dict, List, Optional, Sequence

import httpx

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import DetectionModel, IncidentModel, utcnow_iso
from .settings_store import load_settings

SEVERITY_RANK = {"NORMAL": 0, "HIGH": 1, "CRITICAL": 2}
INCIDENT_KEYS = ("id", "incident_type", "severity", "status", "title", "summary", "recommended_action", "authorities",
                 "facility_id", "detection_id", "latitude", "longitude", "is_drill", "created_at", "reason_codes", "policy_version")
DETECTION_KEYS = ("detection_id", "acq_datetime", "satellite", "instrument", "daynight", "frp", "latitude", "longitude",
                  "class_code", "category", "confidence_pct", "verification_required")


def build_payload(incident: Dict[str, Any], detection: Optional[Dict[str, Any]], event: str, dashboard_url: str = "") -> Dict[str, Any]:
    drill = " (DRILL - simulated data)" if incident.get("is_drill") else ""
    text = f"[{incident['severity']}] {incident['title']}{drill}\n{incident['summary']}\nAction: {incident['recommended_action']}"
    if incident.get("reason_codes"):
        text += f"\nReason codes: {', '.join(incident['reason_codes'])} (alert policy {incident.get('policy_version') or 'unknown'})"
    links: Dict[str, str] = {}
    base = (dashboard_url or "").rstrip("/")
    if base:
        links = {
            "incident": f"{base}/#/incidents?incident={incident['id']}",
            "map": f"{base}/#/map?detection={incident['detection_id']}",
        }
        text += f"\n{links['incident']}"
    return {
        "event": event,
        "source": "GeoThermal Sentinel",
        "sent_at": utcnow_iso(),
        "text": text,
        "incident": {key: incident.get(key) for key in INCIDENT_KEYS},
        "detection": {key: detection.get(key) for key in DETECTION_KEYS} if detection else None,
        "links": links,
    }


async def deliver(url: str, payloads: Sequence[Dict[str, Any]], transport: Optional[httpx.AsyncBaseTransport] = None) -> List[str]:
    """POST every payload to the webhook; returns one history note per payload."""
    notes = []
    async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": settings.HTTP_USER_AGENT}, transport=transport) as client:
        for payload in payloads:
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                notes.append(f"Webhook notification failed ({type(exc).__name__})")
                continue
            if 200 <= response.status_code < 300:
                notes.append(f"Notification delivered to the webhook (HTTP {response.status_code})")
            else:
                notes.append(f"Webhook notification failed (HTTP {response.status_code})")
    return notes


async def notify_incidents(opened: Sequence[int], reopened: Sequence[int] = ()) -> Dict[str, Any]:
    """Notify the webhook about incidents that were just opened or re-opened by the analysis."""
    events = {int(i): "incident.opened" for i in opened}
    events.update({int(i): "incident.reopened" for i in reopened})
    summary: Dict[str, Any] = {"eligible": 0, "delivered": 0, "failed": 0, "skipped": None}
    if not events:
        return summary
    with SessionLocal() as db:
        values = load_settings(db)
        if not values["webhook_url"]:
            summary["skipped"] = "no webhook configured"
            return summary
        if not values["notify_incidents"]:
            summary["skipped"] = "automatic notifications are turned off"
            return summary
        if settings.OFFLINE:
            summary["skipped"] = "offline mode"
            return summary
        min_rank = SEVERITY_RANK.get(values["notify_min_severity"], 1)
        incidents = [
            row.to_dict() for row in db.query(IncidentModel).filter(IncidentModel.id.in_(list(events))).all()
            if row.status == "OPEN" and SEVERITY_RANK.get(row.severity, 0) >= min_rank
        ]
        detections = {
            row.detection_id: row.to_summary()
            for row in db.query(DetectionModel).filter(DetectionModel.detection_id.in_([i["detection_id"] for i in incidents])).all()
        }
    payloads = [build_payload(i, detections.get(i["detection_id"]), events[i["id"]], values["dashboard_url"]) for i in incidents]
    summary["eligible"] = len(payloads)
    if not payloads:
        return summary
    notes = await deliver(values["webhook_url"], payloads)
    with SessionLocal() as db:
        for incident, note in zip(incidents, notes):
            row = db.get(IncidentModel, incident["id"])
            if row is None:
                continue
            history = json.loads(row.history_json or "[]")
            history.append({"at": utcnow_iso(), "by": "system", "status": row.status, "note": note})
            row.history_json = json.dumps(history)
        db.commit()
    summary["delivered"] = sum(1 for note in notes if note.startswith("Notification delivered"))
    summary["failed"] = len(notes) - summary["delivered"]
    return summary

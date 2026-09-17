import asyncio
from datetime import datetime, timezone
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException

from .. import scheduler
from ..config import settings as app_settings
from ..db.database import SessionLocal
from ..pipeline import audit, notifications
from ..pipeline.firms_client import FirmsError, check_map_key
from ..pipeline.service import service
from ..pipeline.settings_store import SECRET_KEYS, SettingsError, load_settings, public_settings, save_settings, severity_config, validate_update
from ..pipeline.severity import REASON_CODES, policy_info
from ..security import require

router = APIRouter(prefix="/settings", tags=["Settings"])
ANALYSIS_KEYS = {"zscore_threshold", "frp_threshold_mw", "cross_alert_km", "high_intensity_frp_mw", "retention_days"}


def _alert_policy(values: Dict[str, Any]) -> Dict[str, Any]:
    return {**policy_info(severity_config(values)), "reason_codes": REASON_CODES}


@router.get("")
def get_settings() -> Dict[str, Any]:
    with SessionLocal() as db:
        values = load_settings(db)
    return {
        "settings": public_settings(values),
        "environment_map_key_configured": bool(app_settings.NASA_FIRMS_MAP_KEY),
        "next_scheduled_sync": scheduler.next_run_time(),
        "offline_mode": app_settings.OFFLINE,
        "static_dataset": app_settings.STATIC_DATASET,
        "alert_policy": _alert_policy(values),
    }


@router.patch("")
async def update_settings(payload: Dict[str, Any] = Body(...), user: Dict[str, Any] = Depends(require("modify_settings"))) -> Dict[str, Any]:
    try:
        clean = validate_update(payload)
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with SessionLocal() as db:
        before = load_settings(db)
        save_settings(db, clean, user["username"])
        values = load_settings(db)
    parts, changes = [], {}
    for key in sorted(clean):
        if before[key] == values[key]:
            continue
        if key in SECRET_KEYS:
            changes[key] = {"changed": True}
            parts.append(f"{'set' if values[key] else 'cleared'} {key}")
        else:
            changes[key] = {"from": before[key], "to": values[key]}
            parts.append(f"{key} {before[key]} -> {values[key]}")
    if parts:
        old_policy, new_policy = policy_info(severity_config(before))["version"], policy_info(severity_config(values))["version"]
        if old_policy != new_policy:
            changes["alert_policy"] = {"from": old_policy, "to": new_policy}
        audit.record(user["username"], "settings.update", "Changed " + ", ".join(parts), "settings", None, changes)
    if "auto_sync_interval_mins" in clean:
        scheduler.reschedule(clean["auto_sync_interval_mins"])
    reanalysed, notified = False, None
    if ANALYSIS_KEYS & set(clean) and service.classifier.available and service.snapshot.get("detections"):
        summary = await asyncio.to_thread(service.analyze)
        reanalysed = True
        notified = await notifications.notify_incidents(summary.get("opened_incident_ids", []), summary.get("reopened_incident_ids", []))
    return {"settings": public_settings(values), "updated": sorted(clean), "reanalysed": reanalysed, "notifications": notified,
            "alert_policy": _alert_policy(values)}


@router.post("/firms-key/check")
async def check_firms_key(user: Dict[str, Any] = Depends(require("modify_settings"))) -> Dict[str, Any]:
    with SessionLocal() as db:
        key = load_settings(db)["firms_api_key"] or app_settings.NASA_FIRMS_MAP_KEY
    if not key:
        raise HTTPException(status_code=400, detail="No MAP_KEY configured")
    try:
        return {"valid": True, "status": await check_map_key(key)}
    except FirmsError as exc:
        return {"valid": False, "error": str(exc)}


@router.post("/test-alert")
async def send_test_alert(user: Dict[str, Any] = Depends(require("send_test_alert"))) -> Dict[str, Any]:
    with SessionLocal() as db:
        url = load_settings(db)["webhook_url"]
    if not url:
        raise HTTPException(status_code=400, detail="Set a webhook URL in settings first")
    if app_settings.OFFLINE:
        raise HTTPException(status_code=503, detail="Offline mode is enabled; outbound requests are disabled")
    payload = {
        "type": "TEST",
        "message": "Test notification from GeoThermal Sentinel. No incident has occurred.",
        "sent_by": user["username"],
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"User-Agent": app_settings.HTTP_USER_AGENT}) as client:
            response = await client.post(url, json=payload)
        delivered = 200 <= response.status_code < 300
        audit.record(user["username"], "settings.test_alert", f"Test notification {'delivered' if delivered else 'failed'} (HTTP {response.status_code})")
        return {"delivered": delivered, "http_status": response.status_code, "payload": payload}
    except httpx.HTTPError as exc:
        audit.record(user["username"], "settings.test_alert", f"Test notification failed ({type(exc).__name__})")
        return {"delivered": False, "error": f"{type(exc).__name__}: could not reach the webhook", "payload": payload}

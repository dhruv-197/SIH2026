"""Background jobs: periodic NASA FIRMS ingestion and first-start bootstrap."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .db.database import SessionLocal
from .db.models import IngestionRunModel
from .pipeline.firms_client import fetch_area_api, fetch_public_feed, load_snapshot
from .pipeline.service import service
from .pipeline.settings_store import load_settings

logger = logging.getLogger("geothermal.scheduler")
scheduler = AsyncIOScheduler(timezone="UTC")
JOB_ID = "firms_sync"


def _settings() -> Dict[str, Any]:
    with SessionLocal() as db:
        return load_settings(db)


async def sync_latest(trigger: str = "scheduler", mode: str = "auto", window: str = "24h", day_range: int = 2) -> Dict[str, Any]:
    values = _settings()
    if trigger == "scheduler" and not values["satellite_auto_polling"]:
        return {"skipped": "Automatic polling is turned off in settings"}
    map_key = values["firms_api_key"] or settings.NASA_FIRMS_MAP_KEY
    use_api = mode == "map_key_api" or (mode == "auto" and bool(map_key))
    if use_api:
        if not map_key:
            raise ValueError("No NASA FIRMS MAP_KEY is configured")
        rows, feeds = await fetch_area_api(map_key, day_range=day_range)
        label, data_source = f"FIRMS area API ({day_range} day range)", "firms_api"
    else:
        rows, feeds = await fetch_public_feed(window)
        label, data_source = f"FIRMS public NRT feed ({window})", "firms_public_nrt"
    return await service.ingest(rows, data_source, label, extra_details={"feeds": feeds, "trigger": trigger})


def next_sync_at(last_finished: Optional[datetime], minutes: int, now: datetime) -> datetime:
    """Next FIRMS fetch. A restart does not wait another full interval when the last fetch is already stale."""
    interval = timedelta(minutes=minutes)
    if last_finished is None:
        return now + timedelta(seconds=5)
    if last_finished.tzinfo is None:
        last_finished = last_finished.replace(tzinfo=timezone.utc)
    due = last_finished.astimezone(timezone.utc) + interval
    if due <= now:
        return now + timedelta(seconds=5)
    return due


def _last_success_at() -> Optional[datetime]:
    with SessionLocal() as db:
        row = (
            db.query(IngestionRunModel)
            .filter(IngestionRunModel.status == "succeeded", IngestionRunModel.finished_at.isnot(None))
            .order_by(IngestionRunModel.id.desc())
            .first()
        )
        if not row:
            return None
        return datetime.fromisoformat(row.finished_at)


def _schedule_job(minutes: int) -> None:
    when = next_sync_at(_last_success_at(), minutes, datetime.now(timezone.utc))
    scheduler.add_job(
        _scheduled_job,
        "interval",
        minutes=minutes,
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=minutes * 60,
        next_run_time=when,
    )


async def _scheduled_job() -> None:
    try:
        result = await sync_latest("scheduler")
        logger.info("Scheduled FIRMS sync: %s", result.get("message") or result)
    except Exception as exc:  # keep the scheduler alive; the failure is recorded in ingestion_runs
        logger.warning("Scheduled FIRMS sync failed: %s", exc)


async def bootstrap_if_empty() -> None:
    """First start with an empty database: load the bundled real FIRMS snapshot."""
    if service.snapshot.get("detections"):
        return
    rows, feeds = load_snapshot()
    if not rows:
        logger.warning("No bundled FIRMS snapshot found; waiting for the first sync")
        return
    await service.ingest(rows, "firms_public_nrt", "Bundled FIRMS snapshot (first start)",
                         fetch_landcover=not settings.OFFLINE, landcover_deadline_s=900.0, extra_details={"feeds": feeds})


def start() -> None:
    if scheduler.running:
        return
    _schedule_job(int(_settings()["auto_sync_interval_mins"]))
    scheduler.start()


def reschedule(minutes: int) -> None:
    if scheduler.running:
        _schedule_job(int(minutes))


def next_run_time():
    job = scheduler.get_job(JOB_ID) if scheduler.running else None
    return job.next_run_time.isoformat() if job and job.next_run_time else None


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)

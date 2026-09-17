"""GeoThermal Sentinel API - classification and monitoring of industrial and vegetation fires
from NASA FIRMS detections, OpenStreetMap industrial geometry and ESA WorldCover land cover."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import scheduler
from .config import settings
from .db.database import SessionLocal
from .db.models import IncidentModel, IngestionRunModel
from .pipeline.service import service
from .pipeline.settings_store import load_settings, severity_config
from .pipeline.severity import policy_info
from .routers import assistant, auth, context, detections, drills, facilities, gis, incidents, ingestion, reports, sources, stats
from .routers import audit as audit_router
from .routers import reviews as reviews_router
from .routers import settings as settings_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("geothermal")


_background_tasks = set()


def _run_in_background(coroutine) -> None:
    task = asyncio.create_task(coroutine)
    _background_tasks.add(task)  # keep a reference until the task finishes
    task.add_done_callback(_background_tasks.discard)


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.startup()
    if settings.JWT_SECRET_IS_EPHEMERAL:
        logger.warning("JWT_SECRET_KEY is not set - using a random key; sessions end when the server restarts")
    if settings.STATIC_DATASET:
        logger.info("Fixed dataset%s: no FIRMS polling, sync or upload", f" '{settings.DATASET_LABEL}'" if settings.DATASET_LABEL else "")
    if not settings.DISABLE_BACKGROUND_JOBS:
        if service.snapshot.get("detections"):
            service.start_background_checks()  # Sentinel-2 evidence and wind for open incidents that have none yet
        elif not settings.STATIC_DATASET:
            _run_in_background(scheduler.bootstrap_if_empty())
        if not settings.STATIC_DATASET:
            scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=__doc__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

for module in (auth, detections, sources, facilities, stats, context, incidents, reviews_router, ingestion, drills, reports, assistant, gis,
               audit_router, settings_router):
    app.include_router(module.router, prefix=settings.API_V1_STR)


@app.get("/api/health", tags=["System"])
def health():
    with SessionLocal() as db:
        last_run = db.query(IngestionRunModel).order_by(IngestionRunModel.id.desc()).first()
        open_incidents = db.query(IncidentModel).filter(IncidentModel.status.in_(("OPEN", "ACKNOWLEDGED", "INVESTIGATING"))).count()
        policy = policy_info(severity_config(load_settings(db)))
    snapshot = service.snapshot
    problems = []
    if not service.classifier.available:
        problems.append(f"classifier model not available ({service.classifier.load_error or 'file missing'}) - run backend/ml/train.py")
    if not snapshot.get("detections"):
        problems.append("no detections loaded yet")
    if service.osm_feature_count == 0:
        problems.append("OpenStreetMap industrial extract missing - run backend/scripts/fetch_osm_industrial.py")
    return {
        "status": "ok" if not problems else "degraded",
        "problems": problems,
        "version": settings.VERSION,
        "detections": len(snapshot.get("detections", [])),
        "persistent_sources": len(snapshot.get("sources", [])),
        "observation_window": snapshot.get("window"),
        "analysis": service.analysis_summary,
        "last_ingestion": last_run.to_dict() if last_run else None,
        "next_scheduled_sync": scheduler.next_run_time(),
        "open_incidents": open_incidents,
        "model": service.classifier.metadata,
        "alert_policy_version": policy["version"],
        "reference_data": {
            "osm_features": service.osm_feature_count,
            "catalog_facilities": len(service.facilities),
            "landcover_cache": service.landcover.coverage(),
        },
        "dataset": {"label": settings.DATASET_LABEL or None, "static": settings.STATIC_DATASET},
        "last_review_at": service.last_review_at,
        "offline_mode": settings.OFFLINE,
        "sessions_survive_restart": not settings.JWT_SECRET_IS_EPHEMERAL,
    }


# The built dashboard is served from the same process when it exists (registered last, so API routes win).
# The Vite dev server is only needed while changing the frontend.
if os.path.isdir(settings.FRONTEND_DIST_DIR):
    app.mount("/", StaticFiles(directory=settings.FRONTEND_DIST_DIR, html=True), name="dashboard")

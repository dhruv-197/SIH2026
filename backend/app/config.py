"""Runtime configuration. Every value can be overridden with an environment variable."""
import os
import secrets
from typing import List, Tuple

from pydantic import BaseModel

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(APP_DIR)
DATA_DIR = os.path.join(APP_DIR, "data")
DEFAULT_DB_PATH = os.getenv("GEOTHERMAL_DB_PATH", os.path.join(DATA_DIR, "geothermal.db"))


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    PROJECT_NAME: str = "GeoThermal Sentinel"
    VERSION: str = "2.2.0"
    API_V1_STR: str = "/api"

    DATA_DIR: str = DATA_DIR
    DB_PATH: str = DEFAULT_DB_PATH
    # GeoPackage GIS layer store, rewritten after every analysis and kept next to the database.
    GIS_STORE_PATH: str = os.getenv("GEOTHERMAL_GIS_STORE_PATH", os.path.join(os.path.dirname(os.path.abspath(DEFAULT_DB_PATH)), "gis", "geothermal_sentinel.gpkg"))
    OSM_FEATURES_PATH: str = os.path.join(DATA_DIR, "osm_industrial_india.geojson")
    INDIA_BOUNDARY_PATH: str = os.path.join(DATA_DIR, "india_boundary.geojson")
    FACILITY_CATALOG_PATH: str = os.path.join(DATA_DIR, "facility_catalog.json")
    FIRMS_SNAPSHOT_DIR: str = os.path.join(DATA_DIR, "firms_snapshot")
    MODEL_BUNDLE_PATH: str = os.getenv("GEOTHERMAL_MODEL_PATH", os.path.join(BACKEND_DIR, "ml", "model_bundle.joblib"))
    EVALUATION_REPORT_PATH: str = os.path.join(BACKEND_DIR, "ml", "evaluation_report.json")
    # Built dashboard (npm run build); served by the API when present, so one process runs everything.
    FRONTEND_DIST_DIR: str = os.getenv("GEOTHERMAL_FRONTEND_DIST", os.path.join(os.path.dirname(BACKEND_DIR), "frontend", "dist"))

    # When true, no outbound network calls are made (tests, air-gapped demos).
    OFFLINE: bool = _env_bool("GEOTHERMAL_OFFLINE", False)
    # When true, the API does not bootstrap or poll data on startup (used by tests).
    DISABLE_BACKGROUND_JOBS: bool = _env_bool("GEOTHERMAL_DISABLE_BACKGROUND_JOBS", False)
    # A fixed dataset (for example an archive week) served as it is: no first-start bootstrap, no FIRMS polling and
    # no sync or upload. DATASET_LABEL names the dataset in the dashboard.
    STATIC_DATASET: bool = _env_bool("GEOTHERMAL_STATIC_DATASET", False)
    DATASET_LABEL: str = os.getenv("GEOTHERMAL_DATASET_LABEL", "")

    NASA_FIRMS_MAP_KEY: str = os.getenv("NASA_FIRMS_MAP_KEY", "")
    FIRMS_PUBLIC_BASE: str = "https://firms.modaps.eosdis.nasa.gov/data/active_fire"
    FIRMS_API_BASE: str = "https://firms.modaps.eosdis.nasa.gov/api"
    FIRMS_REGION: str = "South_Asia"
    # west, south, east, north - used for FIRMS area requests before the India polygon filter
    INDIA_BBOX: Tuple[float, float, float, float] = (68.0, 6.5, 97.5, 37.2)
    RETENTION_DAYS: int = int(os.getenv("GEOTHERMAL_RETENTION_DAYS", "45"))

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(48)
    JWT_SECRET_IS_EPHEMERAL: bool = not bool(os.getenv("JWT_SECRET_KEY"))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
    ANALYST_PASSWORD: str = os.getenv("ANALYST_PASSWORD", "analyst-demo")
    COMMANDER_PASSWORD: str = os.getenv("COMMANDER_PASSWORD", "commander-demo")

    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ]

    PLANETARY_COMPUTER_DATA_API: str = "https://planetarycomputer.microsoft.com/api/data/v1"
    PLANETARY_COMPUTER_STAC_API: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    OVERPASS_API_URL: str = os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")
    # Wind for cross-alerts: recent days from the weather-model API, older dates from the ERA5 archive (Open-Meteo, CC BY 4.0).
    OPEN_METEO_FORECAST_API: str = "https://api.open-meteo.com/v1/forecast"
    OPEN_METEO_ARCHIVE_API: str = "https://archive-api.open-meteo.com/v1/archive"
    HTTP_USER_AGENT: str = "GeoThermalSentinel/2.2 (SIH 2026 prototype)"


settings = Settings()

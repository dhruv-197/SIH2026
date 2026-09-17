"""Geospatial context for a location or detection: OpenStreetMap industry, ESA WorldCover land cover, real satellite
scenes (Sentinel-2, Landsat, Sentinel-1) found via the Planetary Computer STAC API, and the wind (Open-Meteo)."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import DetectionModel
from ..pipeline import audit, weather
from ..pipeline import imagery as imagery_evidence_pipeline
from ..pipeline.geo_context import feature_name
from ..pipeline.landcover import cell_key, describe
from ..pipeline.service import service
from ..security import current_user

router = APIRouter(prefix="/context", tags=["Geospatial context"])
_imagery_cache: Dict[str, Dict[str, Any]] = {}
OSM_TAG_KEYS = ("name", "operator", "industrial", "power", "plant:source", "man_made", "landuse", "resource", "product")
WIND_FACILITY_KM = 10.0  # relate the wind to critical infrastructure within this distance of the detection


@router.get("/osm")
async def osm_context(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=25),
    live: bool = Query(False, description="Also query the live Overpass API"),
) -> Dict[str, Any]:
    lookup = service.geo.lookup(lat, lon)
    result = {
        "latitude": lat,
        "longitude": lon,
        "inside_feature": lookup["inside_feature"],
        "nearest_feature": lookup["nearest"],
        "features_within_radius": service.geo.features_near(lat, lon, radius_km)[:30],
        "facility": service.facility_for(lat, lon),
        "dataset": {"source": "OpenStreetMap extract via Overpass API", "features": service.osm_feature_count, "license": "ODbL 1.0 - (c) OpenStreetMap contributors"},
    }
    if live:
        result["live_overpass"] = await _live_overpass(lat, lon, radius_km)
    return result


async def _live_overpass(lat: float, lon: float, radius_km: float) -> Dict[str, Any]:
    if settings.OFFLINE:
        return {"status": "skipped", "reason": "offline mode"}
    r = int(radius_km * 1000)
    query = (
        f'[out:json][timeout:25];('
        f'nwr(around:{r},{lat},{lon})["industrial"];'
        f'nwr(around:{r},{lat},{lon})["power"="plant"];'
        f'nwr(around:{r},{lat},{lon})["man_made"~"flare|works|kiln|petroleum_well|chimney"];'
        f'nwr(around:{r},{lat},{lon})["landuse"~"industrial|quarry"];'
        f');out tags center 40;'
    )
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": settings.HTTP_USER_AGENT}) as client:
            response = await client.post(settings.OVERPASS_API_URL, data={"data": query})
        if response.status_code != 200:
            return {"status": "error", "reason": f"Overpass returned HTTP {response.status_code}"}
        elements = response.json().get("elements", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: Overpass unavailable"}
    return {
        "status": "ok",
        "count": len(elements),
        "elements": [
            {
                "osm_id": f"{el['type']}/{el['id']}",
                "osm_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
                "tags": {k: v for k, v in el.get("tags", {}).items() if k in OSM_TAG_KEYS},
            }
            for el in elements
        ],
    }


@router.get("/osm-features")
def osm_features(
    bbox: str = Query(..., description="west,south,east,north"),
    limit: int = Query(4000, ge=1, le=10000),
) -> Dict[str, Any]:
    """Industrial / extractive context features intersecting a map view, as GeoJSON."""
    from shapely.geometry import mapping

    from .common import parse_bbox

    west, south, east, north = parse_bbox(bbox)
    if (east - west) * (north - south) > 900:
        raise HTTPException(status_code=422, detail="Requested area is too large; zoom in")
    matches = service.geo.features_in_bbox(west, south, east, north)
    return {
        "type": "FeatureCollection",
        "truncated": len(matches) > limit,
        "license": "ODbL 1.0 - (c) OpenStreetMap contributors",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(feat.geometry),
                "properties": {
                    "feature_id": feat.feature_id,
                    "name": feat.name,
                    "category": feat.category,
                    "subtype": feat.subtype,
                    "source": feat.source,
                    "osm_url": f"https://www.openstreetmap.org/{feat.feature_id}" if feat.source == "osm" else None,
                },
            }
            for feat in matches[:limit]
        ],
    }


@router.get("/landcover")
async def landcover(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> Dict[str, Any]:
    entry = service.landcover.entry(lat, lon)
    fetched = None
    if entry is None and not settings.OFFLINE:
        fetched = await service.landcover.fetch_cells([cell_key(lat, lon)], deadline_s=25.0)
        entry = service.landcover.entry(lat, lon)
    return {"latitude": lat, "longitude": lon, "landcover": describe(entry), "fetch": fetched}


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _stac_search(client: httpx.AsyncClient, collection: str, lat: float, lon: float, center: datetime,
                       days: int, max_cloud: Optional[float] = None, limit: int = 3) -> Dict[str, Any]:
    start, end = (center - timedelta(days=days)).date(), (center + timedelta(days=days)).date()
    body: Dict[str, Any] = {
        "collections": [collection],
        "bbox": [lon - 0.005, lat - 0.005, lon + 0.005, lat + 0.005],
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 50,
    }
    if max_cloud is not None:
        body["query"] = {"eo:cloud_cover": {"lt": max_cloud}}
    try:
        response = await client.post(f"{settings.PLANETARY_COMPUTER_STAC_API}/search", json=body)
        response.raise_for_status()
        features = response.json().get("features", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: STAC search failed", "items": []}

    half = 0.02  # ~2 km either side
    chip_bbox = f"{lon - half:.5f},{lat - half:.5f},{lon + half:.5f},{lat + half:.5f}"
    items: List[Dict[str, Any]] = []
    for feat in sorted(features, key=lambda f: abs((_parse_datetime(f["properties"]["datetime"]) - center).total_seconds()))[:limit]:
        props = feat["properties"]
        acquired = _parse_datetime(props["datetime"])
        item = {
            "id": feat["id"],
            "collection": collection,
            "datetime": props["datetime"],
            "days_from_detection": round((acquired - center).total_seconds() / 86400.0, 1),
            "cloud_cover_pct": props.get("eo:cloud_cover"),
            "platform": props.get("platform"),
            "stac_url": f"{settings.PLANETARY_COMPUTER_STAC_API}/collections/{collection}/items/{feat['id']}",
            "preview_url": feat.get("assets", {}).get("rendered_preview", {}).get("href"),
        }
        if collection == "sentinel-2-l2a":
            item["chip_url"] = (f"{settings.PLANETARY_COMPUTER_DATA_API}/item/bbox/{chip_bbox}/512x512.png"
                                f"?collection={collection}&item={feat['id']}&assets=visual&asset_bidx=visual%7C1,2,3&nodata=0")
            item["swir_chip_url"] = (f"{settings.PLANETARY_COMPUTER_DATA_API}/item/bbox/{chip_bbox}/512x512.png"
                                     f"?collection={collection}&item={feat['id']}&assets=B12&assets=B8A&assets=B04&rescale=0,5000&nodata=0")
        items.append(item)
    return {"status": "ok" if items else "none_found", "search_window_days": days, "items": items}


@router.get("/imagery/{detection_id}")
async def imagery(detection_id: str) -> Dict[str, Any]:
    if detection_id in _imagery_cache:
        return _imagery_cache[detection_id]
    with SessionLocal() as db:
        row = db.query(DetectionModel).filter(DetectionModel.detection_id == detection_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Detection not found")
        lat, lon, acquired, acq_date = row.latitude, row.longitude, row.acq_datetime, row.acq_date
    center = datetime.strptime(acquired[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    gibs = {
        "viirs_true_color": f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{acq_date}/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.jpg",
        "viirs_thermal_anomalies": f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_NOAA20_Thermal_Anomalies_375m_All/default/{acq_date}/GoogleMapsCompatible_Level9/{{z}}/{{y}}/{{x}}.png",
    }
    if settings.OFFLINE:
        return {"detection_id": detection_id, "status": "skipped", "reason": "offline mode", "gibs_tiles": gibs}
    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": settings.HTTP_USER_AGENT}) as client:
        sentinel2, landsat, sentinel1 = await asyncio.gather(
            _stac_search(client, "sentinel-2-l2a", lat, lon, center, days=15, max_cloud=60),
            _stac_search(client, "landsat-c2-l2", lat, lon, center, days=16, max_cloud=60),
            _stac_search(client, "sentinel-1-grd", lat, lon, center, days=12),
        )
    result = {
        "detection_id": detection_id,
        "latitude": lat,
        "longitude": lon,
        "detection_time": acquired,
        "sentinel_2_l2a": sentinel2,
        "landsat_c2_l2": landsat,
        "sentinel_1_grd": sentinel1,
        "gibs_tiles": gibs,
        "note": "Scenes are the nearest real acquisitions in time; they are not simultaneous with the FIRMS detection.",
    }
    if all(section["status"] != "error" for section in (sentinel2, landsat, sentinel1)):
        _imagery_cache[detection_id] = result
    return result


@router.get("/imagery-evidence/{detection_id}")
async def imagery_evidence(
    detection_id: str,
    refresh: bool = Query(False, description="Measure again even when evidence is stored (signed-in users)"),
    user: Optional[Dict[str, Any]] = Depends(current_user),
) -> Dict[str, Any]:
    """Sentinel-2 shortwave-infrared hot spots and burn scars around a detection; stored after the first check."""
    if refresh and user is None:
        raise HTTPException(status_code=401, detail="Sign in to re-run an imagery check")
    result = await imagery_evidence_pipeline.evidence_for_detection(detection_id, refresh=refresh)
    if result is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    if refresh and user is not None:
        audit.record(user["username"], "imagery.recheck", f"Re-ran the Sentinel-2 check: {result['headline']}", "detection", detection_id)
    return result


@router.get("/wind/{detection_id}")
async def wind(detection_id: str) -> Dict[str, Any]:
    """Wind at the detection's overpass hour, and how it blows relative to the nearest critical infrastructure."""
    with SessionLocal() as db:
        row = db.query(DetectionModel).filter(DetectionModel.detection_id == detection_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Detection not found")
        lat, lon, acquired = row.latitude, row.longitude, row.acq_datetime
        analysis = json.loads(row.analysis_json or "{}")
    approach = (analysis.get("severity") or {}).get("fire_approach") or {}
    facility_lat, facility_lon, facility = approach.get("facility_latitude"), approach.get("facility_longitude"), approach.get("facility")
    reference = analysis.get("nearest_critical_infrastructure")
    if facility_lat is None and reference and reference.get("distance_km", WIND_FACILITY_KM + 1) <= WIND_FACILITY_KM:
        feature = service.geo.feature(reference["feature_id"])
        if feature is not None:
            centre = feature.geometry.centroid
            facility_lat, facility_lon, facility = centre.y, centre.x, feature_name(feature)
    when = datetime.strptime(acquired[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    return {"detection_id": detection_id, **(await weather.wind_for_fire(lat, lon, when, facility_lat, facility_lon, facility))}

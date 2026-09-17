"""Satellite imagery evidence for a detection: Sentinel-2 SWIR heat and burn scars.

FIRMS reports that a 375 m pixel was hot. Sentinel-2 (20 m shortwave infrared, morning overpass, revisit
of 2-5 days) shows independently of the classifier what was hot:

- Heat: very hot surfaces (flares, furnaces, coal fires, active fire fronts) raise shortwave-infrared
  reflectance. A pixel is hot when the Normalized Hotspot Index NHI_SWIR = (B12 - B11) / (B12 + B11) exceeds
  0.1 and B12 reflectance exceeds 0.15 (after Marchese et al. 2019). A scene shows heat with at least two hot
  pixels, or one strongly hot pixel. Heat on dates at least four days apart marks a persistent source.
- Burn scar: burned vegetation lowers the Normalized Burn Ratio NBR = (B8A - B12) / (B8A + B12). A drop of
  0.1 or more in the mean over clear land, or of 0.2 or more in its darkest 5 % (small burned fields), between
  the last clear scene before and the first clear scene after the detection marks a burn scar (Key & Benson 2006).

Verdicts: a burn scar supports a vegetation fire; persistent heat without a burn scar supports an industrial
high-temperature source; both together are reported as mixed; heat on one date only confirms real heat.
Cloud and shadow come from the scene classification layer (SCL 3, 8, 9, 10). Sentinel-2 passes in the
morning, so short or night-only events are often invisible: absence of evidence is not evidence of absence.

Statistics are computed server-side by the Microsoft Planetary Computer data API over a ~780 m box around
the detection, so no imagery is downloaded.
"""
import asyncio
import json
import math
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from ..config import settings
from ..db.database import SessionLocal
from ..db.models import DetectionModel, ImageryEvidenceModel, IncidentModel, utcnow_iso

COLLECTION = "sentinel-2-l2a"
FOOTPRINT_HALF_DEG = 0.0035  # ~780 m box: the VIIRS pixel plus its geolocation uncertainty
FOOTPRINT_M = 780
SEARCH_DAYS_BEFORE = 30
SEARCH_DAYS_AFTER = 20
HOTSPOT_WINDOW_DAYS = 12
MIN_SCENES = 3
MAX_SCENES = 6
HOT_NHI = 0.1
HOT_B12_REFLECTANCE = 0.15
HOT_MIN_PIXELS = 2  # one marginal pixel is not enough ...
HOT_STRONG_NHI = 0.25  # ... unless it is strongly hot
PERSISTENT_MIN_SPAN_DAYS = 4
BURN_DNBR = 0.1
BURN_DNBR_DARKEST = 0.2
MIN_CLEAR_LAND = 0.4
MIN_LAND_FOR_PERCENTILE = 0.8
MAX_CLOUD_FOR_CLEAR = 0.5
OPEN_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")

METHOD = (
    "Sentinel-2 L2A scenes from 30 days before to 20 days after the detection are measured over a ~780 m box. "
    "Hot pixel: NHI_SWIR = (B12 - B11) / (B12 + B11) above 0.1 with B12 reflectance above 0.15; a scene shows heat with at least "
    "2 hot pixels (or one above 0.25), and heat on dates at least 4 days apart marks a persistent source. Burn scar: the normalized "
    "burn ratio (B8A - B12) / (B8A + B12) over clear land falls by 0.1 or more on average, or by 0.2 or more in its darkest 5 %, "
    "between the last clear scene before and the first clear scene after the detection. Cloud and shadow come from the scene "
    "classification layer."
)
REFERENCES = [
    "Marchese F. et al. (2019) Remote Sensing 11, 2876 - Normalized Hotspot Indices for Sentinel-2 MSI",
    "Key C.H. & Benson N.C. (2006) USDA Forest Service RMRS-GTR-164-CD - Normalized Burn Ratio and burn severity",
]


def radiometric_offset(properties: Dict[str, Any]) -> int:
    """Sentinel-2 L2A digital numbers carry a +1000 offset from processing baseline 04.00 (January 2022)."""
    try:
        return 1000 if float(properties.get("s2:processing_baseline") or "99") >= 4.0 else 0
    except (TypeError, ValueError):
        return 1000


def scene_expressions(offset: int) -> List[str]:
    """Per-pixel band maths: land share, cloud share, hot pixels, NHI, NBR over land (mean and low percentile)."""
    land = "((SCL==4)|(SCL==5))"
    cloud = "((SCL==3)|(SCL==8)|(SCL==9)|(SCL==10))"
    nhi = f"((B12-B11)/(B12+B11-{2 * offset}+1))"
    nbr = f"((B8A-B12)/(B8A+B12-{2 * offset}+1))"
    return [
        f"where({land},1,0)",
        f"where({cloud},1,0)",
        f"where(({nhi}>{HOT_NHI})&(B12>{int(HOT_B12_REFLECTANCE * 10000) + offset}),1,0)",
        nhi,
        f"where({land},{nbr},0)",
        f"where({land},{nbr},1)",  # non-land pixels sit at the top, so the 5th percentile describes the darkest land
    ]


def scene_metrics(statistics: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Turn the statistics of the six expressions into scene measurements (None when the box has no data)."""
    if len(statistics) < 6:
        return None
    land, cloud, hot, nhi, nbr, nbr_low = statistics[:6]
    count = float(land.get("count") or 0.0)
    land_fraction = float(land.get("mean", float("nan")))
    if count <= 0 or math.isnan(land_fraction):
        return None
    return {
        "valid_pixels": int(count),
        "land_fraction": round(land_fraction, 3),
        "cloud_fraction": round(float(cloud["mean"]), 3),
        "hot_pixels": int(round(float(hot["mean"]) * float(hot.get("count") or count))),
        "max_nhi_swir": round(float(nhi["max"]), 3),
        "nbr_land": round(float(nbr["mean"]) / land_fraction, 3) if land_fraction >= 0.05 else None,
        "nbr_land_p5": round(float(nbr_low["percentile_5"]), 3) if land_fraction >= MIN_LAND_FOR_PERCENTILE and "percentile_5" in nbr_low else None,
    }


def shows_heat(scene: Dict[str, Any]) -> bool:
    return scene["hot_pixels"] >= HOT_MIN_PIXELS or (scene["hot_pixels"] >= 1 and scene["max_nhi_swir"] >= HOT_STRONG_NHI)


def interpret(scenes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Combine scene measurements into heat and burn-scar findings and a verdict."""
    if not scenes:
        return {"status": "none_found", "supports": None, "hotspot": {"detected": None}, "burn_scar": {"detected": None},
                "headline": "No usable Sentinel-2 scene between 30 days before and 20 days after the detection."}

    hot_scenes = sorted((s for s in scenes if shows_heat(s)), key=lambda s: s["days_from_detection"])
    near = [s for s in scenes if abs(s["days_from_detection"]) <= HOTSPOT_WINDOW_DAYS]
    hot_near = [s for s in near if shows_heat(s)]
    clear_near = [s for s in near if s["cloud_fraction"] < MAX_CLOUD_FOR_CLEAR]
    heat_days = [s["days_from_detection"] for s in hot_scenes]
    persistent = len(heat_days) >= 2 and heat_days[-1] - heat_days[0] >= PERSISTENT_MIN_SPAN_DAYS
    if hot_near:
        best = max(hot_near, key=lambda s: (s["hot_pixels"], -abs(s["days_from_detection"])))
        hotspot = {"detected": True, "scene_id": best["id"], "date": best["date"], "hot_pixels": best["hot_pixels"],
                   "max_nhi_swir": best["max_nhi_swir"], "scenes_checked": len(near)}
    elif clear_near:
        hotspot = {"detected": False, "scenes_checked": len(near), "clear_scenes": len(clear_near)}
    else:
        hotspot = {"detected": None, "scenes_checked": len(near), "reason": "cloud or no scene within 12 days of the detection"}
    hotspot.update({"dates_with_heat": [s["date"] for s in hot_scenes], "persistent": persistent})

    usable = [s for s in scenes if s["land_fraction"] >= MIN_CLEAR_LAND and s["nbr_land"] is not None]
    before = [s for s in usable if s["days_from_detection"] < 0]
    after = [s for s in usable if s["days_from_detection"] > 0]
    if before and after:
        pre = max(before, key=lambda s: s["days_from_detection"])
        post = min(after, key=lambda s: s["days_from_detection"])
        dnbr = round(pre["nbr_land"] - post["nbr_land"], 3)
        darkest = None
        if pre.get("nbr_land_p5") is not None and post.get("nbr_land_p5") is not None:
            darkest = round(pre["nbr_land_p5"] - post["nbr_land_p5"], 3)
        burn = {"detected": dnbr >= BURN_DNBR or (darkest is not None and darkest >= BURN_DNBR_DARKEST), "dnbr": dnbr,
                "dnbr_darkest_5pct": darkest, "before_scene_id": pre["id"], "before_date": pre["date"],
                "after_scene_id": post["id"], "after_date": post["date"]}
    else:
        burn = {"detected": None, "reason": "no clear scene both before and after the detection"}

    dates = ", ".join(hotspot["dates_with_heat"])
    if burn["detected"]:
        drop = (f"the burn ratio over clear land fell by {burn['dnbr']:.2f}" if burn["dnbr"] >= BURN_DNBR
                else f"the darkest 5% of land lost {burn['dnbr_darkest_5pct']:.2f} in burn ratio")
        if persistent:
            status, supports = "mixed", None
            headline = (f"Mixed evidence: a burn scar ({drop} between {burn['before_date']} and {burn['after_date']}) and heat on "
                        f"{len(heat_days)} dates ({dates}); vegetation burned near a persistent heat source.")
        else:
            status, supports = "supports_vegetation", "vegetation"
            headline = f"Burn scar: {drop} between {burn['before_date']} and {burn['after_date']}, so vegetation burned."
    elif persistent and (burn["detected"] is False or len(heat_days) >= 3):
        status, supports = "supports_industrial", "industrial"
        headline = (f"Heat on {len(heat_days)} Sentinel-2 dates ({dates}) at the same place" + (" with no burn scar" if burn["detected"] is False else "")
                    + ": a persistent high-temperature source such as a flare, furnace or coal fire.")
    elif hot_scenes:
        status, supports = "heat_confirmed", None
        strongest = max(hot_scenes, key=lambda s: s["hot_pixels"])
        headline = (f"Sentinel-2 shows heat here ({strongest['hot_pixels']} hot pixels on {strongest['date']}"
                    + (f"; heat on {len(heat_days)} dates" if len(heat_days) > 1 else "") + "), confirming a real high-temperature source; "
                    + ("no burn scar." if burn["detected"] is False else "no clear before-and-after pair to test for a burn scar."))
    elif hotspot["detected"] is False or burn["detected"] is False:
        status, supports = "no_evidence", None
        headline = "No heat or burn scar in the clear Sentinel-2 scenes: the source may be small, brief or active only at night."
    else:
        status, supports = "inconclusive", None
        headline = "Inconclusive: cloud or missing Sentinel-2 scenes around the detection."
    return {"status": status, "supports": supports, "headline": headline, "hotspot": hotspot, "burn_scar": burn}


def chip_urls(scene_id: str, lat: float, lon: float) -> Dict[str, str]:
    half = 0.02  # ~4 x 4 km
    bbox = f"{lon - half:.5f},{lat - half:.5f},{lon + half:.5f},{lat + half:.5f}"
    base = f"{settings.PLANETARY_COMPUTER_DATA_API}/item/bbox/{bbox}/512x512.png?collection={COLLECTION}&item={scene_id}"
    return {
        "true_colour": f"{base}&assets=visual&asset_bidx=visual%7C1,2,3&nodata=0",
        "swir": f"{base}&assets=B12&assets=B8A&assets=B04&rescale=0,5000&nodata=0",
    }


def _footprint(lat: float, lon: float) -> Dict[str, Any]:
    half_lat = FOOTPRINT_HALF_DEG
    half_lon = FOOTPRINT_HALF_DEG / max(math.cos(math.radians(lat)), 0.2)
    ring = [[lon - half_lon, lat - half_lat], [lon + half_lon, lat - half_lat], [lon + half_lon, lat + half_lat],
            [lon - half_lon, lat + half_lat], [lon - half_lon, lat - half_lat]]
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}


async def _search(client: httpx.AsyncClient, lat: float, lon: float, acquired: datetime) -> List[Dict[str, Any]]:
    start = (acquired - timedelta(days=SEARCH_DAYS_BEFORE)).strftime("%Y-%m-%dT00:00:00Z")
    end = (acquired + timedelta(days=SEARCH_DAYS_AFTER)).strftime("%Y-%m-%dT23:59:59Z")
    body = {"collections": [COLLECTION], "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "datetime": f"{start}/{end}", "query": {"eo:cloud_cover": {"lt": 95}}, "limit": 100}
    response = await client.post(f"{settings.PLANETARY_COMPUTER_STAC_API}/search", json=body)
    response.raise_for_status()
    scenes: Dict[str, Dict[str, Any]] = {}
    for feature in response.json().get("features", []):
        props = feature["properties"]
        taken = datetime.fromisoformat(props["datetime"].replace("Z", "+00:00"))
        scene = {
            "id": feature["id"],
            "datetime": props["datetime"],
            "date": taken.strftime("%Y-%m-%d"),
            "days_from_detection": round((taken - acquired).total_seconds() / 86400.0, 1),
            "platform": props.get("platform"),
            "scene_cloud_cover_pct": props.get("eo:cloud_cover"),
            "offset": radiometric_offset(props),
        }
        key = f"{scene['date']}|{scene['platform']}"  # overlapping tiles of the same pass: keep the clearer one
        if key not in scenes or (scene["scene_cloud_cover_pct"] or 100) < (scenes[key]["scene_cloud_cover_pct"] or 100):
            scenes[key] = scene
    return sorted(scenes.values(), key=lambda s: abs(s["days_from_detection"]))


async def _measure(client: httpx.AsyncClient, scene: Dict[str, Any], lat: float, lon: float) -> Optional[Dict[str, Any]]:
    params = {"collection": COLLECTION, "item": scene["id"], "expression": ";".join(scene_expressions(scene["offset"])),
              "asset_as_band": "true", "p": "5"}
    for attempt in range(2):
        response = await client.post(f"{settings.PLANETARY_COMPUTER_DATA_API}/item/statistics", params=params, json=_footprint(lat, lon))
        if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
            await asyncio.sleep(2.0)
            continue
        if response.status_code != 200:
            return None
        return scene_metrics(list(response.json()["properties"]["statistics"].values()))
    return None


def _enough(scenes: Sequence[Dict[str, Any]]) -> bool:
    if len(scenes) < MIN_SCENES:
        return False
    clear_near = any(abs(s["days_from_detection"]) <= HOTSPOT_WINDOW_DAYS and s["cloud_fraction"] < MAX_CLOUD_FOR_CLEAR for s in scenes)
    before = any(s["days_from_detection"] < 0 and s["land_fraction"] >= MIN_CLEAR_LAND for s in scenes)
    after = any(s["days_from_detection"] > 0 and s["land_fraction"] >= MIN_CLEAR_LAND for s in scenes)
    return clear_near and before and after


async def assess(lat: float, lon: float, acquired: datetime) -> Dict[str, Any]:
    """Measure the Sentinel-2 scenes around a detection and interpret them."""
    base = {"collection": COLLECTION, "footprint_m": FOOTPRINT_M, "method": METHOD, "references": REFERENCES, "checked_at": utcnow_iso()}
    if settings.OFFLINE:
        return {**base, "status": "unavailable", "supports": None, "headline": "Imagery check skipped: offline mode.", "scenes": []}
    evaluated: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=45.0, headers={"User-Agent": settings.HTTP_USER_AGENT}) as client:
            for scene in await _search(client, lat, lon, acquired):
                if len(evaluated) >= MAX_SCENES or _enough(evaluated):
                    break
                metrics = await _measure(client, scene, lat, lon)
                if metrics is not None:
                    evaluated.append({**{k: v for k, v in scene.items() if k != "offset"}, **metrics})
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {**base, "status": "error", "supports": None, "scenes": [],
                "headline": f"Imagery check failed ({type(exc).__name__} from the Planetary Computer API); try again later."}
    result = interpret(evaluated)
    focus = result["hotspot"].get("scene_id") or (min(evaluated, key=lambda s: abs(s["days_from_detection"]))["id"] if evaluated else None)
    if focus:
        result["chips"] = {"scene_id": focus, **chip_urls(focus, lat, lon)}
    return {**base, **result, "scenes": evaluated}


# ---------------------------------------------------------------- stored evidence

def cached_evidence(detection_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = list(dict.fromkeys(detection_ids))
    out: Dict[str, Dict[str, Any]] = {}
    with SessionLocal() as db:
        for start in range(0, len(ids), 500):
            for row in db.query(ImageryEvidenceModel).filter(ImageryEvidenceModel.detection_id.in_(ids[start:start + 500])).all():
                out[row.detection_id] = row.to_dict()
    return out


def store_evidence(detection_id: str, result: Dict[str, Any]) -> None:
    if result.get("status") in ("unavailable", "error"):
        return  # not a finding; try again later
    with SessionLocal() as db:
        db.merge(ImageryEvidenceModel(
            detection_id=detection_id, status=result["status"], supports=result.get("supports"), headline=result["headline"],
            evidence_json=json.dumps(result), checked_at=result["checked_at"],
        ))
        db.commit()


async def evidence_for_detection(detection_id: str, refresh: bool = False) -> Optional[Dict[str, Any]]:
    """Stored evidence for a detection, measuring it first when there is none (or refresh is requested)."""
    if not refresh:
        cached = cached_evidence([detection_id]).get(detection_id)
        if cached:
            return cached
    with SessionLocal() as db:
        row = db.query(DetectionModel).filter(DetectionModel.detection_id == detection_id).first()
        if row is None:
            return None
        lat, lon, when = row.latitude, row.longitude, row.acq_datetime
    acquired = datetime.fromisoformat(when[:16] + ":00+00:00")
    result = await assess(lat, lon, acquired)
    result["detection_id"] = detection_id
    store_evidence(detection_id, result)
    return result


async def verify_open_incidents(deadline_s: float = 180.0) -> Dict[str, int]:
    """Check open, real (non-drill) incidents without imagery evidence and note the finding in their history."""
    summary = {"checked": 0, "already_checked": 0, "not_available": 0}
    if settings.OFFLINE:
        return summary
    with SessionLocal() as db:
        targets = [(row.id, row.detection_id) for row in db.query(IncidentModel).filter(
            IncidentModel.status.in_(OPEN_INCIDENT_STATUSES), IncidentModel.is_drill.is_(False)).all()]
    cached = cached_evidence(detection_id for _, detection_id in targets)
    loop = asyncio.get_running_loop()
    started = loop.time()
    for incident_id, detection_id in targets:
        if detection_id in cached:
            summary["already_checked"] += 1
            continue
        if loop.time() - started > deadline_s:
            break
        result = await evidence_for_detection(detection_id, refresh=True)
        if not result or result["status"] in ("unavailable", "error"):
            summary["not_available"] += 1
            continue
        with SessionLocal() as db:
            row = db.get(IncidentModel, incident_id)
            if row is not None:
                history = json.loads(row.history_json or "[]")
                history.append({"at": utcnow_iso(), "by": "system", "status": row.status, "note": f"Sentinel-2 check: {result['headline']}"})
                row.history_json = json.dumps(history)
                db.commit()
        summary["checked"] += 1
    return summary

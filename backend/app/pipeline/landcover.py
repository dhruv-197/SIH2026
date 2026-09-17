"""ESA WorldCover 10 m (2021, v200) land-cover fractions inside a satellite pixel footprint.

Values come from the Microsoft Planetary Computer data API (item statistics over a
~375 m box centred on a 0.003 degree grid cell). Results are cached in SQLite, so the
system keeps working offline for every cell fetched before. A cell that was never fetched
is reported as unavailable - the classifier receives missing values instead of a guess.

Reference: Zanaga, D. et al. (2022). ESA WorldCover 10 m 2021 v200. doi:10.5281/zenodo.7254221
"""
import asyncio
import json
import math
from typing import Dict, Iterable, List, Optional, Tuple

import httpx

from ..config import settings

CELL_DEG = 0.003
FOOTPRINT_HALF_DEG = 0.0017  # ~375 m box, the VIIRS I-band pixel size at nadir

WORLDCOVER_CLASSES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

FRACTION_GROUPS = {
    "tree": (10,),
    "shrub_grass": (20, 30),
    "crop": (40,),
    "built": (50,),
    "bare": (60,),
    "water_wetland": (80, 90, 95),
    "other": (70, 100),
}

LANDCOVER_FEATURES = ["lc_tree", "lc_shrub_grass", "lc_crop", "lc_built", "lc_bare", "lc_water_wetland", "lc_available"]


def cell_key(lat: float, lon: float) -> str:
    return f"{math.floor(lat / CELL_DEG)}:{math.floor(lon / CELL_DEG)}"


def cell_center(key: str) -> Tuple[float, float]:
    i, j = (int(part) for part in key.split(":"))
    return round((i + 0.5) * CELL_DEG, 5), round((j + 0.5) * CELL_DEG, 5)


def worldcover_item_id(lat: float, lon: float) -> str:
    lat3 = math.floor(lat / 3) * 3
    lon3 = math.floor(lon / 3) * 3
    ns = "N" if lat3 >= 0 else "S"
    ew = "E" if lon3 >= 0 else "W"
    return f"ESA_WorldCover_10m_2021_v200_{ns}{abs(lat3):02d}{ew}{abs(lon3):03d}"


def fractions_from_histogram(counts: List[float], values: List[float]) -> Tuple[Dict[str, float], Optional[int]]:
    total = float(sum(counts))
    if total <= 0:
        return {}, None
    by_code = {int(v): float(c) for c, v in zip(counts, values)}
    fractions = {group: round(sum(by_code.get(code, 0.0) for code in codes) / total, 4) for group, codes in FRACTION_GROUPS.items()}
    dominant = max(by_code.items(), key=lambda kv: kv[1])[0]
    return fractions, dominant


def feature_values(entry: Optional[Dict]) -> Dict[str, float]:
    """Model features for a cache entry; NaN when land cover is unavailable."""
    if not entry or entry.get("status") != "ok":
        values = {name: float("nan") for name in LANDCOVER_FEATURES}
        values["lc_available"] = 0.0
        return values
    fractions = entry.get("fractions", {})
    values = {f"lc_{group}": float(fractions.get(group, 0.0)) for group in ("tree", "shrub_grass", "crop", "built", "bare", "water_wetland")}
    values["lc_available"] = 1.0
    return values


def describe(entry: Optional[Dict]) -> Dict:
    if not entry:
        return {"available": False, "reason": "not fetched yet"}
    if entry.get("status") != "ok":
        return {"available": False, "reason": "no WorldCover pixels in footprint"}
    fractions = entry.get("fractions", {})
    return {
        "available": True,
        "product": "ESA WorldCover 10 m 2021 v200",
        "footprint_m": 375,
        "dominant_class": WORLDCOVER_CLASSES.get(entry.get("dominant_code")),
        "fractions": fractions,
        "item_id": entry.get("item_id"),
        "fetched_at": entry.get("fetched_at"),
    }


class LandCoverStore:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._cells: Dict[str, Dict] = {}

    def load(self) -> int:
        from ..db.models import LandCoverCacheModel

        with self._session_factory() as db:
            self._cells = {row.cell_key: row.to_dict() for row in db.query(LandCoverCacheModel).all()}
        return len(self._cells)

    def entry(self, lat: float, lon: float) -> Optional[Dict]:
        return self._cells.get(cell_key(lat, lon))

    def features(self, lat: float, lon: float) -> Dict[str, float]:
        return feature_values(self.entry(lat, lon))

    def coverage(self) -> Dict[str, int]:
        ok = sum(1 for e in self._cells.values() if e["status"] == "ok")
        return {"cells_cached": len(self._cells), "cells_with_data": ok}

    def missing_cells(self, coords: Iterable[Tuple[float, float]]) -> List[str]:
        keys = {cell_key(lat, lon) for lat, lon in coords}
        return sorted(k for k in keys if k not in self._cells)

    async def fetch_cells(self, keys: List[str], concurrency: int = 8, deadline_s: Optional[float] = None) -> Dict[str, int]:
        """Fetch WorldCover statistics for the given cells and persist them. Never raises."""
        summary = {"requested": len(keys), "fetched": 0, "nodata": 0, "failed": 0, "skipped_offline": 0}
        if not keys:
            return summary
        if settings.OFFLINE:
            summary["skipped_offline"] = len(keys)
            return summary

        loop = asyncio.get_running_loop()
        started = loop.time()
        semaphore = asyncio.Semaphore(concurrency)
        results: List[Dict] = []

        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": settings.HTTP_USER_AGENT}) as client:
            async def worker(key: str):
                async with semaphore:
                    if deadline_s is not None and loop.time() - started > deadline_s:
                        summary["failed"] += 1
                        return
                    entry = await self._fetch_one(client, key)
                    if entry is None:
                        summary["failed"] += 1
                    else:
                        summary["fetched" if entry["status"] == "ok" else "nodata"] += 1
                        results.append(entry)

            await asyncio.gather(*(worker(key) for key in keys))

        self._persist(results)
        return summary

    async def _fetch_one(self, client: httpx.AsyncClient, key: str) -> Optional[Dict]:
        lat, lon = cell_center(key)
        item_id = worldcover_item_id(lat, lon)
        half_lat = FOOTPRINT_HALF_DEG
        half_lon = FOOTPRINT_HALF_DEG / max(math.cos(math.radians(lat)), 0.2)
        footprint = {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [lon - half_lon, lat - half_lat], [lon + half_lon, lat - half_lat],
                    [lon + half_lon, lat + half_lat], [lon - half_lon, lat + half_lat],
                    [lon - half_lon, lat - half_lat],
                ]],
            },
        }
        params = {"collection": "esa-worldcover", "item": item_id, "assets": "map", "categorical": "true"}
        for attempt in range(3):
            try:
                response = await client.post(f"{settings.PLANETARY_COMPUTER_DATA_API}/item/statistics", params=params, json=footprint)
                if response.status_code == 404:
                    return {"cell_key": key, "latitude": lat, "longitude": lon, "status": "nodata", "item_id": item_id, "dominant_code": None, "fractions": {}}
                if response.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                response.raise_for_status()
                stats = response.json()["properties"]["statistics"]
                band = next(iter(stats.values()))
                counts, values = band["histogram"]
                fractions, dominant = fractions_from_histogram(counts, values)
                status = "ok" if fractions else "nodata"
                return {"cell_key": key, "latitude": lat, "longitude": lon, "status": status, "item_id": item_id, "dominant_code": dominant, "fractions": fractions}
            except (httpx.HTTPError, KeyError, ValueError, StopIteration, TypeError):
                await asyncio.sleep(1.5 * (attempt + 1))
        return None

    def _persist(self, entries: List[Dict]) -> None:
        if not entries:
            return
        from ..db.models import LandCoverCacheModel, utcnow_iso

        with self._session_factory() as db:
            for entry in entries:
                entry["fetched_at"] = utcnow_iso()
                db.merge(LandCoverCacheModel(
                    cell_key=entry["cell_key"],
                    latitude=entry["latitude"],
                    longitude=entry["longitude"],
                    status=entry["status"],
                    item_id=entry["item_id"],
                    dominant_code=entry["dominant_code"],
                    fractions_json=json.dumps(entry["fractions"]),
                    fetched_at=entry["fetched_at"],
                ))
                self._cells[entry["cell_key"]] = entry
            db.commit()

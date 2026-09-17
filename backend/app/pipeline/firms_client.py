"""NASA FIRMS data access.

Three ways in, all producing raw FIRMS CSV rows:
1. Public near-real-time text files (no key): last 24h / 48h / 7d for the South Asia region,
   for VIIRS on Suomi NPP, NOAA-20, NOAA-21 and MODIS on Terra/Aqua.
2. FIRMS area API with a MAP_KEY: any 1-10 day range, optionally ending on a past date.
3. The bundled snapshot in app/data/firms_snapshot (offline demo and tests).
"""
import glob
import os
from typing import Dict, List, Optional, Tuple

import httpx

from ..config import settings
from .normalize import parse_csv_text

PUBLIC_FEEDS = {
    "VIIRS_NOAA20": "noaa-20-viirs-c2/csv/J1_VIIRS_C2_{region}_{window}.csv",
    "VIIRS_NOAA21": "noaa-21-viirs-c2/csv/J2_VIIRS_C2_{region}_{window}.csv",
    "VIIRS_SNPP": "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_{region}_{window}.csv",
    "MODIS": "modis-c6.1/csv/MODIS_C6_1_{region}_{window}.csv",
}
API_SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"]
PUBLIC_WINDOWS = ("24h", "48h", "7d")


class FirmsError(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    return {"User-Agent": settings.HTTP_USER_AGENT}


async def fetch_public_feed(window: str = "24h") -> Tuple[List[Dict], Dict[str, str]]:
    if window not in PUBLIC_WINDOWS:
        raise FirmsError(f"window must be one of {PUBLIC_WINDOWS}")
    if settings.OFFLINE:
        raise FirmsError("Offline mode is enabled; outbound requests are disabled")
    rows: List[Dict] = []
    status: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=90.0, headers=_headers(), follow_redirects=True) as client:
        for feed, path in PUBLIC_FEEDS.items():
            url = f"{settings.FIRMS_PUBLIC_BASE}/{path.format(region=settings.FIRMS_REGION, window=window)}"
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    status[feed] = f"HTTP {response.status_code}"
                    continue
                feed_rows = parse_csv_text(response.text)
                rows.extend(feed_rows)
                status[feed] = f"{len(feed_rows)} rows"
            except httpx.HTTPError as exc:
                status[feed] = f"error: {type(exc).__name__}"
    if not any(value.endswith("rows") for value in status.values()):
        raise FirmsError(f"No FIRMS public feed could be downloaded: {status}")
    return rows, status


async def check_map_key(map_key: str) -> Dict:
    async with httpx.AsyncClient(timeout=30.0, headers=_headers()) as client:
        response = await client.get("https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/", params={"MAP_KEY": map_key})
    if response.status_code != 200:
        raise FirmsError(f"MAP_KEY check failed (HTTP {response.status_code})")
    try:
        return response.json()
    except ValueError as exc:
        raise FirmsError("MAP_KEY is not valid") from exc


async def fetch_area_api(map_key: str, day_range: int = 1, end_date: Optional[str] = None) -> Tuple[List[Dict], Dict[str, str]]:
    if settings.OFFLINE:
        raise FirmsError("Offline mode is enabled; outbound requests are disabled")
    day_range = max(1, min(int(day_range), 10))
    west, south, east, north = settings.INDIA_BBOX
    rows: List[Dict] = []
    status: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=120.0, headers=_headers()) as client:
        for source in API_SOURCES:
            url = f"{settings.FIRMS_API_BASE}/area/csv/{map_key}/{source}/{west},{south},{east},{north}/{day_range}"
            if end_date:
                url += f"/{end_date}"
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                status[source] = f"error: {type(exc).__name__}"
                continue
            text = response.text.strip()
            if response.status_code != 200 or text.lower().startswith("invalid"):
                status[source] = f"HTTP {response.status_code}: {text[:80]}"
                if "invalid" in text.lower() and "key" in text.lower():
                    raise FirmsError("NASA FIRMS rejected the MAP_KEY")
                continue
            feed_rows = parse_csv_text(text)
            rows.extend(feed_rows)
            status[source] = f"{len(feed_rows)} rows"
    return rows, status


def load_snapshot(directory: Optional[str] = None) -> Tuple[List[Dict], Dict[str, str]]:
    directory = directory or settings.FIRMS_SNAPSHOT_DIR
    rows: List[Dict] = []
    status: Dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.csv"))):
        with open(path, encoding="utf-8") as f:
            file_rows = parse_csv_text(f.read())
        rows.extend(file_rows)
        status[os.path.basename(path)] = f"{len(file_rows)} rows"
    return rows, status

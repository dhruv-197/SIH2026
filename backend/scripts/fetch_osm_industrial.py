"""
Fetch thermally relevant industrial and extractive features for India from
OpenStreetMap via the Overpass API.

Output: backend/app/data/osm_industrial_india.geojson

Every feature keeps its real OSM element id (e.g. "way/123456"), so any entry can be
checked at https://www.openstreetmap.org/<osm_id>.
Data (c) OpenStreetMap contributors, available under the ODbL 1.0.

Usage:
    py backend/scripts/fetch_osm_industrial.py
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping
from shapely.ops import polygonize, unary_union

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "data", "osm_industrial_india.geojson")

ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
HEADERS = {"User-Agent": "GeoThermalSentinel/2.0 (SIH 2026 prototype; OSM industrial context extract)"}
AREA = 'area["ISO3166-1"="IN"][admin_level=2]->.in;'

QUERIES = {
    "oil_gas": """
        nwr["industrial"~"^(refinery|oil|gas|petrochemical|lng)$"](area.in);
        nwr["man_made"~"^(flare|petroleum_well|oil_gas_separator)$"](area.in);
        nwr["landuse"="industrial"]["name"~"refinery|petrochemical|LNG|gas processing|group gathering|oil field",i](area.in);
    """,
    "heavy_industry": """
        nwr["power"="plant"]["plant:source"~"coal|gas|oil|diesel|biomass|waste|lignite"](area.in);
        nwr["power"="plant"]["name"~"thermal|TPS|STPS|super thermal",i](area.in);
        nwr["industrial"~"steel|metallurg|smelter|foundry|cement|brickworks|aluminium|ferro"](area.in);
        nwr["man_made"="works"]["product"~"steel|iron|aluminium|cement|coke|glass",i](area.in);
        nwr["landuse"="industrial"]["name"~"steel|ispat|cement|smelter|aluminium|ferro|sponge iron|coke oven|thermal power",i](area.in);
        nwr["man_made"="kiln"](area.in);
    """,
    "mining": """
        nwr["landuse"="quarry"]["resource"~"coal|lignite"](area.in);
        nwr["industrial"="mine"](area.in);
        nwr["landuse"="quarry"]["name"~"coal|colliery|OCP|open ?cast|lignite",i](area.in);
        nwr["man_made"="mineshaft"](area.in);
    """,
}

THERMAL_FUEL = re.compile(r"coal|gas|oil|diesel|biomass|waste|lignite", re.I)


def categorize(tags):
    """Map OSM tags to (category, subtype). Returns (None, None) when not thermally relevant."""
    t = {k: str(v) for k, v in tags.items()}
    name = t.get("name:en") or t.get("name") or ""
    industrial = t.get("industrial", "").lower()
    man_made = t.get("man_made", "").lower()
    landuse = t.get("landuse", "").lower()
    product = t.get("product", "").lower()

    if t.get("power") == "plant":
        source = t.get("plant:source", "")
        if THERMAL_FUEL.search(source) or re.search(r"thermal|\bTPS\b|\bSTPS\b", name, re.I):
            return "heavy_industry", "thermal_power"
        return None, None
    if man_made == "flare":
        return "oil_gas", "gas_flare"
    if man_made == "petroleum_well":
        return "oil_gas", "oil_gas_well"
    if man_made == "oil_gas_separator":
        return "oil_gas", "gas_processing"
    if industrial in ("refinery", "oil", "petrochemical") or re.search(r"refinery|petrochemical", name, re.I):
        return "oil_gas", "refinery"
    if industrial in ("gas", "lng") or re.search(r"\bLNG\b|gas processing|group gathering", name, re.I):
        return "oil_gas", "gas_processing"
    if re.search(r"oil field", name, re.I):
        return "oil_gas", "oil_field"

    if landuse == "quarry" and re.search(r"coal|lignite", t.get("resource", "") + " " + name, re.I):
        return "mining", "coal_mine"
    if industrial == "mine" or man_made == "mineshaft":
        return "mining", "mine"
    if landuse == "quarry" and re.search(r"colliery|\bOCP\b|open ?cast", name, re.I):
        return "mining", "coal_mine"

    if re.search(r"steel|metallurg|ferro", industrial) or re.search(r"steel|iron", product) or re.search(r"steel|ispat|sponge iron|ferro", name, re.I):
        return "heavy_industry", "steel"
    if "smelter" in industrial or "aluminium" in industrial or "aluminium" in product or re.search(r"smelter|aluminium", name, re.I):
        return "heavy_industry", "smelter"
    if "cement" in industrial or "cement" in product or re.search(r"cement", name, re.I):
        return "heavy_industry", "cement"
    if industrial == "brickworks" or man_made == "kiln":
        return "heavy_industry", "kiln"
    if "foundry" in industrial or "coke" in product or re.search(r"coke oven", name, re.I):
        return "heavy_industry", "foundry_coke"
    if "glass" in product:
        return "heavy_industry", "glass"
    if re.search(r"thermal power", name, re.I):
        return "heavy_industry", "thermal_power"
    return None, None


def build_geometry(el):
    etype = el["type"]
    if etype == "node":
        return Point(el["lon"], el["lat"])
    if etype == "way":
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            poly = Polygon(coords)
            return poly if poly.is_valid else poly.buffer(0)
        if coords:
            return Point(sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords))
        return None
    if etype == "relation":
        lines = []
        for member in el.get("members", []):
            if member.get("type") == "way" and member.get("role", "outer") in ("outer", "") and member.get("geometry"):
                pts = [(p["lon"], p["lat"]) for p in member["geometry"] if p]
                if len(pts) >= 2:
                    lines.append(LineString(pts))
        if lines:
            polys = list(polygonize(lines))
            if polys:
                geom = unary_union(polys)
                return geom if geom.is_valid else geom.buffer(0)
        bounds = el.get("bounds")
        if bounds:
            return box(bounds["minlon"], bounds["minlat"], bounds["maxlon"], bounds["maxlat"])
    return None


def round_coords(obj, ndigits=5):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, (list, tuple)):
        return [round_coords(v, ndigits) for v in obj]
    if isinstance(obj, dict):
        return {k: round_coords(v, ndigits) for k, v in obj.items()}
    return obj


def run_query(name, body):
    query = f"[out:json][timeout:300][maxsize:536870912];{AREA}({body});out geom qt;"
    last_err = None
    for attempt in range(6):
        endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            print(f"[{name}] attempt {attempt + 1} via {endpoint}", flush=True)
            response = httpx.post(endpoint, data={"data": query}, headers=HEADERS, timeout=360)
            if response.status_code == 200:
                return response.json().get("elements", []), endpoint
            last_err = f"HTTP {response.status_code}"
        except Exception as exc:  # network or JSON errors
            last_err = f"{type(exc).__name__}: {exc}"
        print(f"[{name}] failed: {last_err}; backing off", flush=True)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Overpass query '{name}' failed: {last_err}")


def main():
    features, seen, used_endpoints = [], set(), set()
    for name, body in QUERIES.items():
        elements, endpoint = run_query(name, body)
        used_endpoints.add(endpoint)
        kept = 0
        for el in elements:
            osm_id = f"{el['type']}/{el['id']}"
            if osm_id in seen:
                continue
            tags = el.get("tags", {})
            category, subtype = categorize(tags)
            if not category:
                continue
            geom = build_geometry(el)
            if geom is None or geom.is_empty:
                continue
            if isinstance(geom, (Polygon, MultiPolygon)):
                geom = geom.simplify(0.0002, preserve_topology=True)
            seen.add(osm_id)
            kept += 1
            features.append({
                "type": "Feature",
                "geometry": round_coords(mapping(geom)),
                "properties": {
                    "osm_id": osm_id,
                    "name": tags.get("name:en") or tags.get("name"),
                    "category": category,
                    "subtype": subtype,
                    "operator": tags.get("operator"),
                    "tags": {k: tags[k] for k in ("industrial", "man_made", "power", "plant:source", "landuse", "resource", "product", "operator") if k in tags},
                },
            })
        print(f"[{name}] {len(elements)} elements -> {kept} thermally relevant features", flush=True)
        time.sleep(10)

    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "OpenStreetMap via Overpass API",
            "license": "ODbL 1.0 - (c) OpenStreetMap contributors",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "endpoints": sorted(used_endpoints),
            "feature_count": len(features),
        },
        "features": features,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(collection, f, separators=(",", ":"))
    counts = {}
    for feat in features:
        key = f"{feat['properties']['category']}/{feat['properties']['subtype']}"
        counts[key] = counts.get(key, 0) + 1
    print(f"[+] Saved {len(features)} features to {os.path.abspath(OUT_PATH)}")
    for key in sorted(counts):
        print(f"    {key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

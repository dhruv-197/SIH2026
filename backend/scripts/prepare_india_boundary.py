"""
Build a simplified India boundary polygon used to keep FIRMS detections inside India.

Source: Natural Earth 1:10m Admin-0 countries, India point of view
(ne_10m_admin_0_countries_ind), public domain - https://www.naturalearthdata.com/
The India point-of-view edition follows the boundary depiction used by the Survey of India.

Usage:
    py backend/scripts/prepare_india_boundary.py [path/to/ne_10m_admin_0_countries_ind.geojson]
"""
import json
import os
import sys

import httpx
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries_ind.geojson"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "data", "india_boundary.geojson")


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    else:
        print(f"Downloading {NE_URL} ...")
        data = httpx.get(NE_URL, timeout=300, follow_redirects=True).json()
    parts = [shape(f["geometry"]) for f in data["features"] if f["properties"].get("ADM0_A3") == "IND"]
    if not parts:
        raise SystemExit("India feature not found in Natural Earth file")
    india = unary_union(parts).simplify(0.01, preserve_topology=True)
    # A small buffer keeps coastal refineries, ports and offshore-adjacent flares inside the mask.
    india = india.buffer(0.05).simplify(0.01, preserve_topology=True)
    out = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "Natural Earth 1:10m admin-0 countries, India point of view (public domain)",
            "processing": "union, simplify 0.01 deg, 0.05 deg coastal buffer",
        },
        "features": [{"type": "Feature", "properties": {"name": "India"},
                      "geometry": json.loads(json.dumps(mapping(india)), parse_float=lambda x: round(float(x), 4))}],
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"[+] Saved India boundary ({os.path.getsize(OUT_PATH) // 1024} KB) to {os.path.abspath(OUT_PATH)}")


if __name__ == "__main__":
    main()

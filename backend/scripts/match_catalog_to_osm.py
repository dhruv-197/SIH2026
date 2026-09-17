"""Match catalog facilities to real OpenStreetMap geometry.

For each facility the script looks for OSM features of the expected category within 8 km of the
approximate catalog coordinate and scores them by distance, geometry type, subtype and name overlap.
Matches are written back to app/data/facility_catalog.json with the real OSM element id; facilities
without a convincing match keep their catalog point and are marked unmatched.

Usage:
    py backend/scripts/match_catalog_to_osm.py
"""
import json
import os
import re
import sys

from shapely.geometry import Point, mapping
from shapely.ops import nearest_points

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.config import settings  # noqa: E402
from app.pipeline.geo_context import haversine_km, load_osm_features  # noqa: E402

EXPECTED = {
    "oil_refinery": ({"oil_gas"}, {"refinery", "gas_flare"}),
    "petrochemical": ({"oil_gas", "heavy_industry"}, {"refinery", "gas_processing"}),
    "lng_terminal": ({"oil_gas"}, {"gas_processing", "refinery"}),
    "chemical_plant": ({"oil_gas", "heavy_industry"}, set()),
    "steel_plant": ({"heavy_industry"}, {"steel"}),
    "thermal_power": ({"heavy_industry"}, {"thermal_power"}),
    "cement_kiln": ({"heavy_industry"}, {"cement"}),
    "coal_mining": ({"mining"}, {"coal_mine", "mine"}),
}
GENERIC = {"refinery", "plant", "steel", "works", "complex", "power", "thermal", "super", "limited", "ltd", "india", "coal",
           "mine", "mines", "basin", "open", "cast", "field", "coalfield", "terminal", "hub", "regasification", "petrochemical",
           "petrochemicals", "chemical", "industrial", "estate", "project", "station", "ultra", "mega", "integrated", "seam", "fires", "spoil"}
SEARCH_KM = 8.0


def tokens(text):
    return set(re.findall(r"[a-z]{4,}", (text or "").lower())) - GENERIC


def main():
    with open(settings.FACILITY_CATALOG_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    features = load_osm_features(settings.OSM_FEATURES_PATH)
    if not features:
        raise SystemExit("OSM extract missing - run scripts/fetch_osm_industrial.py first")

    matched = 0
    for fac in catalog["facilities"]:
        categories, subtypes = EXPECTED.get(fac["facility_type"], ({"heavy_industry"}, set()))
        lat, lon = fac["latitude"], fac["longitude"]
        point = Point(lon, lat)
        fac_tokens = tokens(f"{fac['name']} {fac.get('operator', '')}")
        best = None
        for feat in features:
            if feat.category not in categories:
                continue
            centroid = feat.geometry.centroid
            if abs(centroid.y - lat) > 0.15 or abs(centroid.x - lon) > 0.15:
                continue
            if feat.geometry.geom_type in ("Polygon", "MultiPolygon") and feat.geometry.contains(point):
                distance = 0.0
            else:
                _, near = nearest_points(point, feat.geometry)
                distance = haversine_km(lat, lon, near.y, near.x)
            if distance > SEARCH_KM:
                continue
            overlap = len(fac_tokens & tokens(f"{feat.name or ''} {feat.properties.get('operator') or ''}"))
            # A feature of a different kind (e.g. a captive power station inside a steel works) only counts
            # when the names clearly agree; otherwise the catalog would inherit the wrong geometry.
            if subtypes and feat.subtype not in subtypes and overlap < 2:
                continue
            is_polygon = feat.geometry.geom_type in ("Polygon", "MultiPolygon")
            area_km2 = feat.geometry.area * 111.32 * 110.57 if is_polygon else 0.0
            score = distance - 3.0 * overlap - (1.0 if feat.subtype in subtypes else 0.0) - (0.5 if is_polygon else 0.0) - min(area_km2, 10.0) * 0.1
            if best is None or score < best[0]:
                best = (score, distance, overlap, feat)

        for key in ("osm_element_id", "osm_name", "osm_match_distance_km", "geometry", "refined_latitude", "refined_longitude", "match_method"):
            fac.pop(key, None)
        if best and (best[2] > 0 or best[1] <= 3.0):
            _, distance, overlap, feat = best
            rep = feat.geometry.representative_point() if feat.geometry.geom_type in ("Polygon", "MultiPolygon") else feat.geometry
            fac.update({
                "osm_element_id": feat.feature_id,
                "osm_name": feat.name,
                "osm_match_distance_km": round(distance, 3),
                "refined_latitude": round(rep.y, 5),
                "refined_longitude": round(rep.x, 5),
                "match_method": "name_and_proximity" if overlap else "proximity_within_3km",
            })
            if feat.geometry.geom_type in ("Polygon", "MultiPolygon"):
                fac["geometry"] = json.loads(json.dumps(mapping(feat.geometry)))
            matched += 1
            print(f"MATCH   {fac['id']:12s} {fac['name'][:42]:42s} -> {feat.feature_id:18s} {str(feat.name)[:36]:36s} {distance:5.2f} km  name_overlap={overlap}")
        else:
            fac["match_method"] = "unmatched"
            print(f"NO OSM  {fac['id']:12s} {fac['name'][:42]:42s} (nearest candidate: {best[3].feature_id + ' at ' + format(best[1], '.2f') + ' km' if best else 'none within 8 km'})")

    with open(settings.FACILITY_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
    print(f"[+] {matched}/{len(catalog['facilities'])} catalog facilities matched to OpenStreetMap geometry")


if __name__ == "__main__":
    main()

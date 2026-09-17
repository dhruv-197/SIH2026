"""Geographic context for a detection: distance to real industrial / extractive features
(OpenStreetMap plus the curated facility catalog) and the India boundary mask."""
import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from shapely.geometry import Point, box, shape
from shapely.ops import nearest_points, unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

EARTH_RADIUS_KM = 6371.0088
CONTEXT_CATEGORIES = ("oil_gas", "heavy_industry", "mining")
MAX_CONTEXT_KM = 50.0
# Brick kilns are thermally relevant (they help classify persistent heat) but are not critical
# infrastructure: with thousands of kilns among Indian croplands, cross-alerting on them would
# turn every crop fire into an alert.
NON_CRITICAL_SUBTYPES = {"kiln"}
SUBTYPE_NAMES = {
    "refinery": "refinery", "gas_flare": "gas flare", "oil_gas_well": "oil and gas well", "gas_processing": "gas processing plant",
    "oil_field": "oil field", "thermal_power": "thermal power plant", "steel": "steel works", "cement": "cement plant",
    "smelter": "smelter", "kiln": "brick kiln", "foundry_coke": "foundry or coke oven", "glass": "glass works",
    "coal_mine": "coal mine", "mine": "mine", "oil_refinery": "refinery", "petrochemical": "petrochemical complex",
    "lng_terminal": "LNG terminal", "chemical_plant": "chemical estate", "steel_plant": "steel plant",
    "cement_kiln": "cement plant", "coal_mining": "coal mining area",
}


def feature_name(feature: "ContextFeature") -> str:
    """A name for messages: the mapped name, or a description such as 'a mapped thermal power plant'."""
    return feature.name or f"a mapped {SUBTYPE_NAMES.get(feature.subtype, feature.subtype.replace('_', ' '))}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class ContextFeature:
    feature_id: str  # "way/123" for OSM, "facility:IND-REF-001" for catalog-only points
    name: Optional[str]
    category: str  # oil_gas | heavy_industry | mining
    subtype: str
    geometry: Any  # shapely geometry in lon/lat
    source: str  # osm | catalog | simulated
    properties: Dict[str, Any] = field(default_factory=dict)

    def summary(self, distance_km: float) -> Dict[str, Any]:
        is_osm = self.source == "osm"
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "category": self.category,
            "subtype": self.subtype,
            "source": self.source,
            "distance_km": round(distance_km, 3),
            "osm_url": f"https://www.openstreetmap.org/{self.feature_id}" if is_osm else None,
        }


def load_osm_features(path: str) -> List[ContextFeature]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    features = []
    for item in data.get("features", []):
        props = item.get("properties", {})
        if props.get("category") not in CONTEXT_CATEGORIES:
            continue
        geom = shape(item["geometry"])
        if geom.is_empty:
            continue
        features.append(ContextFeature(
            feature_id=props["osm_id"],
            name=props.get("name"),
            category=props["category"],
            subtype=props.get("subtype") or props["category"],
            geometry=geom,
            source="osm",
            properties={"operator": props.get("operator"), "tags": props.get("tags", {})},
        ))
    return features


def load_boundary(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return unary_union([shape(feat["geometry"]) for feat in data.get("features", [])])


class GeoContext:
    def __init__(self, features: Sequence[ContextFeature], boundary=None):
        self.features: List[ContextFeature] = list(features)
        self._geoms = [feat.geometry for feat in self.features]
        self._tree = STRtree(self._geoms) if self._geoms else None
        self._boundary = prep(boundary) if boundary is not None else None
        self.boundary_geometry = boundary
        self._cache: Dict[tuple, Dict[str, Any]] = {}
        self._by_id: Dict[str, ContextFeature] = {feat.feature_id: feat for feat in self.features}

    def feature(self, feature_id: Optional[str]) -> Optional[ContextFeature]:
        """The loaded context feature (OpenStreetMap element or catalog facility) with this id."""
        return self._by_id.get(feature_id) if feature_id else None

    def in_india(self, lat: float, lon: float) -> bool:
        if self._boundary is None:
            return True
        return self._boundary.contains(Point(lon, lat))

    def candidates(self, lat: float, lon: float, radius_km: float) -> Iterable[int]:
        if self._tree is None:
            return []
        dlat = radius_km / 110.57
        dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.2))
        return self._tree.query(box(lon - dlon, lat - dlat, lon + dlon, lat + dlat))

    def lookup(self, lat: float, lon: float) -> Dict[str, Any]:
        """Distances (km, capped at 50) to the nearest feature of each category."""
        key = (round(lat, 4), round(lon, 4))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        point = Point(lon, lat)
        result: Dict[str, Any] = {f"dist_{c}_km": MAX_CONTEXT_KM for c in CONTEXT_CATEGORIES}
        nearest_by_category: Dict[str, Dict[str, Any]] = {}
        inside: Optional[ContextFeature] = None
        best = None
        critical = None

        for idx in self.candidates(lat, lon, MAX_CONTEXT_KM):
            feat = self.features[int(idx)]
            geom = self._geoms[int(idx)]
            if geom.geom_type in ("Polygon", "MultiPolygon") and geom.contains(point):
                distance = 0.0
                if inside is None:
                    inside = feat
            else:
                _, nearest = nearest_points(point, geom)
                distance = haversine_km(lat, lon, nearest.y, nearest.x)
            if distance > MAX_CONTEXT_KM:
                continue
            dist_key = f"dist_{feat.category}_km"
            if distance < result[dist_key]:
                result[dist_key] = distance
                nearest_by_category[feat.category] = feat.summary(distance)
            if best is None or distance < best[0]:
                best = (distance, feat)
            if feat.subtype not in NON_CRITICAL_SUBTYPES and (critical is None or distance < critical[0]):
                critical = (distance, feat)

        result["dist_industrial_km"] = min(result[f"dist_{c}_km"] for c in CONTEXT_CATEGORIES)
        result["dist_critical_infrastructure_km"] = critical[0] if critical else MAX_CONTEXT_KM
        result["nearest_critical_infrastructure"] = critical[1].summary(critical[0]) if critical else None
        result["inside_industrial"] = inside is not None
        result["inside_feature"] = inside.summary(0.0) if inside is not None else None
        result["nearest"] = best[1].summary(best[0]) if best else None
        result["nearest_by_category"] = nearest_by_category
        self._cache[key] = result
        return result

    def features_in_bbox(self, west: float, south: float, east: float, north: float) -> List[ContextFeature]:
        if self._tree is None:
            return []
        return [self.features[int(idx)] for idx in self._tree.query(box(west, south, east, north))]

    def features_near(self, lat: float, lon: float, radius_km: float) -> List[Dict[str, Any]]:
        point = Point(lon, lat)
        out = []
        for idx in self.candidates(lat, lon, radius_km):
            feat = self.features[int(idx)]
            geom = self._geoms[int(idx)]
            if geom.geom_type in ("Polygon", "MultiPolygon") and geom.contains(point):
                distance = 0.0
            else:
                _, nearest = nearest_points(point, geom)
                distance = haversine_km(lat, lon, nearest.y, nearest.x)
            if distance <= radius_km:
                out.append(feat.summary(distance))
        return sorted(out, key=lambda item: item["distance_km"])

"""GIS layer store: analysis results written as an OGC GeoPackage.

GeoPackage (OGC 12-128r18, version 1.4) is the standard SQLite container for vector GIS data and opens
directly in QGIS, ArcGIS Pro and GDAL. After every analysis the service rewrites data/gis/
geothermal_sentinel.gpkg, and /api/gis/geopackage returns a fresh copy. All layers use WGS 84 (EPSG:4326):

- detections              NASA FIRMS pixels with classification, severity and place
- persistent_sources      locations with detections on two or more days
- incidents               alerts with their triage status
- facility_locations      catalog facilities with their monitoring status
- facility_boundaries     catalog facilities matched to an OpenStreetMap outline
- osm_industrial_areas    OpenStreetMap refineries, plants, mines and kiln yards (polygons)
- osm_industrial_points   OpenStreetMap flares, wells and kilns mapped as points
- india_boundary          the analysis mask

Only the standard library and Shapely are used (no GDAL): the gpkg_spatial_ref_sys, gpkg_contents and
gpkg_geometry_columns tables, plus StandardGeoPackageBinary geometry blobs (a header with an XY envelope,
followed by little-endian WKB).
"""
import os
import sqlite3
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from shapely import from_wkb, to_wkb
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

GPKG_APPLICATION_ID = 0x47504B47  # "GPKG"
GPKG_USER_VERSION = 10400  # GeoPackage 1.4.0
WGS84 = 4326
OPEN_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")

_WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]]'
)
_SRS_ROWS = [
    ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
    ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
    ("WGS 84 geodetic", WGS84, "EPSG", 4326, _WGS84_WKT, "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid"),
]
_METADATA_DDL = """
CREATE TABLE gpkg_spatial_ref_sys (
    srs_name TEXT NOT NULL,
    srs_id INTEGER NOT NULL PRIMARY KEY,
    organization TEXT NOT NULL,
    organization_coordsys_id INTEGER NOT NULL,
    definition TEXT NOT NULL,
    description TEXT
);
CREATE TABLE gpkg_contents (
    table_name TEXT NOT NULL PRIMARY KEY,
    data_type TEXT NOT NULL,
    identifier TEXT UNIQUE,
    description TEXT DEFAULT '',
    last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,
    srs_id INTEGER,
    CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
);
CREATE TABLE gpkg_geometry_columns (
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    geometry_type_name TEXT NOT NULL,
    srs_id INTEGER NOT NULL,
    z TINYINT NOT NULL,
    m TINYINT NOT NULL,
    CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
    CONSTRAINT uk_gc_table_name UNIQUE (table_name),
    CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
    CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
);
"""


@dataclass
class Layer:
    name: str
    title: str
    description: str
    geometry_type: str  # POINT or MULTIPOLYGON
    fields: List[Tuple[str, str]]  # (column, TEXT | REAL | INTEGER | BOOLEAN)
    features: List[Tuple[Optional[BaseGeometry], Dict[str, Any]]] = field(default_factory=list)


def encode_geometry(geometry: Optional[BaseGeometry], srs_id: int = WGS84) -> Optional[bytes]:
    """StandardGeoPackageBinary: "GP", version 0, flags (little-endian, XY envelope), srs_id, envelope, WKB."""
    if geometry is None or geometry.is_empty:
        return None
    min_x, min_y, max_x, max_y = geometry.bounds
    header = b"GP" + bytes([0, 0b00000011]) + struct.pack("<i", srs_id) + struct.pack("<4d", min_x, max_x, min_y, max_y)
    return header + to_wkb(geometry, byte_order=1, output_dimension=2)


def decode_geometry(blob: bytes) -> BaseGeometry:
    envelope_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 0b111]
    return from_wkb(blob[8 + envelope_bytes:])


def _value(value: Any, sql_type: str) -> Any:
    if value is None:
        return None
    if sql_type == "BOOLEAN":
        return 1 if value else 0
    if sql_type == "INTEGER":
        return int(value)
    if sql_type == "REAL":
        number = float(value)
        return None if number != number else number
    return str(value)


def _write_layer(connection: sqlite3.Connection, layer: Layer, stamp: str) -> int:
    columns = ", ".join(f'"{name}" {sql_type}' for name, sql_type in layer.fields)
    connection.execute(f'CREATE TABLE "{layer.name}" (fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, geom {layer.geometry_type}, {columns})')
    rows, bounds = [], None
    for geometry, attributes in layer.features:
        if layer.geometry_type == "MULTIPOLYGON" and isinstance(geometry, Polygon):
            geometry = MultiPolygon([geometry])
        blob = encode_geometry(geometry)
        if blob is not None:
            b = geometry.bounds
            bounds = b if bounds is None else (min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3]))
        rows.append([blob] + [_value(attributes.get(name), sql_type) for name, sql_type in layer.fields])
    names = ", ".join(["geom"] + [f'"{name}"' for name, _ in layer.fields])
    placeholders = ", ".join("?" for _ in range(len(layer.fields) + 1))
    connection.executemany(f'INSERT INTO "{layer.name}" ({names}) VALUES ({placeholders})', rows)
    connection.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier, description, last_change, min_x, min_y, max_x, max_y, srs_id) "
        "VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?, ?)",
        (layer.name, layer.title, layer.description, stamp, *(bounds or (None, None, None, None)), WGS84),
    )
    connection.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)", (layer.name, layer.geometry_type, WGS84))
    return len(rows)


def write_geopackage(path: str, layers: Sequence[Layer]) -> Dict[str, int]:
    """Write the layers to a new GeoPackage at path, replacing any previous file. Returns feature counts."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = f"{path}.tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    connection = sqlite3.connect(tmp_path)
    try:
        connection.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {GPKG_USER_VERSION}")
        connection.executescript(_METADATA_DDL)
        connection.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)", _SRS_ROWS)
        counts = {layer.name: _write_layer(connection, layer, stamp) for layer in layers}
        connection.commit()
    finally:
        connection.close()
    os.replace(tmp_path, path)
    return counts


def layer_to_geojson(layer: Layer) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": layer.name,
        "features": [
            {"type": "Feature", "geometry": mapping(geometry) if geometry is not None else None,
             "properties": {name: attributes.get(name) for name, _ in layer.fields}}
            for geometry, attributes in layer.features
        ],
    }


def layer_summary(layers: Iterable[Layer]) -> List[Dict[str, Any]]:
    return [
        {"name": layer.name, "title": layer.title, "description": layer.description, "geometry_type": layer.geometry_type,
         "features": len(layer.features), "fields": [name for name, _ in layer.fields]}
        for layer in layers
    ]


# ---------------------------------------------------------------- layers from the analysis

DETECTION_FIELDS = [
    ("detection_id", "TEXT"), ("acq_datetime_utc", "TEXT"), ("acq_date", "TEXT"), ("satellite", "TEXT"), ("instrument", "TEXT"),
    ("daynight", "TEXT"), ("frp_mw", "REAL"), ("bright_mir_k", "REAL"), ("bright_tir_k", "REAL"), ("firms_confidence", "TEXT"),
    ("data_source", "TEXT"), ("category", "TEXT"), ("class_code", "TEXT"), ("class_label", "TEXT"), ("confidence_pct", "REAL"),
    ("verification_required", "BOOLEAN"), ("severity", "TEXT"), ("severity_score", "REAL"), ("place", "TEXT"),
    ("facility_id", "TEXT"), ("facility_name", "TEXT"), ("persistent_source_id", "INTEGER"), ("fire_event_id", "INTEGER"),
    ("persistence_days", "INTEGER"), ("review_label", "TEXT"), ("reviewed_by", "TEXT"),
]
SOURCE_FIELDS = [
    ("source_id", "INTEGER"), ("class_code", "TEXT"), ("class_label", "TEXT"), ("category", "TEXT"), ("confidence_pct", "REAL"),
    ("verification_required", "BOOLEAN"), ("first_seen_utc", "TEXT"), ("last_seen_utc", "TEXT"), ("detection_count", "INTEGER"),
    ("active_days", "INTEGER"), ("observation_days", "INTEGER"), ("persistence_ratio", "REAL"), ("night_fraction", "REAL"),
    ("frp_median_mw", "REAL"), ("frp_p90_mw", "REAL"), ("frp_max_mw", "REAL"), ("extent_km", "REAL"), ("trend", "TEXT"),
    ("max_severity", "TEXT"), ("facility_id", "TEXT"),
]
INCIDENT_FIELDS = [
    ("incident_id", "INTEGER"), ("incident_type", "TEXT"), ("severity", "TEXT"), ("status", "TEXT"), ("title", "TEXT"),
    ("summary", "TEXT"), ("recommended_action", "TEXT"), ("authorities", "TEXT"), ("facility_id", "TEXT"), ("detection_id", "TEXT"),
    ("is_drill", "BOOLEAN"), ("created_at_utc", "TEXT"), ("updated_at_utc", "TEXT"), ("updated_by", "TEXT"),
    ("reason_codes", "TEXT"), ("policy_version", "TEXT"),
]
FACILITY_FIELDS = [
    ("facility_id", "TEXT"), ("name", "TEXT"), ("facility_type", "TEXT"), ("sector", "TEXT"), ("operator", "TEXT"), ("state", "TEXT"),
    ("status", "TEXT"), ("detections", "INTEGER"), ("active_days", "INTEGER"), ("open_incidents", "INTEGER"),
    ("geometry_source", "TEXT"), ("osm_element_id", "TEXT"),
]
OSM_FIELDS = [("feature_id", "TEXT"), ("name", "TEXT"), ("category", "TEXT"), ("subtype", "TEXT"), ("operator", "TEXT"), ("osm_url", "TEXT")]


def build_layers(
    detections: Sequence[Dict[str, Any]],
    sources: Sequence[Dict[str, Any]],
    incidents: Sequence[Dict[str, Any]],
    facilities: Sequence[Dict[str, Any]],
    context_features: Iterable[Any],
    boundary: Optional[BaseGeometry],
) -> List[Layer]:
    """Build the GIS layers from the analysis snapshot, incidents, facility catalog and reference data."""
    layer = Layer("detections", "Thermal detections", "NASA FIRMS active-fire pixels with source classification, severity and place", "POINT", DETECTION_FIELDS)
    for d in detections:
        layer.features.append((Point(d["longitude"], d["latitude"]), {
            "detection_id": d["detection_id"], "acq_datetime_utc": d["acq_datetime"], "acq_date": d["acq_date"], "satellite": d["satellite"],
            "instrument": d["instrument"], "daynight": d["daynight"], "frp_mw": d["frp"], "bright_mir_k": d["bright_mir"],
            "bright_tir_k": d["bright_tir"], "firms_confidence": d["confidence"], "data_source": d["data_source"], "category": d["category"],
            "class_code": d["class_code"], "class_label": d.get("class_label"), "confidence_pct": d["confidence_pct"],
            "verification_required": d["verification_required"], "severity": d["severity"], "severity_score": d["severity_score"],
            "place": d.get("place"), "facility_id": d["facility_id"], "facility_name": d.get("facility_name"),
            "persistent_source_id": d["source_id"], "fire_event_id": d["event_id"], "persistence_days": d.get("persistence_days"),
            "review_label": d.get("review_label"), "reviewed_by": d.get("reviewed_by"),
        }))
    layers = [layer]

    layer = Layer("persistent_sources", "Persistent thermal sources", "Locations (750 m) with detections on at least two separate days", "POINT", SOURCE_FIELDS)
    for s in sources:
        layer.features.append((Point(s["longitude"], s["latitude"]), {
            "source_id": s["id"], "class_code": s["class_code"], "class_label": s.get("class_label"), "category": s["category"],
            "confidence_pct": s["confidence_pct"], "verification_required": s["verification_required"], "first_seen_utc": s["first_seen"],
            "last_seen_utc": s["last_seen"], "detection_count": s["detection_count"], "active_days": s["active_days"],
            "observation_days": s["observation_days"], "persistence_ratio": s["persistence_ratio"], "night_fraction": s["night_fraction"],
            "frp_median_mw": s["frp_median"], "frp_p90_mw": s["frp_p90"], "frp_max_mw": s["frp_max"], "extent_km": s["extent_km"],
            "trend": s["trend"], "max_severity": s["max_severity"], "facility_id": s["facility_id"],
        }))
    layers.append(layer)

    layer = Layer("incidents", "Incidents", "Alerts raised by the statistical rules, with triage status", "POINT", INCIDENT_FIELDS)
    for i in incidents:
        geometry = Point(i["longitude"], i["latitude"]) if i.get("latitude") is not None and i.get("longitude") is not None else None
        layer.features.append((geometry, {
            "incident_id": i["id"], "incident_type": i["incident_type"], "severity": i["severity"], "status": i["status"], "title": i["title"],
            "summary": i["summary"], "recommended_action": i["recommended_action"], "authorities": "; ".join(i.get("authorities") or []),
            "facility_id": i["facility_id"], "detection_id": i["detection_id"], "is_drill": i["is_drill"], "created_at_utc": i["created_at"],
            "updated_at_utc": i["updated_at"], "updated_by": i["updated_by"],
            "reason_codes": "; ".join(i.get("reason_codes") or []), "policy_version": i.get("policy_version"),
        }))
    layers.append(layer)

    detections_by_facility = defaultdict(list)
    for d in detections:
        if d["facility_id"]:
            detections_by_facility[d["facility_id"]].append(d)
    open_by_facility = Counter(i["facility_id"] for i in incidents if i["facility_id"] and i["status"] in OPEN_INCIDENT_STATUSES)
    locations = Layer("facility_locations", "Catalog facilities", "Nationally significant facilities with their monitoring status", "POINT", FACILITY_FIELDS)
    boundaries = Layer("facility_boundaries", "Catalog facility boundaries", "Catalog facilities matched to an OpenStreetMap outline", "MULTIPOLYGON", FACILITY_FIELDS)
    for fac in facilities:
        dets = detections_by_facility.get(fac["id"], [])
        attributes = {
            "facility_id": fac["id"], "name": fac["name"], "facility_type": fac["facility_type"], "sector": fac["sector"],
            "operator": fac.get("operator"), "state": fac.get("state"),
            "status": "ALERT" if open_by_facility.get(fac["id"]) else ("ACTIVE" if dets else "NO_DETECTIONS"),
            "detections": len(dets), "active_days": len({d["acq_date"] for d in dets}), "open_incidents": open_by_facility.get(fac["id"], 0),
            "geometry_source": fac.get("geometry_source"), "osm_element_id": fac.get("osm_element_id"),
        }
        locations.features.append((Point(fac["longitude"], fac["latitude"]), attributes))
        if fac.get("geometry"):
            boundaries.features.append((shape(fac["geometry"]), attributes))
    layers += [locations, boundaries]

    areas = Layer("osm_industrial_areas", "OpenStreetMap industrial areas", "Refineries, plants, mines and kiln yards mapped as polygons (ODbL, OpenStreetMap contributors)", "MULTIPOLYGON", OSM_FIELDS)
    points = Layer("osm_industrial_points", "OpenStreetMap industrial points", "Flares, wells and kilns mapped as points (ODbL, OpenStreetMap contributors)", "POINT", OSM_FIELDS)
    for feat in context_features:
        if feat.source != "osm":
            continue
        attributes = {"feature_id": feat.feature_id, "name": feat.name, "category": feat.category, "subtype": feat.subtype,
                      "operator": (feat.properties or {}).get("operator"), "osm_url": f"https://www.openstreetmap.org/{feat.feature_id}"}
        if feat.geometry.geom_type in ("Polygon", "MultiPolygon"):
            areas.features.append((feat.geometry, attributes))
        elif feat.geometry.geom_type == "Point":
            points.features.append((feat.geometry, attributes))
    layers += [areas, points]

    layer = Layer("india_boundary", "India boundary", "Analysis mask: Natural Earth 1:10m admin-0, India point of view", "MULTIPOLYGON", [("name", "TEXT")])
    if boundary is not None:
        layer.features.append((boundary, {"name": "India"}))
    layers.append(layer)
    return layers

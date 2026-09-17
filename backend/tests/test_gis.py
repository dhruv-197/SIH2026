"""GeoPackage writer: OGC GeoPackage 1.4 structure and geometry round trips."""
import sqlite3

from shapely.geometry import Point, Polygon

from app.pipeline.gis_store import GPKG_APPLICATION_ID, Layer, decode_geometry, encode_geometry, layer_to_geojson, write_geopackage

SITE = Polygon([(70.0, 20.0), (71.0, 20.0), (71.0, 21.0), (70.0, 21.0)])


def test_geometry_blob_has_the_geopackage_header_and_round_trips():
    blob = encode_geometry(SITE)
    assert blob[:2] == b"GP" and blob[2] == 0 and blob[3] == 0b00000011
    assert int.from_bytes(blob[4:8], "little") == 4326
    assert decode_geometry(blob).equals(SITE)


def test_geopackage_has_the_required_tables_and_features(tmp_path):
    layers = [
        Layer("points", "Test points", "two points", "POINT", [("name", "TEXT"), ("frp_mw", "REAL"), ("flag", "BOOLEAN")],
              [(Point(72.5, 21.1), {"name": "a", "frp_mw": 3.5, "flag": True}), (Point(74.8, 13.0), {"name": "b", "frp_mw": None, "flag": False})]),
        Layer("areas", "Test areas", "one polygon stored as a multipolygon", "MULTIPOLYGON", [("name", "TEXT")], [(SITE, {"name": "site"})]),
    ]
    path = tmp_path / "layers.gpkg"
    assert write_geopackage(str(path), layers) == {"points": 2, "areas": 1}
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == GPKG_APPLICATION_ID
        assert {row[0] for row in connection.execute("SELECT srs_id FROM gpkg_spatial_ref_sys")} == {-1, 0, 4326}
        contents = {row[0]: row[1:] for row in connection.execute("SELECT table_name, data_type, min_x, min_y, max_x, max_y, srs_id FROM gpkg_contents")}
        assert contents["points"] == ("features", 72.5, 13.0, 74.8, 21.1, 4326)
        assert dict(connection.execute("SELECT table_name, geometry_type_name FROM gpkg_geometry_columns").fetchall()) == {"points": "POINT", "areas": "MULTIPOLYGON"}
        name, frp, flag, geom = connection.execute("SELECT name, frp_mw, flag, geom FROM points ORDER BY fid").fetchone()
        assert (name, frp, flag) == ("a", 3.5, 1) and decode_geometry(geom).equals(Point(72.5, 21.1))
        assert decode_geometry(connection.execute("SELECT geom FROM areas").fetchone()[0]).geom_type == "MultiPolygon"
    finally:
        connection.close()


def test_layer_geojson_keeps_geometry_and_properties():
    layer = Layer("points", "Test points", "", "POINT", [("name", "TEXT")], [(Point(72.5, 21.1), {"name": "a", "ignored": 1})])
    feature = layer_to_geojson(layer)["features"][0]
    assert feature["geometry"]["type"] == "Point" and tuple(feature["geometry"]["coordinates"]) == (72.5, 21.1)
    assert feature["properties"] == {"name": "a"}

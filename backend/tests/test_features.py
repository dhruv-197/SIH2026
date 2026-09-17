import math

from shapely.geometry import box

from app.pipeline.features import FEATURE_COLUMNS, build_feature_table
from app.pipeline.geo_context import ContextFeature, GeoContext
from app.pipeline.landcover import feature_values
from app.pipeline.sources import overpass_clusters


def detection(lat, lon, when, frp=3.0, daynight="N", **extra):
    base = {"latitude": lat, "longitude": lon, "acq_datetime": when, "daynight": daynight, "frp": frp,
            "bright_mir": 330.0, "bright_tir": 292.0, "instrument": "VIIRS", "scan": 0.4, "track": 0.4}
    base.update(extra)
    return base


def no_landcover(lat, lon):
    return feature_values(None)


def test_persistence_counts_distinct_days_within_750m():
    stream = [detection(22.0 + k * 0.0005, 70.0, f"2026-09-0{k + 1}T20:00Z") for k in range(5)]
    stream.append(detection(22.5, 70.5, "2026-09-03T08:00Z", daynight="D"))
    rows, evidence = build_feature_table(stream, GeoContext([]).lookup, no_landcover, observation_days=7)
    assert rows[0]["persistence_days"] == 5
    assert math.isclose(rows[0]["persistence_ratio"], 5 / 7)
    assert rows[-1]["persistence_days"] == 1
    assert evidence[0]["night_fraction_within_750m"] == 1.0


def test_record_fields_cannot_override_features():
    clean = [detection(22.0, 70.0, "2026-09-01T20:00Z")]
    tampered = [detection(22.0, 70.0, "2026-09-01T20:00Z", spread_rate_km_day=99.0, persistence_days=99, revisit_365d=365, lc_tree=1.0)]
    rows_clean, _ = build_feature_table(clean, GeoContext([]).lookup, no_landcover)
    rows_tampered, _ = build_feature_table(tampered, GeoContext([]).lookup, no_landcover)
    for name in FEATURE_COLUMNS:
        a, b = rows_clean[0][name], rows_tampered[0][name]
        assert (math.isnan(a) and math.isnan(b)) or a == b, name


def test_context_distance_and_containment():
    refinery = ContextFeature("way/1", "Test refinery", "oil_gas", "refinery", box(70.0, 22.0, 70.02, 22.02), "osm")
    geo = GeoContext([refinery])
    inside = geo.lookup(22.01, 70.01)
    assert inside["inside_industrial"] and inside["dist_oil_gas_km"] == 0.0
    outside = geo.lookup(22.01, 70.05)
    assert 2.5 < outside["dist_oil_gas_km"] < 3.5
    assert outside["dist_mining_km"] == 50.0


def test_overpass_clusters_sum_frp_within_2km_and_the_same_pass():
    stream = [
        detection(22.0, 70.0, "2026-09-01T20:00Z", frp=10.0),
        detection(22.003, 70.003, "2026-09-01T20:40Z", frp=15.0),  # next satellite, same night, ~450 m away
        detection(22.0, 70.001, "2026-09-02T20:00Z", frp=99.0),  # same place, next night
        detection(22.3, 70.3, "2026-09-01T20:00Z", frp=50.0),  # same pass, far away
    ]
    clusters = overpass_clusters(stream, [0, 1, 2, 3])
    assert clusters[0] == {"detections": 2, "frp_mw": 25.0}
    assert clusters[2]["detections"] == 1 and clusters[3]["detections"] == 1


def test_missing_landcover_is_nan_not_guessed():
    values = feature_values(None)
    assert values["lc_available"] == 0.0
    assert all(math.isnan(values[k]) for k in values if k != "lc_available")

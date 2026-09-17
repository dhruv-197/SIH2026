"""Acceptance scenarios for the trained classifier.

The detection streams below are written by hand or taken from the NASA FIRMS archive (never produced
by the training simulator) and contain only what a real FIRMS feed would contain. Nothing is injected
into the feature vector.
"""
import csv
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from shapely.geometry import box

from app.config import settings
from app.pipeline.classifier import SourceClassifier, interpret
from app.pipeline.features import build_feature_table
from app.pipeline.geo_context import CONTEXT_CATEGORIES, ContextFeature, GeoContext
from app.pipeline.severity import SeverityConfig, assess, robust_baseline
from app.pipeline.sources import overpass_clusters

pytestmark = pytest.mark.skipif(not os.path.exists(settings.MODEL_BUNDLE_PATH), reason="model bundle not trained")

START = datetime(2026, 3, 1, tzinfo=timezone.utc)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture(scope="module")
def classifier():
    return SourceClassifier(settings.MODEL_BUNDLE_PATH)


def landcover(**fractions):
    values = {"lc_tree": 0.0, "lc_shrub_grass": 0.0, "lc_crop": 0.0, "lc_built": 0.0, "lc_bare": 0.0, "lc_water_wetland": 0.0}
    values.update({f"lc_{k}": v for k, v in fractions.items()})
    values["lc_available"] = 1.0
    return lambda lat, lon: values


def det(lat, lon, t, frp, daynight, mir, tir):
    return {"latitude": lat, "longitude": lon, "acq_datetime": t.strftime("%Y-%m-%dT%H:%MZ"), "daynight": daynight, "frp": frp,
            "bright_mir": mir, "bright_tir": tir, "instrument": "VIIRS", "scan": 0.45, "track": 0.42}


def classify(classifier, stream, geo, lc, days=7, index=-1):
    rows, evidence = build_feature_table(stream, geo.lookup, lc, observation_days=days)
    probs = classifier.predict_proba(rows)
    return interpret(probs[index], rows[index], evidence[index]), rows[index], evidence[index]


def test_first_detection_of_a_forest_fire_is_vegetation(classifier):
    rng = np.random.default_rng(1)
    t = START + timedelta(days=6, hours=7, minutes=40)
    stream = [det(30.20 + rng.normal(0, 0.003), 79.20 + rng.normal(0, 0.003), t, rng.uniform(8, 40), "D", rng.uniform(345, 367), rng.uniform(303, 312)) for _ in range(4)]
    decision, _, _ = classify(classifier, stream, GeoContext([]), landcover(tree=0.82, shrub_grass=0.12, crop=0.06))
    assert decision["category"] == "vegetation", decision


def test_night_detection_of_a_forest_fire_is_vegetation(classifier):
    t = START + timedelta(days=5, hours=20, minutes=10)
    stream = [det(11.70, 76.60, t, 22.0, "N", 338.0, 297.0), det(11.703, 76.602, t, 14.0, "N", 331.0, 296.0)]
    decision, _, _ = classify(classifier, stream, GeoContext([]), landcover(tree=0.75, shrub_grass=0.2, crop=0.05))
    assert decision["category"] == "vegetation", decision


def test_faint_night_pixels_of_a_real_forest_fire_far_from_any_mine_are_vegetation(classifier):
    # Real NASA FIRMS detections (VIIRS and MODIS, standard processing) of a forest fire in the Uttarakhand hills, 24-29 April
    # 2024, within ~7 km of 30.28 N 79.12 E, with no mapped industry or mine within 50 km. On several nights the front showed
    # as faint pixels of about 1 MW - as faint as coal-fire pixels - and model 2.1.0 called one of them a coal fire.
    with open(os.path.join(DATA_DIR, "uttarakhand_forest_fire_2024-04.csv"), newline="", encoding="utf-8") as f:
        numeric = ("latitude", "longitude", "frp", "bright_mir", "bright_tir", "scan", "track")
        stream = [{**row, **{key: float(row[key]) for key in numeric}} for row in csv.DictReader(f)]
    rows, evidence = build_feature_table(stream, GeoContext([]).lookup, landcover(tree=0.95, shrub_grass=0.05), observation_days=7)
    decisions = [interpret(p, r, e) for p, r, e in zip(classifier.predict_proba(rows), rows, evidence)]
    assert len(stream) == 51
    assert sum(1 for d in stream if d["daynight"] == "N" and d["instrument"] == "VIIRS" and d["frp"] < 1.5) == 16
    wrong = [(stream[i]["acq_datetime"], stream[i]["frp"], d["class_code"], d["category_confidence"]) for i, d in enumerate(decisions) if d["category"] != "vegetation"]
    assert not wrong, wrong


def test_scattered_daytime_crop_fires_are_agricultural(classifier):
    rng = np.random.default_rng(2)
    stream = []
    for day in range(3):
        for _ in range(9):
            t = START + timedelta(days=4 + day, hours=8, minutes=int(rng.integers(0, 50)))
            stream.append(det(30.25 + rng.uniform(-0.08, 0.08), 75.84 + rng.uniform(-0.08, 0.08), t, rng.uniform(1.5, 9), "D", rng.uniform(328, 350), rng.uniform(300, 310)))
    rows, evidence = build_feature_table(stream, GeoContext([]).lookup, landcover(crop=0.88, built=0.05, tree=0.07), observation_days=7)
    probs = classifier.predict_proba(rows)
    decisions = [interpret(p, r, e) for p, r, e in zip(probs, rows, evidence)]
    vegetation = sum(d["category"] == "vegetation" for d in decisions) / len(decisions)
    agricultural = sum(d["class_code"] == "agricultural" for d in decisions) / len(decisions)
    assert vegetation >= 0.9, decisions[:3]
    assert agricultural >= 0.8


def test_unmapped_persistent_night_flare_is_industrial(classifier):
    rng = np.random.default_rng(3)
    stream = []
    for day in range(7):
        if day == 2:
            continue  # cloudy night
        t = START + timedelta(days=day, hours=20, minutes=int(rng.integers(0, 40)))
        stream.append(det(26.62 + rng.normal(0, 0.0012), 93.73 + rng.normal(0, 0.0012), t, rng.uniform(1.5, 6), "N", rng.uniform(318, 345), rng.uniform(288, 295)))
    decision, _, evidence = classify(classifier, stream, GeoContext([]), landcover(bare=0.35, built=0.25, crop=0.25, tree=0.15))
    assert evidence["persistence_days"] == 6
    assert decision["category"] == "industrial", decision


def test_mapped_steel_plant_is_heavy_industry(classifier):
    plant = ContextFeature("way/65310813", "Bhilai Steel Plant", "heavy_industry", "steel", box(81.37, 21.17, 81.43, 21.21), "osm")
    rng = np.random.default_rng(4)
    stream = []
    for day in range(7):
        for _ in range(int(rng.integers(1, 4))):
            t = START + timedelta(days=day, hours=int(rng.choice([8, 20])), minutes=int(rng.integers(0, 40)))
            # Hot spots move around the works (slag dumping, coke pushing), so they scatter over ~1 km.
            stream.append(det(21.19 + rng.uniform(-0.01, 0.01), 81.40 + rng.uniform(-0.01, 0.01), t, rng.uniform(1, 5), "N" if t.hour == 20 else "D", rng.uniform(320, 340), rng.uniform(292, 305)))
    decision, _, _ = classify(classifier, stream, GeoContext([plant]), landcover(built=0.6, bare=0.25, shrub_grass=0.15))
    assert decision["category"] == "industrial"
    assert decision["class_code"] == "heavy_industry", decision


def test_coal_fire_field_is_mining(classifier):
    mine = ContextFeature("way/117807504", "Coal mine", "mining", "coal_mine", box(86.38, 23.72, 86.46, 23.77), "osm")
    rng = np.random.default_rng(5)
    cells = [(23.745 + rng.uniform(-0.015, 0.015), 86.42 + rng.uniform(-0.03, 0.03)) for _ in range(20)]
    stream = []
    for day in range(7):
        for lat, lon in cells:
            if rng.random() < 0.18:
                t = START + timedelta(days=day, hours=int(rng.choice([8, 20])), minutes=int(rng.integers(0, 40)))
                stream.append(det(lat, lon, t, rng.uniform(1, 5), "N" if t.hour == 20 else "D", rng.uniform(315, 335), rng.uniform(292, 303)))
    decision, _, _ = classify(classifier, stream, GeoContext([mine]), landcover(bare=0.7, shrub_grass=0.15, tree=0.15))
    assert decision["class_code"] == "mining_coal_fire", decision


def test_advancing_wildfire_near_power_plant_stays_vegetation_and_raises_cross_alert(classifier):
    plant = ContextFeature("way/196019571", "Vindhyachal", "heavy_industry", "thermal_power", box(82.66, 24.08, 82.69, 24.11), "osm")
    rng = np.random.default_rng(6)
    stream = []
    for step in range(4):
        t = START + timedelta(days=3 + step, hours=8, minutes=int(rng.integers(0, 40)))
        lat = 24.20 - step * 0.025  # ~2.8 km/day towards the plant
        for _ in range(3 + step):
            stream.append(det(lat + rng.normal(0, 0.002), 82.675 + rng.normal(0, 0.004), t, rng.uniform(10, 45), "D", rng.uniform(345, 367), rng.uniform(303, 312)))
    geo = GeoContext([plant])
    decision, row, evidence = classify(classifier, stream, geo, landcover(tree=0.7, shrub_grass=0.25, built=0.05))
    assert decision["category"] == "vegetation", decision
    distance = min(row[f"dist_{c}_km"] for c in CONTEXT_CATEGORIES)
    severity = assess(frp=30.0, category=decision["category"], class_code=decision["class_code"], dist_industrial_km=distance,
                      inside_industrial=False, event_cells=evidence["active_cells_within_5km_3d"], baseline=None, config=SeverityConfig())
    assert distance <= 2.0
    assert severity["is_cross_alert"] and severity["severity"] == "HIGH"


def test_one_night_flaring_upset_at_a_refinery_is_industrial_and_raises_an_alert(classifier):
    # Modelled on a real week of VIIRS data at a coastal refinery: one night, a tight cluster of hot pixels
    # (a bright core plus weaker neighbours) from two passes 19 minutes apart, nothing on the other days.
    refinery = ContextFeature("way/62004860", "Coastal refinery", "oil_gas", "refinery", box(74.835, 12.965, 74.875, 13.0), "osm")
    t1 = START + timedelta(days=4, hours=21, minutes=14)
    t2 = t1 + timedelta(minutes=19)
    offsets = [(-0.004, 0.001), (-0.002, 0.005), (-0.001, 0.0), (0.0, -0.005), (0.001, 0.002), (0.002, -0.003), (0.004, 0.0)]
    frps = [3.1, 3.6, 17.0, 17.0, 19.3, 19.3, 2.7]
    mirs = [306.0, 304.7, 351.0, 310.5, 333.6, 325.0, 307.3]
    stream = [det(12.9835 + dy, 74.8535 + dx, t1, frp, "N", mir, 290.8 + 0.2 * k) for k, ((dy, dx), frp, mir) in enumerate(zip(offsets, frps, mirs))]
    stream += [det(12.9864, 74.8533, t2, 4.9, "N", 326.3, 287.5), det(12.9874, 74.8519, t2, 5.8, "N", 323.6, 287.7)]
    rows, evidence = build_feature_table(stream, GeoContext([refinery]).lookup, landcover(built=0.5, tree=0.3, shrub_grass=0.08, bare=0.06, water_wetland=0.06), observation_days=8)
    decisions = [interpret(p, r, e) for p, r, e in zip(classifier.predict_proba(rows), rows, evidence)]
    assert all(d["category"] == "industrial" for d in decisions), [(d["class_code"], d["category_confidence"]) for d in decisions]
    cluster = overpass_clusters(stream, list(range(len(stream))))[4]
    severity = assess(frp=stream[4]["frp"], category="industrial", class_code=decisions[4]["class_code"], dist_industrial_km=0.0, inside_industrial=True,
                      event_cells=evidence[4]["active_cells_within_5km_3d"], baseline=None, config=SeverityConfig(), new_activity=cluster)
    assert cluster["detections"] == 9
    assert severity["severity"] == "HIGH" and severity["incident_type"] == "INDUSTRIAL_HIGH_INTENSITY"


def test_daytime_grass_fire_in_a_plant_green_belt_is_vegetation_and_flagged(classifier):
    works = ContextFeature("way/1", "Integrated steel works", "heavy_industry", "steel", box(83.12, 17.57, 83.22, 17.66), "osm")
    rng = np.random.default_rng(8)
    stream = []
    for day in range(7):  # the plant's own furnace heat, most nights, in the built-up core
        if day == 3:
            continue
        t = START + timedelta(days=day, hours=20, minutes=int(rng.integers(0, 40)))
        stream.append(det(17.63 + rng.normal(0, 0.001), 83.19 + rng.normal(0, 0.001), t, rng.uniform(2, 6), "N", rng.uniform(320, 335), rng.uniform(290, 296)))
    t = START + timedelta(days=5, hours=8, minutes=5)  # early afternoon local time, a short front in the green belt ~7 km away
    for k in range(4):
        stream.append(det(17.585 + 0.003 * k, 83.14 + rng.normal(0, 0.001), t, rng.uniform(2, 8), "D", rng.uniform(335, 352), rng.uniform(305, 312)))
    core, green_belt = landcover(built=0.6, bare=0.25, tree=0.15), landcover(tree=0.45, shrub_grass=0.4, built=0.1, bare=0.05)

    def lc(lat, lon):
        return core(lat, lon) if abs(lat - 17.63) < 0.01 and abs(lon - 83.19) < 0.01 else green_belt(lat, lon)

    decision, _, _ = classify(classifier, stream, GeoContext([works]), lc)
    assert decision["category"] == "vegetation", decision
    assert decision["verification_required"]


def test_frp_excursion_against_source_history_is_critical():
    history = [3.1, 2.8, 3.4, 2.9, 3.3, 3.0, 2.7, 3.2]
    baseline = robust_baseline(history, prior_days=5, config=SeverityConfig())
    result = assess(frp=85.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.0, inside_industrial=True,
                    event_cells=1, baseline=baseline, config=SeverityConfig())
    assert result["severity"] == "CRITICAL"
    assert result["override_class"] == "industrial_accident"
    assert "robust standard deviations" in result["triggers"][0]


def test_normal_variation_is_not_an_alert():
    history = [3.1, 2.8, 3.4, 2.9, 3.3, 3.0, 2.7, 3.2]
    baseline = robust_baseline(history, prior_days=5, config=SeverityConfig())
    result = assess(frp=4.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.0, inside_industrial=True,
                    event_cells=1, baseline=baseline, config=SeverityConfig())
    assert result["severity"] == "NORMAL"


def test_new_multi_pixel_activity_at_an_industrial_site_is_high():
    result = assess(frp=12.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.4, inside_industrial=False,
                    event_cells=5, baseline=None, config=SeverityConfig(), new_activity={"detections": 9, "frp_mw": 92.0})
    assert result["severity"] == "HIGH" and result["incident_type"] == "INDUSTRIAL_HIGH_INTENSITY"
    assert "9 detections totalling 92 MW" in result["triggers"][0]


def test_small_or_off_site_new_activity_is_not_an_alert():
    small = assess(frp=3.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.0, inside_industrial=True,
                   event_cells=1, baseline=None, config=SeverityConfig(), new_activity={"detections": 2, "frp_mw": 6.0})
    off_site = assess(frp=30.0, category="industrial", class_code="heavy_industry", dist_industrial_km=5.0, inside_industrial=False,
                      event_cells=4, baseline=None, config=SeverityConfig(), new_activity={"detections": 4, "frp_mw": 120.0})
    assert small["severity"] == "NORMAL" and off_site["severity"] == "NORMAL"


def test_intense_fire_next_to_infrastructure_alerts_even_when_classification_is_uncertain():
    uncertain = assess(frp=8.3, category="vegetation", class_code="agricultural", dist_industrial_km=0.32, inside_industrial=False,
                       event_cells=1, baseline=None, config=SeverityConfig(), category_confidence=0.65)
    weak = assess(frp=1.4, category="vegetation", class_code="wildfire", dist_industrial_km=0.1, inside_industrial=False,
                  event_cells=5, baseline=None, config=SeverityConfig(), category_confidence=0.6)
    assert uncertain["incident_type"] == "CROSS_ALERT" and "uncertain" in uncertain["triggers"][0]
    assert weak["severity"] == "NORMAL"

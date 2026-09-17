"""Alert policy: reason codes, the policy version, the fire front's direction of travel, the wind's relation to a
facility and the attention funnel (pure functions - no trained model or network needed)."""
from datetime import datetime, timedelta, timezone

from shapely.geometry import box

from app.pipeline.approach import angle_between, bearing_deg, compass, fire_approach
from app.pipeline.funnel import alert_funnel
from app.pipeline.severity import SeverityConfig, apply_fire_approach, assess, policy_info, robust_baseline
from app.pipeline.weather import wind_relation

START = datetime(2026, 3, 1, tzinfo=timezone.utc)
PLANT = box(82.66, 24.08, 82.69, 24.11)  # a power plant outline; its north edge is at 24.11


def det(lat, lon, t):
    return {"latitude": lat, "longitude": lon, "acq_datetime": t.strftime("%Y-%m-%dT%H:%MZ")}


def front(distances_km):
    """One morning detection per day, due north of the plant, at these distances from its outline."""
    return [det(24.11 + d / 110.57, 82.675, START + timedelta(days=k, hours=8)) for k, d in enumerate(distances_km)]


def test_every_alert_carries_reason_codes():
    history = [3.1, 2.8, 3.4, 2.9, 3.3, 3.0, 2.7, 3.2]
    excursion = assess(frp=85.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.0, inside_industrial=True,
                       event_cells=1, baseline=robust_baseline(history, prior_days=5, config=SeverityConfig()), config=SeverityConfig())
    cluster = assess(frp=12.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.4, inside_industrial=False,
                     event_cells=5, baseline=None, config=SeverityConfig(), new_activity={"detections": 9, "frp_mw": 92.0})
    uncertain = assess(frp=8.3, category="vegetation", class_code="agricultural", dist_industrial_km=0.32, inside_industrial=False,
                       event_cells=4, baseline=None, config=SeverityConfig(), category_confidence=0.65)
    quiet = assess(frp=4.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.0, inside_industrial=True,
                   event_cells=1, baseline=None, config=SeverityConfig())
    assert excursion["reason_codes"] == ["ABN_BASELINE_EXCEEDED", "ABN_ABOVE_P90"]
    assert cluster["reason_codes"] == ["NEW_HEAT_AT_SITE", "NO_BASELINE", "MULTI_PIXEL_CLUSTER"]
    assert uncertain["reason_codes"] == ["VEG_FIRE_NEAR_INFRA", "FIRE_SPREAD_CELLS", "CONF_LOW"]
    assert quiet["severity"] == "NORMAL" and quiet["reason_codes"] == []


def test_policy_version_follows_the_thresholds():
    default = policy_info(SeverityConfig())
    assert default["version"] == policy_info(SeverityConfig())["version"]
    changed = policy_info(SeverityConfig(cross_alert_km=2.5))
    assert changed["rules_version"] == default["rules_version"] and changed["version"] != default["version"]
    assert changed["thresholds"]["cross_alert_km"] == 2.5


def test_a_fire_front_closing_in_is_approaching():
    records = front([5.0, 3.9, 2.8, 1.7])
    result = fire_approach(records, records[-1], PLANT, "Vindhyachal")
    assert result["status"] == "approaching" and result["side"] == "north"
    assert result["first_km"] > result["latest_km"] and 0.9 < result["closing_rate_km_per_day"] < 1.3
    assert "Vindhyachal" in result["summary"] and len(result["front_by_day"]) == 4


def test_receding_holding_and_single_day_fronts_are_not_approaching():
    receding, holding, single = front([1.5, 2.8, 4.0]), front([1.6, 1.4, 1.7, 1.5]), front([1.2])
    assert fire_approach(receding, receding[-1], PLANT, "plant")["status"] == "receding"
    assert fire_approach(holding, holding[-1], PLANT, "plant")["status"] == "holding"
    assert fire_approach(single, single[-1], PLANT, "plant")["status"] == "insufficient_data"


def test_separate_fires_on_different_days_are_not_a_moving_front():
    # Modelled on a real week near a steel works: two small night fires 7.8 km out, then two days later a
    # fire 1.7 km out in another field - closer, but not the same fire.
    earlier = det(24.11 + 7.8 / 110.57, 82.675, START + timedelta(hours=20))
    later = det(24.11 + 1.7 / 110.57, 82.675, START + timedelta(days=2, hours=7))
    result = fire_approach([earlier, later], later, PLANT, "the steel works")
    assert result["status"] == "insufficient_data" and result["separate_fire_days"] == 1
    assert "separate" in result["summary"] and abs(result["latest_km"] - 1.7) < 0.05


def test_fires_on_the_other_side_of_the_plant_are_not_mixed_in():
    today_north = front([1.8])
    yesterday_south = [det(24.08 - 6.0 / 110.57, 82.675, START - timedelta(days=1) + timedelta(hours=8))]
    result = fire_approach(yesterday_south + today_north, today_north[-1], PLANT, "plant")
    assert result["status"] == "insufficient_data" and result["detections_used"] == 1


def test_an_approaching_front_makes_a_cross_alert_critical():
    cross = assess(frp=30.0, category="vegetation", class_code="wildfire", dist_industrial_km=1.7, inside_industrial=False,
                   event_cells=6, baseline=None, config=SeverityConfig(), category_confidence=0.9)
    approaching = front([5.0, 3.9, 2.8, 1.7])
    escalated = apply_fire_approach(cross, fire_approach(approaching, approaching[-1], PLANT, "Vindhyachal"))
    assert cross["severity"] == "HIGH"
    assert escalated["severity"] == "CRITICAL" and escalated["severity_score"] >= 85 and escalated["reason_codes"][-1] == "FIRE_APPROACHING"
    assert escalated["triggers"][-1].startswith("Fire front closed in on Vindhyachal")
    holding = front([1.6, 1.4, 1.7, 1.5])
    kept = apply_fire_approach(cross, fire_approach(holding, holding[-1], PLANT, "Vindhyachal"))
    assert kept["severity"] == "HIGH" and kept["fire_approach"]["status"] == "holding"
    industrial = assess(frp=4.0, category="industrial", class_code="gas_flare", dist_industrial_km=0.0, inside_industrial=True,
                        event_cells=1, baseline=None, config=SeverityConfig())
    assert apply_fire_approach(industrial, kept["fire_approach"]) is industrial


def test_wind_relation_to_a_facility():
    fire, plant = (24.2, 82.675), (24.095, 82.675)  # the fire is north of the plant
    assert wind_relation(0.0, 20.0, *fire, *plant) == "towards"  # a north wind blows the fire towards the plant
    assert wind_relation(180.0, 20.0, *fire, *plant) == "away"
    assert wind_relation(90.0, 20.0, *fire, *plant) == "across"
    assert wind_relation(0.0, 3.0, *fire, *plant) == "calm"
    assert compass(bearing_deg(24.0, 82.0, 25.0, 82.0)) == "north" and compass(225.0) == "south-west"
    assert angle_between(350.0, 10.0) == 20.0


def test_high_intensity_vegetation_alerts_are_grouped_per_fire_complex():
    from app.pipeline.service import PipelineService

    records = [det(24.00, 80.00, START), det(24.02, 80.01, START + timedelta(days=1)), det(24.30, 80.00, START)]  # 2.4 km apart; the third 33 km away
    for k, record in enumerate(records):
        record["detection_id"] = f"D{k}"
    complexes = PipelineService._fire_complexes(records, [0, 1, 2])
    assert complexes[0] == complexes[1] != complexes[2] and complexes[0].startswith("C")
    assert PipelineService._fire_complexes(records, []) == {}


def test_funnel_counts_locations_alerts_and_pending_reviews():
    def d(i, source=None, event=None, severity="NORMAL", verify=False, label=None, category="industrial"):
        return {"detection_id": f"D{i}", "source_id": source, "event_id": event, "severity": severity,
                "verification_required": verify, "review_label": label, "category": category}

    detections = [d(1, source=1), d(2, source=1), d(3, source=2, severity="HIGH"), d(4, event=7, verify=True, category="vegetation"),
                  d(5, event=8, verify=True, label="wildfire", category="vegetation"), d(6, event=9, category="vegetation")]
    funnel = alert_funnel(detections, sources=[{}, {}], open_incidents=1)
    assert funnel["detections"] == 6 and funnel["locations"] == 5 and funnel["fire_events"] == 3
    assert funnel["alerting_locations"] == 1 and funnel["review_locations"] == 1 and funnel["routine_locations"] == 3
    assert funnel["needing_attention"] == 2 and funnel["attention_share"] == round(2 / 6, 4)

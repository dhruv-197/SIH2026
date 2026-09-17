"""Sentinel-2 imagery evidence: band maths and interpretation rules (no network)."""
import asyncio
from datetime import datetime, timezone

from app.pipeline.imagery import assess, interpret, radiometric_offset, scene_expressions, scene_metrics


def scene(days, hot=0, cloud=0.1, land=0.8, nbr=0.4, nhi=None, p5=None):
    return {"id": f"S2-{days}", "date": f"day {days}", "days_from_detection": days, "hot_pixels": hot, "cloud_fraction": cloud,
            "land_fraction": land, "nbr_land": nbr, "nbr_land_p5": p5, "max_nhi_swir": nhi if nhi is not None else (0.3 if hot else -0.05)}


def test_expressions_correct_for_the_l2a_radiometric_offset():
    assert radiometric_offset({"s2:processing_baseline": "05.11"}) == 1000
    assert radiometric_offset({"s2:processing_baseline": "03.01"}) == 0
    expressions = scene_expressions(1000)
    assert len(expressions) == 6 and "B12>2500" in expressions[2] and "-2000" in expressions[2]


def test_scene_metrics_from_the_statistics_response():
    stats = [{"mean": 0.9, "count": 800}, {"mean": 0.05, "count": 800}, {"mean": 0.01, "count": 800}, {"max": 0.39, "count": 800},
             {"mean": 0.27, "count": 800}, {"mean": 0.4, "count": 800, "percentile_5": 0.12}]
    assert scene_metrics(stats) == {"valid_pixels": 800, "land_fraction": 0.9, "cloud_fraction": 0.05, "hot_pixels": 8,
                                    "max_nhi_swir": 0.39, "nbr_land": 0.3, "nbr_land_p5": 0.12}


def test_burn_scar_supports_a_vegetation_fire():
    result = interpret([scene(-4, nbr=0.45), scene(3, nbr=0.12)])
    assert result["supports"] == "vegetation" and result["burn_scar"]["dnbr"] == 0.33


def test_small_severe_burn_is_found_in_the_darkest_land_pixels():
    result = interpret([scene(-4, land=0.9, nbr=0.42, p5=0.3), scene(3, land=0.9, nbr=0.39, p5=0.02)])
    assert result["status"] == "supports_vegetation" and result["burn_scar"]["dnbr_darkest_5pct"] == 0.28


def test_heat_on_separate_dates_without_burn_scar_supports_industrial():
    result = interpret([scene(-2, hot=6, nbr=0.21), scene(3, hot=4, nbr=0.2)])
    assert result["status"] == "supports_industrial" and result["hotspot"]["persistent"]


def test_burn_scar_next_to_persistent_heat_is_mixed():
    assert interpret([scene(-3, hot=5, nbr=0.45), scene(3, hot=7, nbr=0.15)])["status"] == "mixed"


def test_weaker_evidence_is_reported_as_such():
    assert interpret([scene(-1, hot=3)])["status"] == "heat_confirmed"
    assert interpret([scene(-1, hot=1, nhi=0.12)])["status"] == "no_evidence"  # one marginal pixel is not heat
    assert interpret([scene(-3), scene(4, nbr=0.38)])["status"] == "no_evidence"
    assert interpret([scene(-1, cloud=0.9, land=0.05, nbr=None), scene(2, cloud=0.95, land=0.02, nbr=None)])["status"] == "inconclusive"
    assert interpret([])["status"] == "none_found"


def test_offline_mode_makes_no_request():
    result = asyncio.run(assess(20.965, 85.176, datetime(2026, 9, 14, 10, 2, tzinfo=timezone.utc)))
    assert result["status"] == "unavailable" and result["scenes"] == []

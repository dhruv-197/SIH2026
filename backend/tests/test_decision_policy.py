"""The decision policy applied on top of the classifier's probabilities (no trained model needed)."""
from app.pipeline.classifier import interpret
from app.pipeline.taxonomy import MODEL_CLASSES


def probs(**values):
    return [values.get(code, 0.0) for code in MODEL_CLASSES]


def context(**overrides):
    features = {"inside_industrial": 0.0, "lc_available": 1.0, "dist_oil_gas_km": 50.0, "dist_heavy_industry_km": 50.0, "dist_mining_km": 50.0}
    features.update(overrides)
    return features


def test_category_uses_summed_group_probability_and_subtype_stays_inside_it():
    decision = interpret(probs(gas_flare=0.3, heavy_industry=0.25, wildfire=0.45), context(dist_oil_gas_km=0.2), {"persistence_days": 4, "detections_within_750m": 9})
    assert decision["category"] == "industrial" and decision["class_code"] == "gas_flare"
    assert decision["verification_required"]  # 55 % is mixed evidence


def test_single_day_industrial_heat_far_from_mapped_industry_needs_verification():
    far = interpret(probs(gas_flare=0.95, wildfire=0.05), context(dist_heavy_industry_km=12.0), {"persistence_days": 1, "detections_within_750m": 3})
    recurring = interpret(probs(gas_flare=0.95, wildfire=0.05), context(dist_heavy_industry_km=12.0), {"persistence_days": 5, "detections_within_750m": 9})
    at_site = interpret(probs(gas_flare=0.95, wildfire=0.05), context(dist_oil_gas_km=0.3), {"persistence_days": 1, "detections_within_750m": 3})
    assert far["verification_required"] and not recurring["verification_required"] and not at_site["verification_required"]


def test_vegetation_fire_inside_a_mapped_industrial_site_needs_verification():
    decision = interpret(probs(wildfire=0.9, heavy_industry=0.1), context(inside_industrial=1.0, dist_heavy_industry_km=0.0), {"persistence_days": 1, "detections_within_750m": 4})
    assert decision["category"] == "vegetation" and decision["verification_required"]

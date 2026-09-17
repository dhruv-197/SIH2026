"""Source classes, their grouping into industrial vs vegetation fires, analyst review labels and display metadata."""

MODEL_CLASSES = ["gas_flare", "heavy_industry", "mining_coal_fire", "wildfire", "agricultural"]

# Assigned by the statistical excursion test in severity.py, never by the classifier itself:
# thermal data alone cannot confirm an explosion, so it is always reported as "suspected".
INDUSTRIAL_ACCIDENT = "industrial_accident"

CLASS_LABELS = {
    "gas_flare": "Gas Flare / Oil & Gas Facility",
    "heavy_industry": "Heavy Industry (Steel, Cement, Power, Kilns)",
    "mining_coal_fire": "Mining / Coal Fire",
    "wildfire": "Wildfire / Forest Fire",
    "agricultural": "Agricultural / Biomass Burning",
    INDUSTRIAL_ACCIDENT: "Suspected Industrial Fire / Explosion",
}

INDUSTRIAL_CLASSES = {"gas_flare", "heavy_industry", "mining_coal_fire", INDUSTRIAL_ACCIDENT}

CATEGORY_LABELS = {
    "industrial": "Industrial / extractive heat source",
    "vegetation": "Vegetation fire (forest or agricultural)",
}

# Okabe-Ito based palette: distinguishable under common colour-vision deficiencies.
CLASS_COLORS = {
    "gas_flare": "#E69F00",
    "heavy_industry": "#0072B2",
    "mining_coal_fire": "#CC79A7",
    "wildfire": "#009E73",
    "agricultural": "#C9A800",
    INDUSTRIAL_ACCIDENT: "#D55E00",
}

# Labels an analyst can give when reviewing a detection: the source classes plus outcomes the model cannot produce.
# Reviews therefore also collect evidence for classes that cannot be separated yet, without retraining the model.
REVIEW_LABELS = {
    "gas_flare": {"label": "Gas flare / oil & gas facility", "category": "industrial"},
    "heavy_industry": {"label": "Heavy industry (steel, cement, power, kilns)", "category": "industrial"},
    "mining_coal_fire": {"label": "Mining / coal fire", "category": "industrial"},
    INDUSTRIAL_ACCIDENT: {"label": "Industrial fire or explosion", "category": "industrial"},
    "wildfire": {"label": "Wildfire / forest fire", "category": "vegetation"},
    "agricultural": {"label": "Agricultural / biomass burning", "category": "vegetation"},
    "other_heat_source": {"label": "Other heat source (landfill, waste or urban fire)", "category": None},
    "not_a_fire": {"label": "No heat source (false detection)", "category": None},
    "unsure": {"label": "Unsure - needs a field check", "category": None},
}

REVIEW_EVIDENCE = {
    "satellite_imagery": "Recent satellite imagery",
    "operator_contact": "Facility operator or safety officer",
    "field_visit": "Field visit",
    "official_report": "Official report or news",
    "local_knowledge": "Local knowledge",
}


def category_for(class_code: str) -> str:
    return "industrial" if class_code in INDUSTRIAL_CLASSES else "vegetation"


def taxonomy_payload():
    return {
        "classes": [
            {
                "code": code,
                "label": CLASS_LABELS[code],
                "category": category_for(code),
                "color": CLASS_COLORS[code],
                "assigned_by": "excursion_test" if code == INDUSTRIAL_ACCIDENT else "classifier",
            }
            for code in MODEL_CLASSES + [INDUSTRIAL_ACCIDENT]
        ],
        "categories": CATEGORY_LABELS,
        "review_labels": [{"code": code, **meta} for code, meta in REVIEW_LABELS.items()],
        "review_evidence": REVIEW_EVIDENCE,
    }

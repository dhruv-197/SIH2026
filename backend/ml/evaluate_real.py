"""Checks of the classifier on real FIRMS detections against independent evidence.

There are no ground-truth source labels for Indian FIRMS detections, so this script uses
*proxy* labels built from evidence the model can be tested without, and ablations that remove
that evidence from the model input:

A. Mapped industrial sites: detections recurring on >= 3 days inside a mapped OSM industrial or
   mining polygon (or within 500 m of a mapped flare/well/kiln point). Expected: industrial.
   Ablation: the same detections with all map features removed - does the model still say
   industrial from persistence and radiometry alone (the situation at unmapped facilities)?
B. Vegetation-dominated footprints far from industry: WorldCover tree or cropland >= 60 %,
   >= 10 km from any mapped industrial feature, single-day location. Expected: vegetation.
   Ablation: land cover removed.
C. NASA's static-source flag (archive files only): FIRMS standard-processing records carry a
   "type" - 2 for "other static land source" (persistent heat such as flares, furnaces and
   kilns) and 0 for "presumed vegetation fire". NASA derives it from how often a location has
   burned over the years, independently of our maps and land cover. Industrial sites without a
   long record stay "presumed vegetation" in it, so it is a second opinion, not ground truth.

Proxy labels are not ground truth: set A is biased towards well-mapped sites, set B towards
clear-cut landscapes. The numbers show consistency with independent evidence, not field accuracy.

Usage (after build_dataset.py):  py backend/ml/evaluate_real.py
Archive week:  py backend/ml/evaluate_real.py --db backend/app/data/archive/<name>/geothermal.db --key archive_data_checks
"""
import argparse
import json
import os
import sys
from collections import Counter

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

POINT_SUBTYPES = {"gas_flare", "oil_gas_well", "kiln"}


def share(values, expected):
    return round(sum(1 for v in values if v == expected) / len(values), 4) if values else None


def main():
    parser = argparse.ArgumentParser(description="Checks of the classifier on real FIRMS detections")
    parser.add_argument("--db", help="database to evaluate (default: the live database)")
    parser.add_argument("--key", default="real_data_checks", help="section of evaluation_report.json to write")
    args = parser.parse_args()
    if args.db:  # must be set before the app reads its configuration
        db_path = os.path.abspath(args.db)
        os.environ["GEOTHERMAL_DB_PATH"] = db_path
        os.environ.setdefault("GEOTHERMAL_GIS_STORE_PATH", os.path.join(os.path.dirname(db_path), "gis", "geothermal_sentinel.gpkg"))

    from app.config import settings
    from app.db.database import SessionLocal
    from app.db.models import DetectionModel
    from app.pipeline.classifier import interpret
    from app.pipeline.features import build_feature_table
    from app.pipeline.geo_context import CONTEXT_CATEGORIES, MAX_CONTEXT_KM
    from app.pipeline.landcover import LANDCOVER_FEATURES
    from app.pipeline.service import service

    def categories(probs, rows, evidence):
        return [interpret(p, r, e)["category"] for p, r, e in zip(probs, rows, evidence)]

    service.startup()
    with SessionLocal() as db:
        stored = db.query(DetectionModel).filter(DetectionModel.data_source != "drill").order_by(DetectionModel.acq_datetime).all()
        records = [row.to_record() for row in stored]
        served = {row.detection_id: row.category for row in stored}
        firms_types = {row.detection_id: row.firms_type for row in stored}
    if not records:
        raise SystemExit("No detections - build a dataset first")
    rows, evidence = build_feature_table(records, service.geo.lookup, service.landcover.features)
    probs = service.classifier.predict_proba(rows)
    predicted = categories(probs, rows, evidence)

    set_a = []
    for i, (row, ev) in enumerate(zip(rows, evidence)):
        if row["persistence_days"] < 3:
            continue
        inside = ev.get("inside_feature")
        nearest = ev.get("nearest_industrial_feature")
        if (inside and inside["source"] == "osm") or (nearest and nearest["source"] == "osm" and nearest["subtype"] in POINT_SUBTYPES and nearest["distance_km"] <= 0.5):
            set_a.append(i)

    set_b = []
    for i, (row, ev) in enumerate(zip(rows, evidence)):
        if row["lc_available"] < 0.5 or row["persistence_days"] > 1:
            continue
        if max(row["lc_tree"], row["lc_crop"]) < 0.6:
            continue
        if min(row[f"dist_{c}_km"] for c in CONTEXT_CATEGORIES) < 10.0:
            continue
        set_b.append(i)

    def ablate(indices, remove):
        changed = []
        for i in indices:
            row = dict(rows[i])
            if remove == "maps":
                for c in CONTEXT_CATEGORIES:
                    row[f"dist_{c}_km"] = MAX_CONTEXT_KM
                row["inside_industrial"] = 0.0
            elif remove == "landcover":
                for name in LANDCOVER_FEATURES:
                    row[name] = float("nan")
                row["lc_available"] = 0.0
            changed.append(row)
        if not changed:
            return []
        p = service.classifier.predict_proba(changed)
        return categories(p, changed, [evidence[i] for i in indices])

    a_pred = [predicted[i] for i in set_a]
    a_by_feature = Counter((evidence[i].get("inside_feature") or evidence[i].get("nearest_industrial_feature"))["subtype"] for i in set_a)
    b_pred = [predicted[i] for i in set_b]

    checks = {
        "method": __doc__.split("Usage")[0].strip(),
        "detections_evaluated": len(records),
        "observation_window": service.snapshot.get("window"),
        "dataset_label": settings.DATASET_LABEL or None,
        "predicted_category_distribution": dict(Counter(predicted)),
        "A_mapped_industrial_sites": {
            "detections": len(set_a),
            "feature_subtypes": dict(a_by_feature),
            "share_predicted_industrial": share(a_pred, "industrial"),
            "ablation_without_map_features_share_industrial": share(ablate(set_a, "maps"), "industrial"),
        },
        "B_vegetation_far_from_industry": {
            "detections": len(set_b),
            "share_predicted_vegetation": share(b_pred, "vegetation"),
            "ablation_without_landcover_share_vegetation": share(ablate(set_b, "landcover"), "vegetation"),
        },
    }
    checks["summary"] = {
        "mapped_industrial_agreement": checks["A_mapped_industrial_sites"]["share_predicted_industrial"],
        "mapped_industrial_agreement_without_maps": checks["A_mapped_industrial_sites"]["ablation_without_map_features_share_industrial"],
        "vegetation_agreement": checks["B_vegetation_far_from_industry"]["share_predicted_vegetation"],
        "vegetation_agreement_without_landcover": checks["B_vegetation_far_from_industry"]["ablation_without_landcover_share_vegetation"],
        "sample_sizes": {"A": len(set_a), "B": len(set_b)},
    }

    static = [i for i, r in enumerate(records) if firms_types.get(r["detection_id"]) == 2]
    presumed = [i for i, r in enumerate(records) if firms_types.get(r["detection_id"]) == 0]
    if static or presumed:
        checks["C_nasa_static_source_flag"] = {
            "static_land_source": {
                "detections": len(static),
                "share_model_industrial": share([predicted[i] for i in static], "industrial"),
                "share_shown_industrial": share([served.get(records[i]["detection_id"]) for i in static], "industrial"),
            },
            "presumed_vegetation_fire": {
                "detections": len(presumed),
                "share_model_vegetation": share([predicted[i] for i in presumed], "vegetation"),
                "share_shown_vegetation": share([served.get(records[i]["detection_id"]) for i in presumed], "vegetation"),
            },
            "note": ("'model' is the classifier on each detection; 'shown' is the category in the dashboard, where persistent sources are "
                     "decided on all their detections together."),
        }
        checks["summary"].update({
            "nasa_static_source_agreement": checks["C_nasa_static_source_flag"]["static_land_source"]["share_shown_industrial"],
            "nasa_presumed_vegetation_agreement": checks["C_nasa_static_source_flag"]["presumed_vegetation_fire"]["share_shown_vegetation"],
        })
        checks["summary"]["sample_sizes"].update({"C_static": len(static), "C_presumed_vegetation": len(presumed)})

    report = {}
    if os.path.exists(settings.EVALUATION_REPORT_PATH):
        with open(settings.EVALUATION_REPORT_PATH, encoding="utf-8") as f:
            report = json.load(f)
    report[args.key] = checks
    with open(settings.EVALUATION_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(checks["summary"], indent=2))
    print(f"[+] Written to {settings.EVALUATION_REPORT_PATH} ({args.key})")


if __name__ == "__main__":
    main()

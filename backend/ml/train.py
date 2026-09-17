"""Train the source-type classifier on simulated detection streams.

Evaluation is out-of-fold with GroupKFold over *scenes*: every detection of a simulated site is
either entirely in training or entirely in validation, so the model is never scored on a site
it has seen. Results are written to ml/evaluation_report.json under "simulation"; real-data
checks are added by ml/evaluate_real.py.

Usage (from the project root):
    py backend/ml/train.py [--scenes 2600] [--seed 7] [--folds 5]
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import GroupKFold
from xgboost import XGBClassifier

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from app.pipeline.classifier import INDUSTRIAL_INDICES, interpret  # noqa: E402
from app.pipeline.features import FEATURE_COLUMNS  # noqa: E402
from app.pipeline.taxonomy import MODEL_CLASSES, category_for  # noqa: E402
from ml.simulator import FAMILY_WEIGHTS, HARD_FAMILIES, simulate_dataset  # noqa: E402

MODEL_PATH = os.path.join(BACKEND_DIR, "ml", "model_bundle.joblib")
REPORT_PATH = os.path.join(BACKEND_DIR, "ml", "evaluation_report.json")
MODEL_VERSION = "2.2.0"


def make_model(seed: int) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=450,
        max_depth=6,
        learning_rate=0.06,
        subsample=0.85,
        colsample_bytree=0.8,
        min_child_weight=3,
        reg_lambda=1.5,
        objective="multi:softprob",
        eval_metric="mlogloss",
        tree_method="hist",
        random_state=seed,
        n_jobs=-1,
    )


def expected_calibration_error(confidence: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (confidence > lo) & (confidence <= hi)
        if mask.any():
            ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(ece)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenes", type=int, default=2600)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    started = time.time()
    print(f"[+] Simulating {args.scenes} scenes ...", flush=True)
    records = simulate_dataset(args.scenes, seed=args.seed)
    frame = pd.DataFrame(records)
    print(f"[+] {len(frame)} simulated detections from {frame['scene_id'].nunique()} scenes in {time.time() - started:.0f}s", flush=True)

    X = frame[FEATURE_COLUMNS].astype(float)
    y = frame["label"].map({code: i for i, code in enumerate(MODEL_CLASSES)}).to_numpy()
    groups = frame["scene_id"].to_numpy()
    class_counts = Counter(y.tolist())
    weights = np.array([len(y) / (len(MODEL_CLASSES) * class_counts[label]) for label in y])

    oof = np.zeros((len(frame), len(MODEL_CLASSES)))
    for fold, (train_idx, valid_idx) in enumerate(GroupKFold(n_splits=args.folds).split(X, y, groups), start=1):
        model = make_model(args.seed + fold)
        model.fit(X.iloc[train_idx], y[train_idx], sample_weight=weights[train_idx])
        oof[valid_idx] = model.predict_proba(X.iloc[valid_idx])
        fold_acc = accuracy_score(y[valid_idx], oof[valid_idx].argmax(axis=1))
        print(f"    fold {fold}: class accuracy {fold_acc:.3f}", flush=True)

    # Apply the same decision policy used in production (category first, subtype within category).
    decisions = [interpret(oof[i], X.iloc[i].to_dict(), records[i]["_evidence"]) for i in range(len(frame))]
    predicted = np.array([MODEL_CLASSES.index(d["class_code"]) for d in decisions])
    true_category = np.array([category_for(MODEL_CLASSES[label]) for label in y])
    predicted_category = np.array([d["category"] for d in decisions])
    flagged = np.array([d["verification_required"] for d in decisions])
    class_correct = predicted == y
    category_correct = predicted_category == true_category

    precision, recall, f1, support = precision_recall_fscore_support(y, predicted, labels=list(range(len(MODEL_CLASSES))), zero_division=0)
    per_family = {}
    for family in sorted(frame["family"].unique()):
        mask = (frame["family"] == family).to_numpy()
        per_family[family] = {
            "detections": int(mask.sum()),
            "class_accuracy": round(float(class_correct[mask].mean()), 4),
            "category_accuracy": round(float(category_correct[mask].mean()), 4),
            "verification_flag_rate": round(float(flagged[mask].mean()), 4),
            "hard_case": family in HARD_FAMILIES,
        }

    single = (frame["persistence_days"] <= 1).to_numpy()
    confidence = np.array([d["category_confidence"] for d in decisions])
    p_industrial = oof[:, INDUSTRIAL_INDICES].sum(axis=1)

    simulation_report = {
        "method": "Out-of-fold predictions, GroupKFold by simulated scene (no site appears in both training and validation)",
        "scenes": int(frame["scene_id"].nunique()),
        "detections": int(len(frame)),
        "folds": args.folds,
        "category_accuracy": round(float(category_correct.mean()), 4),
        "class_accuracy": round(float(class_correct.mean()), 4),
        "class_macro_f1": round(float(f1_score(y, predicted, average="macro")), 4),
        "category_confusion": {
            "labels": ["industrial", "vegetation"],
            "matrix": confusion_matrix(true_category, predicted_category, labels=["industrial", "vegetation"]).tolist(),
        },
        "class_confusion": {"labels": MODEL_CLASSES, "matrix": confusion_matrix(y, predicted, labels=list(range(len(MODEL_CLASSES)))).tolist()},
        "per_class": {
            MODEL_CLASSES[i]: {"precision": round(float(precision[i]), 4), "recall": round(float(recall[i]), 4), "f1": round(float(f1[i]), 4), "support": int(support[i])}
            for i in range(len(MODEL_CLASSES))
        },
        "by_evidence": {
            "single_day_location": {"detections": int(single.sum()), "category_accuracy": round(float(category_correct[single].mean()), 4) if single.any() else None},
            "recurring_location": {"detections": int((~single).sum()), "category_accuracy": round(float(category_correct[~single].mean()), 4) if (~single).any() else None},
        },
        "verification_policy": {
            "flag_rate": round(float(flagged.mean()), 4),
            "category_accuracy_when_not_flagged": round(float(category_correct[~flagged].mean()), 4) if (~flagged).any() else None,
            "category_accuracy_when_flagged": round(float(category_correct[flagged].mean()), 4) if flagged.any() else None,
        },
        "calibration": {
            "category_expected_calibration_error": round(expected_calibration_error(confidence, category_correct), 4),
            "industrial_probability_brier_score": round(float(np.mean((p_industrial - (true_category == "industrial")) ** 2)), 4),
        },
        "per_family": per_family,
    }

    print("[+] Training final model on all simulated scenes ...", flush=True)
    final_model = make_model(args.seed)
    final_model.fit(X, y, sample_weight=weights)
    gain = final_model.get_booster().get_score(importance_type="gain")
    importance = sorted(((FEATURE_COLUMNS[int(k[1:])] if k.startswith("f") and k[1:].isdigit() else k, v) for k, v in gain.items()), key=lambda kv: -kv[1])

    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    bundle = {
        "model": final_model,
        "feature_columns": FEATURE_COLUMNS,
        "classes": MODEL_CLASSES,
        "version": MODEL_VERSION,
        "trained_at": trained_at,
        "algorithm": "XGBoost gradient-boosted trees (multi:softprob, 450 trees, depth 6), class-balanced weights",
        "training_data": f"{simulation_report['detections']} physics-simulated detections from {simulation_report['scenes']} scenes across {len(FAMILY_WEIGHTS)} scenario families",
    }
    joblib.dump(bundle, MODEL_PATH)

    report = {}
    if os.path.exists(REPORT_PATH):
        try:
            with open(REPORT_PATH, encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, ValueError):
            report = {}
    report.update({
        "model": {k: bundle[k] for k in ("version", "trained_at", "algorithm", "training_data")},
        "important_caveat": ("Accuracy below is measured on held-out simulated scenes. It shows the method works when the physics "
                             "assumptions hold; it is not a field-validated accuracy on real Indian detections. See 'real_data_checks'."),
        "simulation": simulation_report,
        "feature_importance_gain": [{"feature": name, "gain": round(float(value), 2)} for name, value in importance[:20]],
        "scenario_families": {family: {"weight": weight, "hard_case": family in HARD_FAMILIES} for family, weight in FAMILY_WEIGHTS.items()},
    })
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"[+] Category accuracy (industrial vs vegetation): {simulation_report['category_accuracy']:.3f}")
    print(f"[+] Class accuracy: {simulation_report['class_accuracy']:.3f} | macro F1: {simulation_report['class_macro_f1']:.3f}")
    print(f"[+] Single-day locations category accuracy: {simulation_report['by_evidence']['single_day_location']['category_accuracy']}")
    for family, stats in per_family.items():
        marker = " (hard)" if stats["hard_case"] else ""
        print(f"    {family:30s} class {stats['class_accuracy']:.3f}  category {stats['category_accuracy']:.3f}{marker}")
    print(f"[+] Saved {MODEL_PATH} and {REPORT_PATH} in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()

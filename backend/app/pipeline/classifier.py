"""Source-type classifier (gradient-boosted trees) plus the decision policy on top of it.

The model outputs probabilities for five source classes. The primary decision - industrial
versus vegetation fire - uses the summed probability of each group, and the subtype is chosen
within the winning group, so the two levels never contradict each other. Low-evidence results
are flagged for verification instead of being presented as certain.
"""
import os
from typing import Any, Dict, List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd

from .features import FEATURE_COLUMNS
from .geo_context import CONTEXT_CATEGORIES
from .taxonomy import CLASS_LABELS, MODEL_CLASSES

INDUSTRIAL_INDICES = [MODEL_CLASSES.index(c) for c in ("gas_flare", "heavy_industry", "mining_coal_fire")]
VEGETATION_INDICES = [MODEL_CLASSES.index(c) for c in ("wildfire", "agricultural")]
AUTO_ACCEPT_CATEGORY_CONFIDENCE = 0.75
UNMAPPED_SITE_KM = 2.0  # single-day industrial heat farther than this from mapped industry is flagged

FEATURE_DESCRIPTIONS = {
    "frp_log": "fire radiative power",
    "bright_mir": "mid-infrared brightness temperature",
    "bright_tir": "thermal-infrared brightness temperature",
    "delta_t": "MIR minus TIR temperature difference",
    "mir_saturated": "MIR channel saturation",
    "is_night": "night-time overpass",
    "is_modis": "MODIS sensor",
    "pixel_area_km2": "pixel size",
    "persistence_days": "days with detections within 750 m",
    "persistence_ratio": "share of observed days with detections",
    "detections_750m": "detections within 750 m",
    "night_fraction_750m": "share of night-time detections at this location",
    "frp_median_750m_log": "typical FRP at this location",
    "frp_cv_750m": "FRP variability at this location",
    "concurrent_pixels_2km": "simultaneous detections within 2 km",
    "event_cells_5km": "active fire cells within 5 km (3 days)",
    "event_days_5km": "active days within 5 km (3 days)",
    "spread_km_day": "day-to-day movement of fire activity",
    "isolation_other_cells_5km": "other active cells within 5 km",
    "dist_oil_gas_km": "distance to mapped oil & gas feature",
    "dist_heavy_industry_km": "distance to mapped heavy industry",
    "dist_mining_km": "distance to mapped mine",
    "inside_industrial": "inside a mapped industrial polygon",
    "lc_tree": "tree cover fraction",
    "lc_shrub_grass": "shrub/grass fraction",
    "lc_crop": "cropland fraction",
    "lc_built": "built-up fraction",
    "lc_bare": "bare ground fraction",
    "lc_water_wetland": "water/wetland fraction",
    "lc_available": "land-cover availability",
}


def interpret(probs: Sequence[float], features: Dict[str, float], evidence: Dict[str, Any]) -> Dict[str, Any]:
    probs = np.asarray(probs, dtype=float)
    p_industrial = float(probs[INDUSTRIAL_INDICES].sum())
    category = "industrial" if p_industrial >= 0.5 else "vegetation"
    group = INDUSTRIAL_INDICES if category == "industrial" else VEGETATION_INDICES
    best = max(group, key=lambda idx: probs[idx])
    category_confidence = p_industrial if category == "industrial" else 1.0 - p_industrial
    subtype_confidence = float(probs[best] / max(probs[group].sum(), 1e-9))

    reasons = []
    if category_confidence < AUTO_ACCEPT_CATEGORY_CONFIDENCE:
        reasons.append("Industrial-versus-vegetation evidence is mixed")
    single_observation = evidence.get("detections_within_750m", 1) <= 1 and evidence.get("persistence_days", 1) <= 1
    if single_observation and features.get("lc_available", 0.0) < 0.5:
        reasons.append("Single detection with no land-cover data yet")
    if category == "vegetation" and features.get("inside_industrial", 0.0) >= 0.5:
        reasons.append("Classified as a vegetation fire inside a mapped industrial or mining site")
    nearest_mapped_km = min(features.get(f"dist_{c}_km", 50.0) for c in CONTEXT_CATEGORIES)
    if category == "industrial" and evidence.get("persistence_days", 1) <= 1 and nearest_mapped_km > UNMAPPED_SITE_KM:
        reasons.append(f"Single-day heat source with no mapped industry within {UNMAPPED_SITE_KM:.0f} km")

    class_code = MODEL_CLASSES[best]
    return {
        "class_code": class_code,
        "class_label": CLASS_LABELS[class_code],
        "category": category,
        "category_confidence": round(category_confidence, 4),
        "subtype_confidence": round(subtype_confidence, 4),
        "confidence_pct": round(100.0 * category_confidence, 1),
        "probabilities": {code: round(float(p), 4) for code, p in zip(MODEL_CLASSES, probs)},
        "verification_required": bool(reasons),
        "verification_reasons": reasons,
    }


class SourceClassifier:
    def __init__(self, bundle_path: str):
        self.bundle_path = bundle_path
        self.bundle: Optional[Dict[str, Any]] = None
        self.model = None
        self.load_error: Optional[str] = None
        self.load()

    def load(self) -> None:
        """Load the bundle; problems are reported through load_error (shown by /api/health) instead of crashing."""
        self.bundle, self.model, self.load_error = None, None, None
        if not os.path.exists(self.bundle_path):
            return
        try:
            bundle = joblib.load(self.bundle_path)
        except Exception as exc:  # e.g. written by an incompatible XGBoost or scikit-learn version
            self.load_error = f"cannot be loaded: {type(exc).__name__}"
            return
        if bundle.get("feature_columns") != FEATURE_COLUMNS or bundle.get("classes") != MODEL_CLASSES:
            self.load_error = "trained for a different feature set"
            return
        self.bundle, self.model = bundle, bundle["model"]

    @property
    def available(self) -> bool:
        return self.model is not None

    @property
    def metadata(self) -> Dict[str, Any]:
        if not self.bundle:
            return {"available": False}
        return {
            "available": True,
            "version": self.bundle.get("version"),
            "trained_at": self.bundle.get("trained_at"),
            "algorithm": self.bundle.get("algorithm"),
            "training_data": self.bundle.get("training_data"),
        }

    def _frame(self, rows: Sequence[Dict[str, float]]) -> pd.DataFrame:
        return pd.DataFrame([{name: row.get(name, np.nan) for name in FEATURE_COLUMNS} for row in rows], columns=FEATURE_COLUMNS).astype(float)

    def predict_proba(self, rows: Sequence[Dict[str, float]]) -> np.ndarray:
        if not self.available:
            raise RuntimeError("Classifier model is not trained. Run: py backend/ml/train.py")
        if not rows:
            return np.zeros((0, len(MODEL_CLASSES)))
        return self.model.predict_proba(self._frame(rows))

    def top_contributions(self, rows: Sequence[Dict[str, float]], class_codes: Sequence[str], top: int = 5) -> List[List[Dict[str, Any]]]:
        """Per-detection feature contributions (XGBoost TreeSHAP) towards the reported class."""
        if not self.available or not rows:
            return [[] for _ in rows]
        import xgboost as xgb

        frame = self._frame(rows)
        contribs = self.model.get_booster().predict(xgb.DMatrix(frame, missing=np.nan), pred_contribs=True)
        out = []
        for i, code in enumerate(class_codes):
            class_index = MODEL_CLASSES.index(code) if code in MODEL_CLASSES else 0
            values = contribs[i, class_index, :-1]
            order = np.argsort(-np.abs(values))[:top]
            out.append([
                {
                    "feature": FEATURE_COLUMNS[j],
                    "description": FEATURE_DESCRIPTIONS.get(FEATURE_COLUMNS[j], FEATURE_COLUMNS[j]),
                    "value": None if np.isnan(frame.iat[i, j]) else round(float(frame.iat[i, j]), 3),
                    "contribution": round(float(values[j]), 3),
                    "direction": "supports" if values[j] > 0 else "against",
                }
                for j in order
            ])
        return out

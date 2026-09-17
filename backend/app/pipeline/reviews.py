"""Analyst reviews: labels from people, stored next to - never instead of - the model's output.

A review labels one detection, or its whole location: the persistent source or the fire event the detection belongs
to. Reviews are append-only and the newest review is the current label. Together they are the start of a real
validation set: the dashboard reports how often analysts agree with the model, and reviewed detections export with
their features and label provenance as training rows for the next model.
"""
import csv
import io
import json
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, or_

from ..db.database import SessionLocal
from ..db.models import DetectionModel, DetectionReviewModel, IncidentModel, utcnow_iso
from .features import FEATURE_COLUMNS
from .locations import LOCATION_KINDS, group_key
from .taxonomy import CLASS_LABELS, REVIEW_EVIDENCE, REVIEW_LABELS

OPEN_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")
SCOPES = ("detection", "location")
SEVERITY_RANK = {"NORMAL": 0, "HIGH": 1, "CRITICAL": 2}
AGREEMENT_NOTE = ("Agreement is counted only on detections an analyst has labelled - mostly the uncertain ones from the review "
                  "queue - so it is not an accuracy estimate for all detections.")
QUEUE_KEYS = ("detection_id", "latitude", "longitude", "acq_datetime", "frp", "daynight", "satellite", "class_code", "class_label",
              "category", "confidence_pct", "severity", "place", "facility_name", "data_source", "source_id", "event_id")
EXPORT_COLUMNS = ["detection_id", "acq_datetime", "latitude", "longitude", "satellite", "instrument", "daynight", "frp", "bright_mir",
                  "bright_tir", "confidence", "data_source", "model_class_code", "model_category", "model_confidence_pct", "model_version",
                  "label", "label_category", "agrees_with_model", "label_source", "scope", "location", "reviewer", "reviewed_at",
                  "evidence", "note"]


class ReviewError(ValueError):
    """An invalid review request."""


def location_info(detection: Dict[str, Any], detections: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    key = group_key(detection)
    return {"group_key": key, "kind": LOCATION_KINDS[key[0]], "detections": max(1, sum(1 for d in detections if group_key(d) == key))}


def _all_reviews() -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        return [row.to_dict() for row in db.query(DetectionReviewModel).order_by(DetectionReviewModel.id).all()]


def current_labels(detections: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The newest review that applies to each detection: its own, or a review of its whole location."""
    rows = _all_reviews()
    if not rows:
        return {}
    by_detection: Dict[str, Dict[str, Any]] = {}
    by_location: Dict[str, Dict[str, Any]] = {}
    for review in rows:  # oldest first, so a newer review replaces an older one
        by_detection[review["detection_id"]] = review
        if review["scope"] == "location" and review["group_key"]:
            by_location[review["group_key"]] = review
    labels = {}
    for d in detections:
        candidates = [r for r in (by_detection.get(d["detection_id"]), by_location.get(group_key(d))) if r]
        if candidates:
            labels[d["detection_id"]] = max(candidates, key=lambda r: r["id"])
    return labels


def reviews_for(detection: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every review that applies to a detection, newest first."""
    with SessionLocal() as db:
        rows = db.query(DetectionReviewModel).filter(or_(
            DetectionReviewModel.detection_id == detection["detection_id"],
            and_(DetectionReviewModel.scope == "location", DetectionReviewModel.group_key == group_key(detection)),
        )).order_by(DetectionReviewModel.id.desc()).all()
        return [row.to_dict() for row in rows]


def list_reviews(limit: int = 200) -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        return [row.to_dict() for row in db.query(DetectionReviewModel).order_by(DetectionReviewModel.id.desc()).limit(limit).all()]


def create_review(detection_id: str, label: str, scope: str, reviewer: str, note: Optional[str] = None,
                  evidence: Sequence[str] = ()) -> Tuple[Optional[Dict[str, Any]], List[int]]:
    """Store a review. Returns the review and the ids of open incidents that received a history note, or (None, [])
    when the detection does not exist."""
    if label not in REVIEW_LABELS:
        raise ReviewError(f"label must be one of: {', '.join(REVIEW_LABELS)}")
    if scope not in SCOPES:
        raise ReviewError("scope must be 'detection' or 'location'")
    unknown = [item for item in evidence if item not in REVIEW_EVIDENCE]
    if unknown:
        raise ReviewError(f"unknown evidence: {', '.join(unknown)} (allowed: {', '.join(REVIEW_EVIDENCE)})")
    with SessionLocal() as db:
        row = db.query(DetectionModel).filter(DetectionModel.detection_id == detection_id).first()
        if row is None:
            return None, []
        if row.predicted_class is None:
            raise ReviewError("this detection has not been analysed yet")
        detection = row.to_summary()
        classification = json.loads(row.analysis_json or "{}").get("classification", {})
        key = group_key(detection)
        label_category = REVIEW_LABELS[label]["category"]
        now = utcnow_iso()
        review = DetectionReviewModel(
            detection_id=detection_id, scope=scope, group_key=key, label=label, label_category=label_category,
            model_class_code=detection["class_code"], model_category=detection["category"],
            model_confidence_pct=detection["confidence_pct"], model_version=classification.get("model_version"),
            agrees_with_model=(label_category == detection["category"]) if label_category else None,
            evidence_json=json.dumps(list(dict.fromkeys(evidence))), note=(note or "").strip() or None,
            reviewer=reviewer, created_at=now,
        )
        db.add(review)
        # Open incidents on this detection (or on the reviewed location) note the label, so triage sees it.
        note_text = f"Analyst review: {REVIEW_LABELS[label]['label']} (model: {CLASS_LABELS.get(detection['class_code'], detection['class_code'])})"
        noted = []
        for incident in db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN_INCIDENT_STATUSES)).all():
            same_location = scope == "location" and key[0] in "SE" and incident.group_key.endswith(f":{key}")
            if incident.detection_id == detection_id or same_location:
                history = json.loads(incident.history_json or "[]")
                history.append({"at": now, "by": reviewer, "status": incident.status, "note": note_text})
                incident.history_json, incident.updated_at, incident.updated_by = json.dumps(history), now, reviewer
                noted.append(incident.id)
        db.commit()
        return review.to_dict(), noted


def review_queue(detections: Sequence[Dict[str, Any]], limit: int = 100) -> Dict[str, Any]:
    """Locations with detections flagged for verification that no analyst has labelled yet, most urgent first."""
    sizes = Counter(group_key(d) for d in detections)
    alerting = {group_key(d) for d in detections if d["severity"] in ("HIGH", "CRITICAL")}
    groups: Dict[str, Dict[str, Any]] = {}
    for d in detections:
        if not d["verification_required"] or d.get("review_label"):
            continue
        key = group_key(d)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {"group_key": key, "kind": LOCATION_KINDS[key[0]], "flagged_detections": 0, "detections": sizes[key],
                                   "first_seen": d["acq_datetime"], "last_seen": d["acq_datetime"], "max_frp": d["frp"],
                                   "is_drill": False, "alerting": key in alerting, "representative": d}
        group["flagged_detections"] += 1
        group["first_seen"] = min(group["first_seen"], d["acq_datetime"])
        group["last_seen"] = max(group["last_seen"], d["acq_datetime"])
        group["max_frp"] = max(group["max_frp"], d["frp"])
        group["is_drill"] = group["is_drill"] or d["data_source"] == "drill"
        rep = group["representative"]
        if (SEVERITY_RANK[d["severity"]], d["acq_datetime"]) > (SEVERITY_RANK[rep["severity"]], rep["acq_datetime"]):
            group["representative"] = d
    ordered = sorted(groups.values(), key=lambda g: (-SEVERITY_RANK[g["representative"]["severity"]],
                                                     g["representative"]["confidence_pct"] or 0.0, -g["flagged_detections"]))[:limit]
    ids = [g["representative"]["detection_id"] for g in ordered]
    reasons: Dict[str, List[str]] = {}
    with SessionLocal() as db:
        for start in range(0, len(ids), 500):
            query = db.query(DetectionModel.detection_id, DetectionModel.analysis_json).filter(DetectionModel.detection_id.in_(ids[start:start + 500]))
            for detection_id, analysis_json in query:
                reasons[detection_id] = json.loads(analysis_json or "{}").get("classification", {}).get("verification_reasons", [])
    items = []
    for group in ordered:
        rep = group["representative"]
        items.append({**{k: v for k, v in group.items() if k != "representative"},
                      "detection": {k: rep.get(k) for k in QUEUE_KEYS}, "reasons": reasons.get(rep["detection_id"], [])})
    return {"locations": len(groups), "with_alerts": sum(1 for g in groups.values() if g["alerting"]),
            "flagged_detections": sum(g["flagged_detections"] for g in groups.values()), "items": items}


def _share(agree: int, compared: int) -> Optional[float]:
    return round(agree / compared, 4) if compared else None


def review_stats(detections: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows = _all_reviews()
    labelled = [d for d in detections if d.get("review_label")]
    compared = [d for d in labelled if d.get("review_category")]
    agree = sum(1 for d in compared if d["review_category"] == d["category"])
    locations: Dict[str, Dict[str, Any]] = {}
    for d in labelled:
        locations.setdefault(group_key(d), d)
    located = [d for d in locations.values() if d.get("review_category")]
    located_agree = sum(1 for d in located if d["review_category"] == d["category"])
    confusion = Counter((d["category"], d.get("review_category") or d["review_label"]) for d in labelled)
    return {
        "reviews": len(rows),
        "reviewers": dict(Counter(r["reviewer"] for r in rows)),
        "last_review_at": rows[-1]["created_at"] if rows else None,
        "labelled_detections": len(labelled),
        "labelled_locations": len(locations),
        "detection_agreement": {"agree": agree, "compared": len(compared), "share": _share(agree, len(compared))},
        "location_agreement": {"agree": located_agree, "compared": len(located), "share": _share(located_agree, len(located))},
        "labels": dict(Counter(d["review_label"] for d in labelled)),
        "confusion": [{"model_category": model, "analyst": analyst, "detections": n} for (model, analyst), n in sorted(confusion.items())],
        "pending_flagged_detections": sum(1 for d in detections if d["verification_required"] and not d.get("review_label")),
        "note": AGREEMENT_NOTE,
    }


def export_csv(detections: Sequence[Dict[str, Any]]) -> str:
    """Reviewed detections as training rows: the FIRMS record, the model's output, the analyst's label with its
    provenance, and the 30 model features."""
    labels = current_labels(detections)
    by_id = {d["detection_id"]: d for d in detections if d["detection_id"] in labels}
    ids = list(by_id)
    analyses: Dict[str, Dict[str, Any]] = {}
    with SessionLocal() as db:
        for start in range(0, len(ids), 500):
            query = db.query(DetectionModel.detection_id, DetectionModel.analysis_json).filter(DetectionModel.detection_id.in_(ids[start:start + 500]))
            for detection_id, analysis_json in query:
                analyses[detection_id] = json.loads(analysis_json or "{}")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS + FEATURE_COLUMNS)
    for detection_id, d in sorted(by_id.items(), key=lambda item: item[1]["acq_datetime"]):
        review = labels[detection_id]
        analysis = analyses.get(detection_id, {})
        features = analysis.get("features", {})
        values = {key: d.get(key) for key in EXPORT_COLUMNS[:12]}
        values.update({
            "model_class_code": d["class_code"], "model_category": d["category"], "model_confidence_pct": d["confidence_pct"],
            "model_version": analysis.get("classification", {}).get("model_version"),
            "label": review["label"], "label_category": review["label_category"],
            "agrees_with_model": None if review["label_category"] is None else review["label_category"] == d["category"],
            "label_source": "analyst_review", "scope": review["scope"], "location": group_key(d), "reviewer": review["reviewer"],
            "reviewed_at": review["created_at"], "evidence": ";".join(review["evidence"]), "note": review["note"],
        })
        writer.writerow(["" if values[c] is None else values[c] for c in EXPORT_COLUMNS]
                        + ["" if features.get(name) is None else features[name] for name in FEATURE_COLUMNS])
    return output.getvalue()

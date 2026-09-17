"""From raw detections to decisions: how much of the satellite feed needs a person's attention.

NASA FIRMS reports every hot pixel. Grouping pixels into locations, classifying them, keeping known persistent sources
quiet unless they deviate from their own baseline, and sending uncertain cases to review turns the feed into a short
list. Every number here is counted from the stored analysis, not estimated.
"""
from typing import Any, Dict, Sequence

from .locations import group_key

DEFINITION = ("A location is a persistent source (a 750 m spot active on 2 or more days) or a fire event (other detections "
              "within 3 km with no gap longer than 3 days). Attention means an open incident, or a location without an alert "
              "whose detections are flagged for verification and not yet labelled by an analyst.")


def alert_funnel(detections: Sequence[Dict[str, Any]], sources: Sequence[Dict[str, Any]], open_incidents: int) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    for d in detections:
        group = groups.setdefault(group_key(d), {"alert": False, "pending_review": False, "category": d["category"]})
        if d["severity"] in ("HIGH", "CRITICAL"):
            group["alert"] = True
        if d["verification_required"] and not d.get("review_label"):
            group["pending_review"] = True
    alerting = sum(1 for g in groups.values() if g["alert"])
    review = sum(1 for g in groups.values() if g["pending_review"] and not g["alert"])
    routine = [g for g in groups.values() if not g["alert"] and not g["pending_review"]]
    attention = open_incidents + review
    return {
        "detections": len(detections),
        "locations": len(groups),
        "persistent_sources": len(sources),
        "fire_events": sum(1 for key in groups if key.startswith("E")),
        "routine_locations": len(routine),
        "routine_industrial_locations": sum(1 for g in routine if g["category"] == "industrial"),
        "routine_vegetation_locations": sum(1 for g in routine if g["category"] == "vegetation"),
        "alerting_locations": alerting,
        "review_locations": review,
        "open_incidents": open_incidents,
        "needing_attention": attention,
        "attention_share": round(attention / len(detections), 4) if detections else None,
        "definition": DEFINITION,
    }

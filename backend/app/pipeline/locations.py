"""Locations: the unit the review queue lists and the alert funnel counts.

A detection belongs to its persistent source (a 750 m spot active on 2 or more days), else to its fire event, else it
stands alone. Nothing here imports the app configuration or the database, so modules of plain definitions (the focus
regions, which scripts import before they point the app at a database) can use it.
"""
from typing import Any, Dict

LOCATION_KINDS = {"S": "persistent_source", "E": "fire_event", "D": "single_detection"}


def group_key(detection: Dict[str, Any]) -> str:
    """The location a detection belongs to: its persistent source (S), its fire event (E), or itself (D)."""
    if detection.get("source_id") is not None:
        return f"S{detection['source_id']}"
    if detection.get("event_id") is not None:
        return f"E{detection['event_id']}"
    return f"D{detection['detection_id']}"

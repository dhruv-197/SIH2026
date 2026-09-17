"""Focus regions: parts of India where one kind of heat source dominates, or where industry meets forest.

Monitoring covers the whole country. In these regions the separation of industrial heat from vegetation fires is easy
to see and to check: farm belts and forests supply the fires the classifier must not call industrial, industrial belts
and coalfields supply the persistent heat it must, and the power-and-forest belt supplies fires next to plants. The
dashboard summarises every region, the map zooms to them, and the archive demonstration week is cut to them.
"""
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

from .locations import group_key

OPEN_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")

# bbox: west, south, east, north (degrees). dominant: what the region is chosen to show.
FOCUS_REGIONS: List[Dict[str, Any]] = [
    {"id": "gujarat_industrial", "name": "Gujarat industrial belt", "bbox": [68.0, 20.0, 74.6, 24.8], "dominant": "industrial",
     "description": "Refineries, petrochemical complexes, LNG terminals and steel works at Jamnagar, Vadodara-Ankleshwar, Hazira and Kutch"},
    {"id": "punjab_haryana_farms", "name": "Punjab-Haryana farm belt", "bbox": [73.8, 27.6, 77.5, 32.6], "dominant": "vegetation",
     "description": "Wheat (April-May) and paddy (October-November) residue burning, the largest source of false industrial alarms"},
    {"id": "uttarakhand_forests", "name": "Uttarakhand forests", "bbox": [77.55, 28.7, 81.1, 31.5], "dominant": "vegetation",
     "description": "Pine and broadleaf forests with a spring fire season"},
    {"id": "singrauli_korba", "name": "Singrauli-Korba power and forest belt", "bbox": [82.0, 21.8, 83.6, 24.5], "dominant": "mixed",
     "description": "Coal-fired power stations and open-cast mines (Vindhyachal, Rihand, Korba, Sipat) surrounded by forest"},
    {"id": "talcher_angul", "name": "Talcher-Angul industrial belt", "bbox": [84.8, 20.6, 85.5, 21.3], "dominant": "industrial",
     "description": "The Talcher coalfield, the Angul aluminium smelter and steel plant, and the Kaniha and Talcher power stations"},
    {"id": "jharia_raniganj", "name": "Jharia-Raniganj coalfields", "bbox": [85.9, 23.4, 87.45, 24.0], "dominant": "industrial",
     "description": "Underground coal fires of Jharia and the steel plants of Bokaro, Asansol and Durgapur"},
]


def in_region(region: Dict[str, Any], lat: float, lon: float) -> bool:
    west, south, east, north = region["bbox"]
    return south <= lat <= north and west <= lon <= east


def region_for(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    return next((region for region in FOCUS_REGIONS if in_region(region, lat, lon)), None)


def region_summaries(detections: Sequence[Dict[str, Any]], sources: Sequence[Dict[str, Any]], incidents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Locations to review are counted as in the alert funnel: a location with an alert is on the incident list instead.
    alerting = {group_key(d) for d in detections if d["severity"] in ("HIGH", "CRITICAL")}
    out = []
    for region in FOCUS_REGIONS:
        inside = [d for d in detections if in_region(region, d["latitude"], d["longitude"])]
        pending = [d for d in inside if d["verification_required"] and not d.get("review_label")]
        out.append({
            **region,
            "detections": len(inside),
            "industrial": sum(1 for d in inside if d["category"] == "industrial"),
            "vegetation": sum(1 for d in inside if d["category"] == "vegetation"),
            "classes": dict(Counter(d["class_code"] for d in inside)),
            "persistent_sources": sum(1 for s in sources if in_region(region, s["latitude"], s["longitude"])),
            "open_incidents": sum(1 for i in incidents if i["status"] in OPEN_INCIDENT_STATUSES and i.get("latitude") is not None
                                  and in_region(region, i["latitude"], i["longitude"])),
            "pending_review": len(pending),
            "review_locations": len({group_key(d) for d in pending} - alerting),
        })
    return out

"""Rule-based query assistant. Answers are computed from stored detections - no language model and
no invented figures. Every answer says which data it was computed from."""
import re
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db.database import SessionLocal
from ..db.models import IncidentModel
from ..pipeline.funnel import alert_funnel
from ..pipeline.reviews import review_stats
from ..pipeline.service import service
from ..pipeline.taxonomy import CLASS_LABELS, INDUSTRIAL_ACCIDENT

router = APIRouter(prefix="/assistant", tags=["Query assistant"])
OPEN = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")

CLASS_KEYWORDS = [
    (INDUSTRIAL_ACCIDENT, r"explosion|accident|excursion|blowout"),
    ("gas_flare", r"flare|flaring|refiner|oil|gas|lng|petro"),
    ("mining_coal_fire", r"mine|mining|coal|colliery|jharia|seam"),
    ("heavy_industry", r"steel|cement|power plant|thermal power|kiln|smelter|heavy"),
    ("wildfire", r"wildfire|forest|jungle"),
    ("agricultural", r"crop|stubble|agri|farm|paddy|residue|biomass"),
]
STOPWORDS = {"the", "and", "plant", "works", "refinery", "complex", "steel", "power", "thermal", "super", "limited", "ltd", "coal", "mine", "mines", "basin", "open", "cast", "field", "coalfield", "terminal", "hub", "india", "status", "what", "about"}

SUGGESTIONS = [
    "Give me an overview",
    "What needs attention?",
    "Which alerts are open?",
    "Show gas flares",
    "Status of Jamnagar",
    "How does the classification work?",
]


class Query(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


def _grounding() -> str:
    window = service.snapshot["window"]
    n = len(service.snapshot["detections"])
    return f"Computed from {n} stored detections ({window['start']} to {window['end']})." if window else "No detections are stored yet."


def _match_facility(question: str) -> Optional[Dict[str, Any]]:
    words = set(re.findall(r"[a-z]{4,}", question.lower())) - STOPWORDS
    best, best_score = None, 0
    for fac in service.facilities:
        tokens = set(re.findall(r"[a-z]{4,}", f"{fac['name']} {fac.get('operator') or ''}".lower())) - STOPWORDS
        score = len(words & tokens)
        if score > best_score:
            best, best_score = fac, score
    return best


def _open_incidents() -> List[Dict[str, Any]]:
    with SessionLocal() as db:
        return [row.to_dict() for row in db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN)).all()]


@router.post("/query")
def query(q: Query) -> Dict[str, Any]:
    text = q.question.lower()
    detections = service.snapshot["detections"]
    sources = service.snapshot["sources"]

    if re.search(r"\bhow\b.*(classif|work|decide|model)|method", text):
        meta = service.classifier.metadata
        answer = (
            "Each FIRMS detection is described by 30 measured features: radiometry (FRP, brightness temperatures, day/night), "
            "recurrence at the same 750 m location across the observation window, the pattern of surrounding fire activity, "
            "distance to mapped industrial and mining features from OpenStreetMap, and ESA WorldCover land cover in the pixel footprint. "
            f"A gradient-boosted tree model ({meta.get('version', 'not trained')}) trained on physics-based simulated detection streams "
            "estimates the probability of each source type. The industrial-versus-vegetation decision uses the summed probabilities, "
            "locations seen on several days are classified as one persistent source, and uncertain results are flagged for verification. "
            "Alerts are raised when FRP jumps far above a source's own history (suspected industrial accident), when a large cluster "
            "of new heat appears at a mapped plant, or when a vegetation fire burns near critical infrastructure - critical when its front "
            "is moving towards the plant. Every alert carries reason codes and the version of the alert policy that raised it. Open "
            "incidents are checked against Sentinel-2 imagery for shortwave-infrared hot spots and burn scars, and uncertain results go to "
            "a review queue where analysts' labels are stored next to the model's output."
        )
        return {"intent": "methodology", "answer": answer, "facts": {"model": meta}, "grounding": "Describes the deployed pipeline.", "suggestions": SUGGESTIONS}

    if re.search(r"attention|workload|funnel|review queue|to review|need a person|labell?ed", text):
        funnel = alert_funnel(detections, sources, len(_open_incidents()))
        labels = review_stats(detections)
        agreement = labels["location_agreement"]["share"]
        answer = (
            f"{funnel['detections']} raw detections form {funnel['locations']} locations, and {funnel['routine_locations']} of them need no action. "
            f"{funnel['needing_attention']} items need a person: {funnel['open_incidents']} open incident(s) and {funnel['review_locations']} location(s) "
            f"with uncertain evidence in the review queue. Analysts have labelled {labels['labelled_detections']} detection(s)"
            + (f"; the model agrees at {agreement:.0%} of labelled locations." if agreement is not None else ".")
        )
        return {"intent": "attention", "answer": answer, "facts": {"funnel": funnel, "labelled_detections": labels["labelled_detections"]}, "grounding": _grounding(), "suggestions": SUGGESTIONS}

    if re.search(r"alert|incident|critical|warning|emergenc", text):
        incidents = _open_incidents()
        by_severity = Counter(i["severity"] for i in incidents)
        lines = [f"{i['severity']}: {i['title']} (status {i['status']})" for i in sorted(incidents, key=lambda i: i["severity"] != "CRITICAL")[:5]]
        answer = f"{len(incidents)} open incident(s): {by_severity.get('CRITICAL', 0)} critical, {by_severity.get('HIGH', 0)} high." + (" Most urgent: " + "; ".join(lines) if lines else "")
        return {"intent": "incidents", "answer": answer, "facts": {"open": len(incidents), "by_severity": dict(by_severity)}, "grounding": _grounding(), "suggestions": SUGGESTIONS}

    facility = _match_facility(text)
    if facility:
        dets = [d for d in detections if d["facility_id"] == facility["id"]]
        fac_sources = [s for s in sources if s["facility_id"] == facility["id"]]
        if dets:
            classes = Counter(d["class_label"] for d in dets).most_common(2)
            frps = sorted(d["frp"] for d in dets)
            answer = (f"{facility['name']}: {len(dets)} detection(s) on {len({d['acq_date'] for d in dets})} day(s), last at {max(d['acq_datetime'] for d in dets)}. "
                      f"Median FRP {frps[len(frps) // 2]:.1f} MW, max {frps[-1]:.1f} MW. Classified mostly as {classes[0][0]}. "
                      f"{len(fac_sources)} persistent source(s) associated.")
        else:
            answer = f"{facility['name']}: no FIRMS detections within the facility area in the current observation window."
        return {"intent": "facility", "answer": answer, "facts": {"facility_id": facility["id"], "detections": len(dets), "persistent_sources": len(fac_sources)}, "grounding": _grounding(), "suggestions": SUGGESTIONS}

    for code, pattern in CLASS_KEYWORDS:
        if re.search(pattern, text):
            dets = [d for d in detections if d["class_code"] == code]
            cls_sources = sorted((s for s in sources if s["class_code"] == code), key=lambda s: (-s["active_days"], -s["frp_median"]))
            flagged = sum(1 for d in dets if d["verification_required"])
            top = [f"{s['latitude']:.3f}, {s['longitude']:.3f} ({s['active_days']} days, median {s['frp_median']:.1f} MW)" for s in cls_sources[:3]]
            answer = f"{CLASS_LABELS[code]}: {len(dets)} detection(s), {len(cls_sources)} persistent source(s); {flagged} need verification."
            if top:
                answer += " Most persistent: " + "; ".join(top) + "."
            return {"intent": "class", "answer": answer, "facts": {"class_code": code, "detections": len(dets), "persistent_sources": len(cls_sources)}, "grounding": _grounding(), "suggestions": SUGGESTIONS}

    industrial = sum(1 for d in detections if d["category"] == "industrial")
    classes = Counter(d["class_label"] for d in detections).most_common(3)
    incidents = _open_incidents()
    answer = (f"{len(detections)} detections: {industrial} industrial/extractive and {len(detections) - industrial} vegetation fires, "
              f"{len(sources)} persistent sources. Largest groups: " + ", ".join(f"{label} ({n})" for label, n in classes) +
              f". {len(incidents)} incident(s) open.") if detections else "No detections are stored yet. Run a FIRMS sync first."
    return {"intent": "overview", "answer": answer, "facts": {"detections": len(detections), "industrial": industrial, "open_incidents": len(incidents)}, "grounding": _grounding(), "suggestions": SUGGESTIONS}

"""Analysis service: ingestion, classification, persistent sources, severity, incidents, what-if
analysis and the in-memory snapshot that the API reads from."""
import asyncio
import hashlib
import json
import logging
import math
import os
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import Point, shape
from shapely.ops import nearest_points

from ..config import settings
from ..db.database import SessionLocal, init_db
from ..db.models import DetectionModel, DetectionReviewModel, FacilityModel, IncidentModel, IngestionRunModel, ThermalSourceModel, utcnow_iso
from . import emissions, gis_store, imagery, normalize, notifications, reviews, weather
from .approach import fire_approach
from .classifier import SourceClassifier, interpret
from .features import FEATURE_COLUMNS, build_feature_table
from .geo_context import CONTEXT_CATEGORIES, ContextFeature, GeoContext, feature_name, haversine_km, load_boundary, load_osm_features
from .landcover import LandCoverStore, describe as describe_landcover
from .settings_store import load_settings, severity_config
from .severity import apply_fire_approach, assess, policy_info, robust_baseline
from .sources import cluster_events, cluster_persistent_sources, overpass_clusters, summarize_source
from .taxonomy import CATEGORY_LABELS, CLASS_COLORS, CLASS_LABELS, INDUSTRIAL_ACCIDENT

logger = logging.getLogger("geothermal.service")

FACILITY_CATEGORY = {
    "oil_refinery": "oil_gas",
    "petrochemical": "oil_gas",
    "lng_terminal": "oil_gas",
    "chemical_plant": "heavy_industry",
    "steel_plant": "heavy_industry",
    "thermal_power": "heavy_industry",
    "cement_kiln": "heavy_industry",
    "coal_mining": "mining",
}
FACILITY_ASSOCIATION_KM = 2.0
OPEN_INCIDENT_STATUSES = ("OPEN", "ACKNOWLEDGED", "INVESTIGATING")


def _stable_id(text: str) -> int:
    return int(hashlib.sha1(text.encode()).hexdigest()[:7], 16)


def _json_default(value):
    if isinstance(value, (np.floating,)):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not serialisable: {type(value)}")


def _clean_number(value: float, digits: int = 3):
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else round(value, digits)


def evidence_statements(decision: Dict[str, Any], evidence: Dict[str, Any], landcover_entry: Optional[Dict], facility: Optional[Dict]) -> List[str]:
    statements = []
    days, window = evidence["persistence_days"], evidence["observation_days"]
    if days >= 2:
        statements.append(f"Recurring location: detections on {days} of {window} observed days within 750 m.")
    else:
        statements.append(f"Detected on a single day at this location in the {window}-day observation window.")
    count, night = evidence["detections_within_750m"], evidence["night_fraction_within_750m"]
    if count >= 3:
        statements.append(f"{night:.0%} of the {count} detections here were at night (industrial heat is mostly detected at night; crop fires mostly by day).")
    inside = evidence.get("inside_feature")
    nearest = evidence.get("nearest_industrial_feature")
    if inside:
        label = inside["subtype"].replace("_", " ")
        name = f" '{inside['name']}'" if inside.get("name") else ""
        statements.append(f"Inside mapped {label}{name} ({inside['feature_id']}).")
    elif nearest:
        label = nearest.get("name") or nearest["subtype"].replace("_", " ")
        statements.append(f"Nearest mapped industrial or mining feature: {label} at {nearest['distance_km']:.1f} km.")
    else:
        statements.append("No mapped industrial or mining feature within 50 km.")
    if facility:
        statements.append(f"Within {facility['distance_km']:.1f} km of catalog facility {facility['name']}.")
    if landcover_entry and landcover_entry.get("status") == "ok":
        names = {"tree": "tree cover", "shrub_grass": "shrub/grass", "crop": "cropland", "built": "built-up", "bare": "bare ground", "water_wetland": "water/wetland"}
        top = sorted(((v, k) for k, v in landcover_entry["fractions"].items() if k in names and v >= 0.05), reverse=True)[:3]
        if top:
            statements.append("ESA WorldCover in the 375 m footprint: " + ", ".join(f"{v:.0%} {names[k]}" for v, k in top) + ".")
    else:
        statements.append("Land cover has not been fetched for this location yet.")
    if evidence["spread_km_per_day"] >= 1.0 and evidence["active_cells_within_5km_3d"] >= 3:
        statements.append(f"Nearby fire activity shifted {evidence['spread_km_per_day']:.1f} km/day across {evidence['active_cells_within_5km_3d']} active cells.")
    cluster = evidence.get("overpass_cluster")
    if cluster and cluster["detections"] >= 2:
        statements.append(f"{cluster['detections']} detections totalling {cluster['frp_mw']:.0f} MW within 2 km in the same overpass.")
    elif evidence["concurrent_pixels_within_2km"] >= 4:
        statements.append(f"{evidence['concurrent_pixels_within_2km']} detections within 2 km in the same overpass.")
    return statements


def describe_place(analysis: Dict[str, Any]) -> Optional[str]:
    """Short place description for a detection: catalog facility, mapped feature, or land cover."""
    facility = analysis.get("facility")
    evidence = analysis.get("evidence", {})
    inside = evidence.get("inside_feature")
    nearest = evidence.get("nearest_industrial_feature")
    landcover = analysis.get("landcover", {})
    if facility:
        return facility["name"]
    if inside:
        return inside.get("name") or inside["subtype"].replace("_", " ").title()
    if nearest and nearest["distance_km"] <= 5:
        return f"{nearest['distance_km']:.1f} km from {nearest.get('name') or nearest['subtype'].replace('_', ' ')}"
    if landcover.get("available"):
        return f"{landcover['dominant_class']} area"
    return None


class PipelineService:
    def __init__(self):
        self.classifier = SourceClassifier(settings.MODEL_BUNDLE_PATH)
        self.landcover = LandCoverStore(SessionLocal)
        self.geo = GeoContext([])
        self.facilities: List[Dict[str, Any]] = []
        self._facility_geoms: List[Any] = []
        self._facility_cache: Dict[Tuple[float, float], Optional[Dict]] = {}
        self.osm_feature_count = 0
        self._lock = threading.Lock()
        self.snapshot: Dict[str, Any] = {"detections": [], "sources": [], "window": None, "generated_at": None}
        self.analysis_summary: Dict[str, Any] = {}
        self.gis_store_status: Dict[str, Any] = {}
        self.last_review_at: Optional[str] = None
        self._tasks: set = set()
        self.started = False

    # ------------------------------------------------------------------ startup / reference data
    def startup(self) -> None:
        init_db()
        self.load_reference_data()
        self.landcover.load()
        self._build_snapshot()
        if self.snapshot["detections"] and not os.path.exists(settings.GIS_STORE_PATH):
            self.refresh_gis_store()
        self.started = True

    def load_reference_data(self) -> None:
        osm_features = load_osm_features(settings.OSM_FEATURES_PATH)
        self.osm_feature_count = len(osm_features)
        self._sync_facilities()
        catalog_features = []
        for fac in self.facilities:
            if not fac["osm_element_id"]:
                catalog_features.append(ContextFeature(
                    feature_id=f"facility:{fac['id']}", name=fac["name"], category=FACILITY_CATEGORY.get(fac["facility_type"], "heavy_industry"),
                    subtype=fac["facility_type"], geometry=Point(fac["longitude"], fac["latitude"]), source="catalog"))
        self.geo = GeoContext(osm_features + catalog_features, load_boundary(settings.INDIA_BOUNDARY_PATH))
        self._facility_cache.clear()

    def _sync_facilities(self) -> None:
        try:
            with open(settings.FACILITY_CATALOG_PATH, encoding="utf-8") as f:
                catalog = json.load(f)["facilities"]
        except FileNotFoundError:
            catalog = []
        with SessionLocal() as db:
            for fac in catalog:
                db.merge(FacilityModel(
                    id=fac["id"], name=fac["name"], facility_type=fac["facility_type"], sector=fac["sector"],
                    operator=fac.get("operator"), state=fac.get("state"),
                    latitude=fac.get("refined_latitude", fac["latitude"]), longitude=fac.get("refined_longitude", fac["longitude"]),
                    buffer_m=int(fac.get("buffer_m", 1500)),
                    geometry_geojson=json.dumps(fac["geometry"]) if fac.get("geometry") else None,
                    geometry_source="osm" if fac.get("geometry") else "catalog_point",
                    osm_element_id=fac.get("osm_element_id"), osm_name=fac.get("osm_name"),
                    osm_match_distance_km=fac.get("osm_match_distance_km"),
                ))
            db.commit()
            self.facilities = [row.to_dict() for row in db.query(FacilityModel).order_by(FacilityModel.id).all()]
        self._facility_geoms = [shape(f["geometry"]) if f["geometry"] else Point(f["longitude"], f["latitude"]) for f in self.facilities]

    def facility_for(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        key = (round(lat, 4), round(lon, 4))
        if key in self._facility_cache:
            return self._facility_cache[key]
        point, best = Point(lon, lat), None
        for fac, geom in zip(self.facilities, self._facility_geoms):
            if abs(fac["latitude"] - lat) > 0.25 or abs(fac["longitude"] - lon) > 0.25:
                continue
            if geom.geom_type in ("Polygon", "MultiPolygon") and geom.contains(point):
                distance = 0.0
            else:
                _, nearest = nearest_points(point, geom)
                distance = haversine_km(lat, lon, nearest.y, nearest.x)
            limit = FACILITY_ASSOCIATION_KM if fac["geometry"] else max(fac["buffer_m"] / 1000.0, FACILITY_ASSOCIATION_KM)
            if distance <= limit and (best is None or distance < best[0]):
                best = (distance, fac)
        result = None
        if best:
            fac = best[1]
            result = {"id": fac["id"], "name": fac["name"], "sector": fac["sector"], "facility_type": fac["facility_type"], "distance_km": round(best[0], 3)}
        self._facility_cache[key] = result
        return result

    # ------------------------------------------------------------------ ingestion
    def _insert_records(self, raw_rows: Sequence[Dict[str, Any]], data_source: str, source_label: str) -> Dict[str, Any]:
        started = utcnow_iso()
        valid, rejected = normalize.validate_records(list(raw_rows), data_source)
        inside = [r for r in valid if self.geo.in_india(r["latitude"], r["longitude"])]
        unique = {r["detection_id"]: r for r in inside}
        with SessionLocal() as db:
            existing = set()
            ids = list(unique)
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                existing.update(x[0] for x in db.query(DetectionModel.detection_id).filter(DetectionModel.detection_id.in_(chunk)).all())
            new_rows = [r for key, r in unique.items() if key not in existing]
            if new_rows:
                db.bulk_insert_mappings(DetectionModel, new_rows)
            run = IngestionRunModel(
                source=source_label, started_at=started, status="running",
                records_received=len(raw_rows), records_valid=len(valid), records_rejected=len(rejected),
                records_outside_india=len(valid) - len(inside), records_duplicate=len(inside) - len(new_rows),
                records_inserted=len(new_rows), details_json=json.dumps({"rejected_sample": rejected[:20]}),
            )
            db.add(run)
            db.commit()
            run_id = run.id
        return {
            "run_id": run_id,
            "records_received": len(raw_rows),
            "records_valid": len(valid),
            "records_rejected": len(rejected),
            "records_outside_india": len(valid) - len(inside),
            "records_duplicate": len(inside) - len(new_rows),
            "records_inserted": len(new_rows),
            "rejected_sample": rejected[:20],
            "new_detection_ids": [r["detection_id"] for r in new_rows],
            "new_coordinates": [(r["latitude"], r["longitude"]) for r in new_rows],
        }

    def _finish_run(self, run_id: int, status: str, message: str, details: Dict[str, Any]) -> None:
        with SessionLocal() as db:
            run = db.get(IngestionRunModel, run_id)
            if run is None:
                return
            merged = json.loads(run.details_json or "{}")
            merged.update(details)
            run.status, run.message, run.finished_at = status, message, utcnow_iso()
            run.details_json = json.dumps(merged, default=_json_default)
            db.commit()

    async def ingest(self, raw_rows: Sequence[Dict[str, Any]], data_source: str, source_label: str,
                     fetch_landcover: bool = True, landcover_deadline_s: float = 180.0, extra_details: Optional[Dict] = None) -> Dict[str, Any]:
        inserted = await asyncio.to_thread(self._insert_records, raw_rows, data_source, source_label)
        details: Dict[str, Any] = dict(extra_details or {})
        try:
            if fetch_landcover and inserted["new_coordinates"]:
                keys = self.landcover.missing_cells(inserted["new_coordinates"])
                details["landcover"] = await self.landcover.fetch_cells(keys, deadline_s=landcover_deadline_s)
            if inserted["records_inserted"] or not self.snapshot.get("generated_at"):
                details["analysis"] = await asyncio.to_thread(self.analyze)
                details["notifications"] = await notifications.notify_incidents(
                    details["analysis"].get("opened_incident_ids", []), details["analysis"].get("reopened_incident_ids", []))
                self.start_background_checks()
            message = f"{inserted['records_inserted']} new detections inside India ({inserted['records_duplicate']} already stored, {inserted['records_outside_india']} outside India, {inserted['records_rejected']} rejected)."
            await asyncio.to_thread(self._finish_run, inserted["run_id"], "succeeded", message, details)
        except Exception as exc:
            await asyncio.to_thread(self._finish_run, inserted["run_id"], "failed", f"{type(exc).__name__}: {exc}", details)
            raise
        result = {k: v for k, v in inserted.items() if k != "new_coordinates"}
        result.update({"message": message, "details": details})
        return result

    # ------------------------------------------------------------------ analysis
    def analyze(self) -> Dict[str, Any]:
        if not self.classifier.available:
            raise RuntimeError("Classifier model is not trained. Run: py backend/ml/train.py")
        with self._lock:
            started = time.time()
            with SessionLocal() as db:
                values = load_settings(db)
                config = severity_config(values)
                self._apply_retention(db, int(values["retention_days"]))
                rows = db.query(DetectionModel).order_by(DetectionModel.acq_datetime, DetectionModel.id).all()
                records = [row.to_record() for row in rows]
                if not records:
                    db.query(ThermalSourceModel).delete()
                    db.commit()
                    self.analysis_summary = {"detections": 0, "finished_at": utcnow_iso()}
                else:
                    changes = self._analyze_records(db, rows, records, config)
                    self.analysis_summary = {
                        "detections": len(records),
                        "duration_s": round(time.time() - started, 2),
                        "finished_at": utcnow_iso(),
                        "alert_policy_version": policy_info(config)["version"],
                        "opened_incident_ids": changes["opened"],
                        "reopened_incident_ids": changes["reopened"],
                        "withdrawn_incident_ids": changes["withdrawn"],
                    }
            self._build_snapshot()
            self.refresh_gis_store()
            return self.analysis_summary

    def _apply_retention(self, db, retention_days: int) -> None:
        newest = db.query(DetectionModel.acq_date).order_by(DetectionModel.acq_date.desc()).first()
        if not newest:
            return
        cutoff = (date.fromisoformat(newest[0]) - timedelta(days=retention_days)).isoformat()
        db.query(DetectionModel).filter(DetectionModel.acq_date < cutoff).delete(synchronize_session=False)
        db.commit()

    def _analyze_records(self, db, rows, records, config) -> Dict[str, List[int]]:
        n = len(records)
        window_start = date.fromisoformat(records[0]["acq_date"])
        window_end = date.fromisoformat(max(r["acq_date"] for r in records))
        observation_days = (window_end - window_start).days + 1
        policy = policy_info(config)

        features, evidence = build_feature_table(records, self.geo.lookup, self.landcover.features, observation_days=observation_days)
        probs = self.classifier.predict_proba(features)
        source_labels = cluster_persistent_sources(records, features)

        # Persistent sources: aggregate evidence across all detections of the location.
        members_by_label: Dict[int, List[int]] = defaultdict(list)
        for i, label in enumerate(source_labels):
            if label >= 0:
                members_by_label[int(label)].append(i)
        sources: Dict[int, Dict[str, Any]] = {}
        for label, members in members_by_label.items():
            ordered = sorted(members, key=lambda i: records[i]["acq_datetime"])
            summary = summarize_source(records, members, observation_days)
            rep = min(members, key=lambda i: haversine_km(summary["latitude"], summary["longitude"], records[i]["latitude"], records[i]["longitude"]))
            source_evidence = dict(evidence[rep])
            source_evidence["persistence_days"] = summary["active_days"]
            source_evidence["detections_within_750m"] = summary["detection_count"]
            decision = interpret(probs[members].mean(axis=0), features[rep], source_evidence)
            baselines, prior_frp, prior_days = {}, [], set()
            for i in ordered:
                baselines[i] = robust_baseline(prior_frp, len(prior_days), config)
                prior_frp.append(float(records[i]["frp"]))
                prior_days.add(records[i]["acq_date"])
            sources[label] = {
                "id": _stable_id(records[ordered[0]]["detection_id"]),
                "members": ordered,
                "summary": summary,
                "decision": decision,
                "baselines": baselines,
                "context": self.geo.lookup(summary["latitude"], summary["longitude"]),
                "facility": self.facility_for(summary["latitude"], summary["longitude"]),
                "landcover": describe_landcover(self.landcover.entry(summary["latitude"], summary["longitude"])),
            }

        transient = [i for i in range(n) if source_labels[i] < 0]
        event_of = cluster_events(records, transient)
        # Several adjacent pixels in one overpass are often a single hot event: measure the cluster as a whole.
        new_activity = overpass_clusters(records, transient)
        for i, cluster in new_activity.items():
            evidence[i]["overpass_cluster"] = cluster
        event_first: Dict[int, int] = {}
        for i, event in event_of.items():
            if event not in event_first or records[i]["acq_datetime"] < records[event_first[event]]["acq_datetime"]:
                event_first[event] = i
        event_ids = {event: _stable_id(records[first]["detection_id"]) for event, first in event_first.items()}

        # Stored Sentinel-2 findings (pipeline/imagery.py) never change a classification, but a finding that points to the
        # other category makes the detection need verification.
        imagery_found = imagery.cached_evidence(record["detection_id"] for record in records)
        decisions, severities, model_codes, critical_refs = [], [], [], []
        for i in range(n):
            label = int(source_labels[i])
            if label >= 0:
                decision = dict(sources[label]["decision"])
                decision["level"] = "persistent_source"
                baseline = sources[label]["baselines"][i]
            else:
                decision = interpret(probs[i], features[i], evidence[i])
                decision["level"] = "single_detection"
                baseline = None
            model_codes.append(decision["class_code"])
            context = self.geo.lookup(records[i]["latitude"], records[i]["longitude"])
            critical_refs.append(context.get("nearest_critical_infrastructure"))
            if decision["category"] == "vegetation":
                dist_industrial = context["dist_critical_infrastructure_km"]  # cross-alerts ignore brick kilns
            else:
                dist_industrial = min(features[i][f"dist_{c}_km"] for c in CONTEXT_CATEGORIES)
            severity = assess(
                frp=float(records[i]["frp"]), category=decision["category"], class_code=decision["class_code"],
                dist_industrial_km=dist_industrial, inside_industrial=features[i]["inside_industrial"] > 0.5,
                event_cells=evidence[i]["active_cells_within_5km_3d"], baseline=baseline, config=config,
                category_confidence=decision["category_confidence"], new_activity=new_activity.get(i) if label < 0 else None,
            )
            if severity["incident_type"] == "INDUSTRIAL_HIGH_INTENSITY":
                decision = dict(decision)
                decision["verification_required"] = True
                decision["verification_reasons"] = decision["verification_reasons"] + ["Unusual heat at an industrial site: confirm whether it is planned flaring, an upset or a fire"]
            if severity["override_class"]:
                decision = dict(decision)
                decision["model_class_code"] = decision["class_code"]
                decision["class_code"] = INDUSTRIAL_ACCIDENT
                decision["class_label"] = CLASS_LABELS[INDUSTRIAL_ACCIDENT]
                decision["category"] = "industrial"
                decision["verification_required"] = True
                decision["verification_reasons"] = decision["verification_reasons"] + ["Suspected excursion: confirm with the operator and recent imagery"]
            found = imagery_found.get(records[i]["detection_id"])
            if found and found.get("supports") and found["supports"] != decision["category"]:
                decision = dict(decision)
                decision["verification_required"] = True
                decision["verification_reasons"] = decision["verification_reasons"] + [
                    "Sentinel-2 imagery points to an industrial heat source" if found["supports"] == "industrial" else "Sentinel-2 imagery points to a vegetation fire"]
            decisions.append(decision)
            severities.append(severity)

        # Cross-alerts: is the fire front moving towards the facility? (pipeline/approach.py)
        self._apply_fire_approach(records, decisions, severities, critical_refs)

        contributions = self.classifier.top_contributions(features, model_codes)
        model_meta = self.classifier.metadata

        mappings = []
        for i, row in enumerate(rows):
            label = int(source_labels[i])
            source = sources.get(label) if label >= 0 else None
            facility = self.facility_for(records[i]["latitude"], records[i]["longitude"])
            landcover_entry = self.landcover.entry(records[i]["latitude"], records[i]["longitude"])
            decision, severity = decisions[i], severities[i]
            statements = evidence_statements(decision, evidence[i], landcover_entry, facility)
            found = imagery_found.get(records[i]["detection_id"])
            if found:
                statements.append(f"Sentinel-2 imagery: {found['headline']}")
            analysis = {
                "classification": {**decision, "category_label": CATEGORY_LABELS[decision["category"]], "model_version": model_meta.get("version")},
                "evidence": {**evidence[i], "statements": statements},
                "features": {name: _clean_number(features[i][name]) for name in FEATURE_COLUMNS},
                "contributions": contributions[i],
                "facility": facility,
                "nearest_critical_infrastructure": critical_refs[i],
                "landcover": describe_landcover(landcover_entry),
                "severity": {**{k: v for k, v in severity.items() if k != "override_class"}, "policy_version": policy["version"]},
                "emissions": emissions.estimate(decision["class_code"], float(records[i]["frp"])),
                "source": {"id": source["id"], **source["summary"]} if source else None,
                "event_id": event_ids.get(event_of.get(i)) if source is None else None,
            }
            mappings.append({
                "id": row.id,
                "source_id": source["id"] if source else None,
                "event_id": analysis["event_id"],
                "predicted_class": decision["class_code"],
                "category": decision["category"],
                "confidence_pct": decision["confidence_pct"],
                "verification_required": decision["verification_required"],
                "severity": severity["severity"],
                "severity_score": severity["severity_score"],
                "is_cross_alert": severity["is_cross_alert"],
                "facility_id": facility["id"] if facility else None,
                "analysis_json": json.dumps(analysis, default=_json_default),
            })
        db.bulk_update_mappings(DetectionModel, mappings)

        db.query(ThermalSourceModel).delete()
        severity_rank = {"NORMAL": 0, "HIGH": 1, "CRITICAL": 2}
        for label, source in sources.items():
            member_decisions = [decisions[i] for i in source["members"]]
            max_severity = max((severities[i]["severity"] for i in source["members"]), key=lambda s: severity_rank[s])
            class_code = INDUSTRIAL_ACCIDENT if any(d["class_code"] == INDUSTRIAL_ACCIDENT for d in member_decisions) else source["decision"]["class_code"]
            context = {
                "nearest_feature": source["context"].get("nearest"),
                "inside_feature": source["context"].get("inside_feature"),
                "nearest_by_category": source["context"].get("nearest_by_category"),
                "facility": source["facility"],
                "landcover": source["landcover"],
                "probabilities": source["decision"]["probabilities"],
                "verification_reasons": source["decision"]["verification_reasons"],
                "subtype_confidence": source["decision"]["subtype_confidence"],
                "trend_slope_mw_per_day": source["summary"]["trend_slope_mw_per_day"],
            }
            db.add(ThermalSourceModel(
                id=source["id"], latitude=source["summary"]["latitude"], longitude=source["summary"]["longitude"],
                first_seen=source["summary"]["first_seen"], last_seen=source["summary"]["last_seen"],
                detection_count=source["summary"]["detection_count"], active_days=source["summary"]["active_days"],
                observation_days=observation_days, persistence_ratio=source["summary"]["persistence_ratio"],
                night_fraction=source["summary"]["night_fraction"], frp_median=source["summary"]["frp_median"],
                frp_p90=source["summary"]["frp_p90"], frp_max=source["summary"]["frp_max"], extent_km=source["summary"]["extent_km"],
                predicted_class=class_code, category="industrial" if class_code == INDUSTRIAL_ACCIDENT else source["decision"]["category"],
                confidence_pct=source["decision"]["confidence_pct"], verification_required=source["decision"]["verification_required"],
                facility_id=source["facility"]["id"] if source["facility"] else None, max_severity=max_severity,
                trend=source["summary"]["trend"], context_json=json.dumps(context, default=_json_default), updated_at=utcnow_iso(),
            ))

        changes = self._update_incidents(db, records, decisions, severities, source_labels, sources, event_of, event_ids, policy)
        db.commit()
        return {kind: [incident.id for incident in incidents] for kind, incidents in changes.items()}

    def _apply_fire_approach(self, records, decisions, severities, critical_refs) -> None:
        """Attach the fire front's direction of travel to every cross-alert; an approaching front makes it critical."""
        cross_alerts = [i for i, severity in enumerate(severities) if severity["incident_type"] == "CROSS_ALERT"]
        if not cross_alerts:
            return
        vegetation = [records[i] for i, decision in enumerate(decisions) if decision["category"] == "vegetation"]
        measured: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for i in cross_alerts:
            feature = self.geo.feature((critical_refs[i] or {}).get("feature_id"))
            if feature is None:
                continue
            # Adjacent pixels of one overpass share a front: measure once per facility, overpass and ~1 km cell.
            key = (feature.feature_id, records[i]["acq_datetime"], round(records[i]["latitude"], 2), round(records[i]["longitude"], 2))
            if key not in measured:
                measured[key] = fire_approach(vegetation, records[i], feature.geometry, feature_name(feature))
            severities[i] = apply_fire_approach(severities[i], measured[key])

    @staticmethod
    def _fire_complexes(records, indices, radius_km: float = 5.0) -> Dict[int, str]:
        """Fire complexes: detections chained within radius_km of each other, keyed by the complex's earliest detection."""
        if not indices:
            return {}
        from sklearn.cluster import DBSCAN

        from .geo_context import EARTH_RADIUS_KM

        coords = np.radians([[records[i]["latitude"], records[i]["longitude"]] for i in indices])
        labels = DBSCAN(eps=radius_km / EARTH_RADIUS_KM, min_samples=1, metric="haversine", algorithm="ball_tree").fit(coords).labels_
        first: Dict[int, int] = {}
        for i, label in zip(indices, labels):
            if label not in first or (records[i]["acq_datetime"], records[i]["detection_id"]) < (records[first[label]]["acq_datetime"], records[first[label]]["detection_id"]):
                first[label] = i
        return {i: f"C{_stable_id(records[first[label]]['detection_id'])}" for i, label in zip(indices, labels)}

    def _update_incidents(self, db, records, decisions, severities, source_labels, sources, event_of, event_ids, policy) -> Dict[str, List[IncidentModel]]:
        # A large vegetation fire burns as many fire events and recurring spots at once: its high-intensity alerts are grouped
        # per fire complex, so one fire raises one incident. Other alerts are grouped per persistent source or fire event.
        complexes = self._fire_complexes(records, [i for i, s in enumerate(severities) if s["incident_type"] == "HIGH_INTENSITY_VEGETATION_FIRE"])
        groups: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for i, severity in enumerate(severities):
            if severity["severity"] not in ("HIGH", "CRITICAL"):
                continue
            label = int(source_labels[i])
            if i in complexes:
                anchor = complexes[i]
            else:
                anchor = f"S{sources[label]['id']}" if label >= 0 else f"E{event_ids.get(event_of.get(i), 0)}"
            groups[(severity["incident_type"], anchor)].append(i)

        open_incidents = {inc.group_key: inc for inc in db.query(IncidentModel).filter(IncidentModel.status.in_(OPEN_INCIDENT_STATUSES)).all()}
        closed_incidents = {inc.group_key: inc for inc in db.query(IncidentModel).filter(~IncidentModel.status.in_(OPEN_INCIDENT_STATUSES)).all()}
        alerting_keys = {f"{incident_type}:{anchor}" for incident_type, anchor in groups}
        analysed_ids = {record["detection_id"] for record in records}
        now = utcnow_iso()
        changes: Dict[str, List[IncidentModel]] = {"opened": [], "reopened": [], "withdrawn": []}
        # Alerts nobody has acted on are withdrawn when re-analysis (updated model, thresholds or data) no longer
        # raises them, and re-opened if the condition returns. Incidents a person has touched are left alone.
        for key, incident in open_incidents.items():
            history = json.loads(incident.history_json or "[]")
            untouched = incident.updated_by == "system" and all(entry.get("by") == "system" for entry in history)
            if key not in alerting_keys and untouched and incident.detection_id in analysed_ids:
                history.append({"at": now, "by": "system", "status": "RESOLVED", "note": "Withdrawn by automated re-analysis: the alert condition no longer holds"})
                incident.status, incident.updated_at, incident.history_json = "RESOLVED", now, json.dumps(history)
                changes["withdrawn"].append(incident)
        for (incident_type, anchor), indices in groups.items():
            key = f"{incident_type}:{anchor}"
            latest = max(indices, key=lambda i: records[i]["acq_datetime"])
            worst = max(indices, key=lambda i: severities[i]["severity_score"])
            decision, severity = decisions[worst], severities[worst]
            facility = self.facility_for(records[worst]["latitude"], records[worst]["longitude"])
            place = facility["name"] if facility else f"{records[worst]['latitude']:.3f}, {records[worst]['longitude']:.3f}"
            approaching = (severity.get("fire_approach") or {}).get("status") == "approaching"
            title = {
                "INDUSTRIAL_EXCURSION": f"Suspected industrial excursion - {place}",
                "INDUSTRIAL_HIGH_INTENSITY": f"Possible industrial fire or emergency flaring - {place}" if anchor.startswith("E") else f"High-intensity industrial detection - {place}",
                "CROSS_ALERT": f"Vegetation fire {'approaching' if approaching else 'near'} industrial infrastructure - {place}",
                "HIGH_INTENSITY_VEGETATION_FIRE": f"High-intensity {CLASS_LABELS[decision['class_code']].split(' / ')[0].lower()} - {place}",
            }.get(incident_type, f"Thermal alert - {place}")
            summary = "; ".join(severity["triggers"]) + f". {len(indices)} alerting detection(s); latest {records[latest]['acq_datetime']}."
            is_drill = any(records[i]["data_source"] == "drill" for i in indices)
            reason_codes = list(severity.get("reason_codes", []))
            context = {"fire_approach": severity["fire_approach"]} if severity.get("fire_approach") else {}
            incident = open_incidents.get(key)
            withdrawn = closed_incidents.get(key)
            if incident is None and withdrawn is not None and withdrawn.updated_by == "system":
                history = json.loads(withdrawn.history_json or "[]")
                history.append({"at": now, "by": "system", "status": "OPEN", "note": "Re-opened by automated analysis: the alert condition holds again"})
                withdrawn.status, withdrawn.history_json, withdrawn.updated_at = "OPEN", json.dumps(history), now
                withdrawn.detection_id, withdrawn.severity, withdrawn.summary, withdrawn.title = records[latest]["detection_id"], severity["severity"], summary, title
                self._set_alert_context(withdrawn, reason_codes, policy, context)
                changes["reopened"].append(withdrawn)
            elif incident:
                if incident.detection_id != records[latest]["detection_id"] or incident.severity != severity["severity"]:
                    incident.detection_id = records[latest]["detection_id"]
                    incident.severity = severity["severity"]
                    incident.summary = summary
                    incident.title = title
                    incident.updated_at = utcnow_iso()
                self._set_alert_context(incident, reason_codes, policy, context)
            elif key not in closed_incidents:
                label = int(source_labels[worst])
                created = IncidentModel(
                    group_key=key, detection_id=records[latest]["detection_id"],
                    source_id=sources[label]["id"] if label >= 0 else None,
                    facility_id=facility["id"] if facility else None, incident_type=incident_type, severity=severity["severity"],
                    title=title, summary=summary, recommended_action=severity["recommended_action"],
                    authorities_json=json.dumps(severity["authorities"]), status="OPEN", is_drill=is_drill,
                    latitude=records[worst]["latitude"], longitude=records[worst]["longitude"],
                    created_at=utcnow_iso(), updated_at=utcnow_iso(), updated_by="system",
                    history_json=json.dumps([{"at": utcnow_iso(), "by": "system", "status": "OPEN", "note": "Created by automated analysis"}]),
                    reason_codes_json=json.dumps(reason_codes), policy_version=policy["version"], details_json=json.dumps(context),
                )
                db.add(created)
                changes["opened"].append(created)
        return changes

    @staticmethod
    def _set_alert_context(incident: IncidentModel, reason_codes: List[str], policy: Dict[str, Any], context: Dict[str, Any]) -> None:
        """Keep an incident's reason codes, alert policy version and structured context in step with the latest analysis
        (context added later, such as the wind, is kept)."""
        incident.reason_codes_json = json.dumps(reason_codes)
        incident.policy_version = policy["version"]
        details = json.loads(incident.details_json or "{}")
        details.pop("fire_approach", None)
        details.update(context)
        incident.details_json = json.dumps(details)

    # ------------------------------------------------------------------ GIS layer store and background checks
    def gis_layers(self) -> List[gis_store.Layer]:
        with SessionLocal() as db:
            incidents = [row.to_dict() for row in db.query(IncidentModel).order_by(IncidentModel.id).all()]
        return gis_store.build_layers(self.snapshot["detections"], self.snapshot["sources"], incidents, self.facilities,
                                      self.geo.features, self.geo.boundary_geometry)

    def refresh_gis_store(self) -> None:
        """Rewrite the GeoPackage layer store. A failure (for example the file is open in a GIS) never stops the analysis."""
        try:
            counts = gis_store.write_geopackage(settings.GIS_STORE_PATH, self.gis_layers())
            self.gis_store_status = {"written_at": utcnow_iso(), "features": counts, "error": None}
        except Exception as exc:
            self.gis_store_status = {"written_at": None, "features": None, "error": f"{type(exc).__name__}: {exc}"}
            logger.warning("GIS layer store not updated: %s", exc)

    def start_background_checks(self) -> None:
        """Check open incidents against Sentinel-2 imagery and record the wind at cross-alerts, in the background
        (nothing happens offline)."""
        if settings.OFFLINE:
            return
        task = asyncio.get_running_loop().create_task(self._background_checks())
        self._tasks.add(task)  # keep a reference until the task finishes
        task.add_done_callback(self._tasks.discard)

    async def _background_checks(self) -> None:
        try:
            summary = await imagery.verify_open_incidents()
            if summary["checked"]:
                logger.info("Sentinel-2 evidence recorded for %d open incident(s)", summary["checked"])
        except Exception as exc:  # an unavailable external service must not affect monitoring
            logger.warning("Sentinel-2 incident checks failed: %s", exc)
        try:
            summary = await weather.annotate_cross_alerts()
            if summary["annotated"]:
                logger.info("Wind recorded for %d cross-alert incident(s)", summary["annotated"])
        except Exception as exc:
            logger.warning("Wind annotation failed: %s", exc)

    # ------------------------------------------------------------------ snapshot for the API
    def _build_snapshot(self) -> None:
        with SessionLocal() as db:
            rows = db.query(DetectionModel).filter(DetectionModel.predicted_class.isnot(None)).order_by(DetectionModel.acq_datetime.desc()).all()
            detections = []
            for row in rows:
                item = row.to_summary()
                analysis = json.loads(row.analysis_json or "{}")
                facility = analysis.get("facility")
                evidence = analysis.get("evidence", {})
                item.update({
                    "class_label": CLASS_LABELS.get(row.predicted_class, row.predicted_class),
                    "class_color": CLASS_COLORS.get(row.predicted_class),
                    "facility_name": facility["name"] if facility else None,
                    "place": describe_place(analysis),
                    "persistence_days": evidence.get("persistence_days"),
                    "night_fraction": evidence.get("night_fraction_within_750m"),
                    "spread_km_day": evidence.get("spread_km_per_day"),
                    "robust_zscore": analysis.get("severity", {}).get("robust_zscore"),
                })
                detections.append(item)
            sources = []
            for row in db.query(ThermalSourceModel).order_by(ThermalSourceModel.frp_median.desc()).all():
                item = row.to_dict()
                item["class_label"] = CLASS_LABELS.get(row.predicted_class, row.predicted_class)
                item["class_color"] = CLASS_COLORS.get(row.predicted_class)
                sources.append(item)
        self._attach_reviews(detections)
        dates = sorted({d["acq_date"] for d in detections})
        window = {"start": dates[0], "end": dates[-1], "days": (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days + 1} if dates else None
        self.snapshot = {"detections": detections, "sources": sources, "window": window, "generated_at": utcnow_iso()}

    @staticmethod
    def _attach_reviews(detections: List[Dict[str, Any]]) -> None:
        labels = reviews.current_labels(detections)
        for d in detections:
            review = labels.get(d["detection_id"])
            d["review_label"] = review["label"] if review else None
            d["review_category"] = review["label_category"] if review else None
            d["reviewed_by"] = review["reviewer"] if review else None
            d["reviewed_at"] = review["created_at"] if review else None

    def refresh_reviews(self) -> None:
        """Attach the current analyst labels to the snapshot after a review; no re-analysis is needed."""
        self._attach_reviews(self.snapshot["detections"])
        self.last_review_at = utcnow_iso()

    # ------------------------------------------------------------------ what-if analysis
    async def what_if(self, record: Dict[str, Any]) -> Dict[str, Any]:
        normalized = normalize.normalize_record(record, "what_if")
        lat, lon = normalized["latitude"], normalized["longitude"]
        missing = self.landcover.missing_cells([(lat, lon)])
        landcover_fetch = await self.landcover.fetch_cells(missing, deadline_s=20.0) if missing else None
        return await asyncio.to_thread(self._what_if_sync, normalized, landcover_fetch)

    def _what_if_sync(self, normalized: Dict[str, Any], landcover_fetch: Optional[Dict]) -> Dict[str, Any]:
        lat, lon = normalized["latitude"], normalized["longitude"]
        with SessionLocal() as db:
            nearby = db.query(DetectionModel).filter(
                DetectionModel.latitude.between(lat - 0.1, lat + 0.1), DetectionModel.longitude.between(lon - 0.1, lon + 0.1)
            ).all()
            records = [row.to_record() for row in nearby if row.detection_id != normalized["detection_id"]]
        records.append(normalized)
        window = self.snapshot.get("window") or {"days": 1}
        features, evidence = build_feature_table(records, self.geo.lookup, self.landcover.features, observation_days=window["days"])
        probs = self.classifier.predict_proba([features[-1]])[0]
        decision = interpret(probs, features[-1], evidence[-1])
        decision["level"] = "single_detection"
        facility = self.facility_for(lat, lon)
        entry = self.landcover.entry(lat, lon)
        return {
            "input": normalized,
            "classification": {**decision, "category_label": CATEGORY_LABELS[decision["category"]]},
            "evidence": {**evidence[-1], "statements": evidence_statements(decision, evidence[-1], entry, facility)},
            "features": {name: _clean_number(features[-1][name]) for name in FEATURE_COLUMNS},
            "contributions": self.classifier.top_contributions([features[-1]], [decision["class_code"]])[0],
            "facility": facility,
            "landcover": describe_landcover(entry),
            "landcover_fetch": landcover_fetch,
            "stored_detections_used_as_context": len(records) - 1,
            "emissions": emissions.estimate(decision["class_code"], normalized["frp"]),
            "note": "What-if analysis only - nothing is stored.",
        }

    # ------------------------------------------------------------------ drills (clearly labelled simulations)
    def drill_rows(self, kind: str, facility_id: str) -> List[Dict[str, Any]]:
        facility = next((f for f in self.facilities if f["id"] == facility_id), None)
        if facility is None:
            raise ValueError(f"Unknown facility {facility_id}")
        window = self.snapshot.get("window")
        end = datetime.combine(date.fromisoformat(window["end"]), datetime.min.time(), tzinfo=timezone.utc) if window else datetime.now(timezone.utc)
        rng = np.random.default_rng(_stable_id(facility_id + kind))
        lat0, lon0 = facility["latitude"], facility["longitude"]
        rows: List[Dict[str, Any]] = []

        def row(dt, lat, lon, frp, mir, tir, daynight):
            return {"latitude": round(lat, 5), "longitude": round(lon, 5), "acq_date": dt.strftime("%Y-%m-%d"), "acq_time": dt.strftime("%H%M"),
                    "frp": round(frp, 2), "bright_ti4": round(mir, 2), "bright_ti5": round(tir, 2), "daynight": daynight,
                    "satellite": "DRILL", "instrument": "VIIRS", "confidence": "n", "version": "drill", "scan": 0.4, "track": 0.4}

        if kind == "industrial_excursion":
            for day in range(6, 0, -1):
                dt = end - timedelta(days=day) + timedelta(hours=20, minutes=int(rng.integers(0, 50)))
                for _ in range(2):
                    rows.append(row(dt, lat0 + rng.normal(0, 0.001), lon0 + rng.normal(0, 0.001), rng.normal(3.0, 0.6), rng.uniform(318, 330), rng.uniform(288, 294), "N"))
            spike = end + timedelta(hours=20, minutes=30)
            rows.append(row(spike, lat0 + 0.0004, lon0 - 0.0003, 85.0, 367.0, 296.0, "N"))
        elif kind == "wildfire_near_facility":
            bearing = rng.uniform(0, 2 * math.pi)
            for step in range(4):
                dt = end - timedelta(days=3 - step) + timedelta(hours=8, minutes=int(rng.integers(0, 40)))
                distance_km = 5.0 - 1.1 * step
                for _ in range(3 + step):
                    offset = rng.normal(0, 0.25)
                    lat = lat0 + (distance_km * math.sin(bearing) + offset) / 110.57
                    lon = lon0 + (distance_km * math.cos(bearing) + rng.normal(0, 0.25)) / (111.32 * math.cos(math.radians(lat0)))
                    rows.append(row(dt, lat, lon, rng.uniform(12, 45), rng.uniform(345, 367), rng.uniform(302, 312), "D"))
        else:
            raise ValueError("kind must be 'industrial_excursion' or 'wildfire_near_facility'")
        return rows

    def purge_drills(self) -> Dict[str, int]:
        with SessionLocal() as db:
            drill_ids = [row[0] for row in db.query(DetectionModel.detection_id).filter(DetectionModel.data_source == "drill").all()]
            reviews_removed = 0
            for start in range(0, len(drill_ids), 500):
                reviews_removed += db.query(DetectionReviewModel).filter(
                    DetectionReviewModel.detection_id.in_(drill_ids[start:start + 500])).delete(synchronize_session=False)
            detections = db.query(DetectionModel).filter(DetectionModel.data_source == "drill").delete(synchronize_session=False)
            incidents = db.query(IncidentModel).filter(IncidentModel.is_drill.is_(True)).delete(synchronize_session=False)
            db.commit()
        return {"detections_removed": detections, "incidents_removed": incidents, "reviews_removed": reviews_removed}


service = PipelineService()

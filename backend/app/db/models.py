"""Database tables: detections, persistent thermal sources, facilities, land cover cache,
incidents, ingestion runs and settings."""
import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text

from .database import Base


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class FacilityModel(Base):
    """Curated nationally significant facilities, matched to real OSM geometry where one exists."""

    __tablename__ = "facilities"

    id = Column(String(32), primary_key=True)
    name = Column(String(255), nullable=False)
    facility_type = Column(String(64), nullable=False)
    sector = Column(String(128), nullable=False)
    operator = Column(String(255))
    state = Column(String(64))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    buffer_m = Column(Integer, nullable=False, default=1500)
    geometry_geojson = Column(Text)
    geometry_source = Column(String(32), nullable=False, default="catalog_point")
    osm_element_id = Column(String(32))
    osm_name = Column(String(255))
    osm_match_distance_km = Column(Float)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "facility_type": self.facility_type,
            "sector": self.sector,
            "operator": self.operator,
            "state": self.state,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "buffer_m": self.buffer_m,
            "geometry": _loads(self.geometry_geojson, None),
            "geometry_source": self.geometry_source,
            "osm_element_id": self.osm_element_id,
            "osm_url": f"https://www.openstreetmap.org/{self.osm_element_id}" if self.osm_element_id else None,
            "osm_name": self.osm_name,
            "osm_match_distance_km": self.osm_match_distance_km,
        }


class DetectionModel(Base):
    """One NASA FIRMS active-fire pixel (or an uploaded / drill record) with its analysis."""

    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detection_id = Column(String(24), unique=True, nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    acq_datetime = Column(String(20), nullable=False, index=True)  # UTC, "YYYY-MM-DDTHH:MMZ"
    acq_date = Column(String(10), nullable=False, index=True)
    acq_time = Column(String(4), nullable=False)
    satellite = Column(String(32))
    instrument = Column(String(16))
    confidence = Column(String(16))
    version = Column(String(16))
    daynight = Column(String(1))
    bright_mir = Column(Float)  # VIIRS I4 (3.74 um) or MODIS 4 um brightness temperature, K
    bright_tir = Column(Float)  # VIIRS I5 (11.45 um) or MODIS 11 um brightness temperature, K
    frp = Column(Float, nullable=False)  # fire radiative power, MW
    scan = Column(Float)
    track = Column(Float)
    # FIRMS standard-processing "type" (archive files only): 0 presumed vegetation fire, 1 active volcano,
    # 2 other static land source, 3 offshore. Never a model feature; used to check the model against NASA's flag.
    firms_type = Column(Integer)
    data_source = Column(String(32), nullable=False, index=True)
    ingested_at = Column(String(32), default=utcnow_iso)

    source_id = Column(Integer, index=True)
    event_id = Column(Integer, index=True)
    predicted_class = Column(String(32), index=True)
    category = Column(String(16), index=True)
    confidence_pct = Column(Float)
    verification_required = Column(Boolean, default=False)
    severity = Column(String(16), index=True, default="NORMAL")
    severity_score = Column(Float, default=0.0)
    is_cross_alert = Column(Boolean, default=False)
    facility_id = Column(String(32), index=True)
    analysis_json = Column(Text)

    __table_args__ = (Index("ix_detections_lat_lon", "latitude", "longitude"),)

    def to_record(self):
        """Raw observation fields used by the analysis pipeline."""
        return {
            "detection_id": self.detection_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "acq_datetime": self.acq_datetime,
            "acq_date": self.acq_date,
            "acq_time": self.acq_time,
            "satellite": self.satellite,
            "instrument": self.instrument,
            "confidence": self.confidence,
            "version": self.version,
            "daynight": self.daynight,
            "bright_mir": self.bright_mir,
            "bright_tir": self.bright_tir,
            "frp": self.frp,
            "scan": self.scan,
            "track": self.track,
            "firms_type": self.firms_type,
            "data_source": self.data_source,
        }

    def to_summary(self):
        record = self.to_record()
        record.update({
            "source_id": self.source_id,
            "event_id": self.event_id,
            "class_code": self.predicted_class,
            "category": self.category,
            "confidence_pct": self.confidence_pct,
            "verification_required": bool(self.verification_required),
            "severity": self.severity,
            "severity_score": self.severity_score,
            "is_cross_alert": bool(self.is_cross_alert),
            "facility_id": self.facility_id,
        })
        return record

    def to_detail(self):
        detail = self.to_summary()
        detail["analysis"] = _loads(self.analysis_json, {})
        return detail


class ThermalSourceModel(Base):
    """A location with repeated detections on at least two separate days (persistent source)."""

    __tablename__ = "thermal_sources"

    id = Column(Integer, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    first_seen = Column(String(20))
    last_seen = Column(String(20))
    detection_count = Column(Integer, nullable=False)
    active_days = Column(Integer, nullable=False)
    observation_days = Column(Integer, nullable=False)
    persistence_ratio = Column(Float)
    night_fraction = Column(Float)
    frp_median = Column(Float)
    frp_p90 = Column(Float)
    frp_max = Column(Float)
    extent_km = Column(Float)
    predicted_class = Column(String(32), index=True)
    category = Column(String(16), index=True)
    confidence_pct = Column(Float)
    verification_required = Column(Boolean, default=False)
    facility_id = Column(String(32), index=True)
    max_severity = Column(String(16))
    trend = Column(String(16))
    context_json = Column(Text)
    updated_at = Column(String(32), default=utcnow_iso)

    def to_dict(self):
        return {
            "id": self.id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "detection_count": self.detection_count,
            "active_days": self.active_days,
            "observation_days": self.observation_days,
            "persistence_ratio": self.persistence_ratio,
            "night_fraction": self.night_fraction,
            "frp_median": self.frp_median,
            "frp_p90": self.frp_p90,
            "frp_max": self.frp_max,
            "extent_km": self.extent_km,
            "class_code": self.predicted_class,
            "category": self.category,
            "confidence_pct": self.confidence_pct,
            "verification_required": bool(self.verification_required),
            "facility_id": self.facility_id,
            "max_severity": self.max_severity,
            "trend": self.trend,
            "context": _loads(self.context_json, {}),
            "updated_at": self.updated_at,
        }


class LandCoverCacheModel(Base):
    """ESA WorldCover fractions for a ~375 m footprint, keyed by a 0.003 degree grid cell."""

    __tablename__ = "landcover_cache"

    cell_key = Column(String(24), primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    status = Column(String(16), nullable=False)  # ok | nodata
    item_id = Column(String(64))
    dominant_code = Column(Integer)
    fractions_json = Column(Text)
    fetched_at = Column(String(32), default=utcnow_iso)

    def to_dict(self):
        return {
            "cell_key": self.cell_key,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "status": self.status,
            "item_id": self.item_id,
            "dominant_code": self.dominant_code,
            "fractions": _loads(self.fractions_json, {}),
            "fetched_at": self.fetched_at,
        }


class ImageryEvidenceModel(Base):
    """Sentinel-2 hot-spot and burn-scar evidence measured around a detection (pipeline/imagery.py)."""

    __tablename__ = "imagery_evidence"

    detection_id = Column(String(24), primary_key=True)
    status = Column(String(32), nullable=False)
    supports = Column(String(16))
    headline = Column(Text)
    evidence_json = Column(Text)
    checked_at = Column(String(32), default=utcnow_iso)

    def to_dict(self):
        evidence = _loads(self.evidence_json, {})
        evidence.update({"detection_id": self.detection_id, "status": self.status, "supports": self.supports,
                         "headline": self.headline, "checked_at": self.checked_at})
        return evidence


class IncidentModel(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_key = Column(String(64), index=True, nullable=False)  # incident type + persistent source / fire event
    detection_id = Column(String(24), index=True, nullable=False)
    source_id = Column(Integer)
    facility_id = Column(String(32))
    incident_type = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text)
    recommended_action = Column(Text)
    authorities_json = Column(Text)
    status = Column(String(24), nullable=False, default="OPEN", index=True)
    is_drill = Column(Boolean, default=False)
    latitude = Column(Float)
    longitude = Column(Float)
    created_at = Column(String(32), default=utcnow_iso)
    updated_at = Column(String(32), default=utcnow_iso)
    updated_by = Column(String(64))
    history_json = Column(Text)
    reason_codes_json = Column(Text)  # machine-readable reasons for the alert (severity.REASON_CODES)
    policy_version = Column(String(64))  # alert rules version + fingerprint of the thresholds that raised it
    details_json = Column(Text)  # structured context, e.g. the fire front's direction of travel and the wind

    def to_dict(self):
        return {
            "id": self.id,
            "detection_id": self.detection_id,
            "source_id": self.source_id,
            "facility_id": self.facility_id,
            "incident_type": self.incident_type,
            "severity": self.severity,
            "title": self.title,
            "summary": self.summary,
            "recommended_action": self.recommended_action,
            "authorities": _loads(self.authorities_json, []),
            "status": self.status,
            "is_drill": bool(self.is_drill),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
            "history": _loads(self.history_json, []),
            "reason_codes": _loads(self.reason_codes_json, []),
            "policy_version": self.policy_version,
            "details": _loads(self.details_json, {}),
        }


class DetectionReviewModel(Base):
    """An analyst's label for a detection, or for its whole location (persistent source or fire event).

    Reviews are append-only: the newest review is the current label, earlier ones stay as history, and the
    model's own classification is never overwritten."""

    __tablename__ = "detection_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detection_id = Column(String(24), index=True, nullable=False)
    scope = Column(String(16), nullable=False)  # detection | location
    group_key = Column(String(32), index=True)  # S<persistent source id> or E<fire event id> when reviewed
    label = Column(String(32), nullable=False)
    label_category = Column(String(16))  # industrial | vegetation; empty for other heat sources, false detections, unsure
    model_class_code = Column(String(32))
    model_category = Column(String(16))
    model_confidence_pct = Column(Float)
    model_version = Column(String(32))
    agrees_with_model = Column(Boolean)  # category agreement; empty when the label has no category
    evidence_json = Column(Text)
    note = Column(Text)
    reviewer = Column(String(64), nullable=False)
    created_at = Column(String(32), default=utcnow_iso, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "detection_id": self.detection_id,
            "scope": self.scope,
            "group_key": self.group_key,
            "label": self.label,
            "label_category": self.label_category,
            "model_class_code": self.model_class_code,
            "model_category": self.model_category,
            "model_confidence_pct": self.model_confidence_pct,
            "model_version": self.model_version,
            "agrees_with_model": self.agrees_with_model,
            "evidence": _loads(self.evidence_json, []),
            "note": self.note,
            "reviewer": self.reviewer,
            "created_at": self.created_at,
        }


class AuditLogModel(Base):
    """Append-only record of human actions: sign-ins, settings, triage, reviews, drills, uploads and syncs."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(String(32), default=utcnow_iso, index=True)
    actor = Column(String(64), nullable=False, index=True)
    action = Column(String(48), nullable=False, index=True)
    entity_type = Column(String(32))
    entity_id = Column(String(64))
    summary = Column(Text)
    details_json = Column(Text)

    def to_dict(self):
        return {
            "id": self.id,
            "at": self.at,
            "actor": self.actor,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "summary": self.summary,
            "details": _loads(self.details_json, {}),
        }


class IngestionRunModel(Base):
    __tablename__ = "ingestion_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(48), nullable=False)
    started_at = Column(String(32), default=utcnow_iso)
    finished_at = Column(String(32))
    status = Column(String(16), nullable=False, default="running")
    records_received = Column(Integer, default=0)
    records_valid = Column(Integer, default=0)
    records_rejected = Column(Integer, default=0)
    records_outside_india = Column(Integer, default=0)
    records_duplicate = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    message = Column(Text)
    details_json = Column(Text)

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "records_received": self.records_received,
            "records_valid": self.records_valid,
            "records_rejected": self.records_rejected,
            "records_outside_india": self.records_outside_india,
            "records_duplicate": self.records_duplicate,
            "records_inserted": self.records_inserted,
            "message": self.message,
            "details": _loads(self.details_json, {}),
        }


class SystemSettingsModel(Base):
    __tablename__ = "system_settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(String(32), default=utcnow_iso)
    updated_by = Column(String(64))

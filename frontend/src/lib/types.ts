import type { Category, ClassCode, IncidentStatus, Severity } from "./taxonomy";

export interface Window {
  start: string;
  end: string;
  days: number;
}

export interface FeatureRef {
  feature_id: string;
  name: string | null;
  category: string;
  subtype: string;
  source: "osm" | "catalog" | "simulated";
  distance_km: number;
  osm_url: string | null;
}

export interface FacilityRef {
  id: string;
  name: string;
  sector: string;
  facility_type: string;
  distance_km: number;
}

export interface DetectionSummary {
  detection_id: string;
  latitude: number;
  longitude: number;
  acq_datetime: string;
  acq_date: string;
  acq_time: string;
  satellite: string;
  instrument: string;
  confidence: string;
  version: string;
  daynight: "D" | "N";
  bright_mir: number | null;
  bright_tir: number | null;
  frp: number;
  scan: number | null;
  track: number | null;
  data_source: string;
  source_id: number | null;
  event_id: number | null;
  class_code: ClassCode;
  class_label: string;
  class_color: string;
  category: Category;
  confidence_pct: number;
  verification_required: boolean;
  severity: Severity;
  severity_score: number;
  is_cross_alert: boolean;
  facility_id: string | null;
  facility_name: string | null;
  place: string | null;
  persistence_days: number | null;
  night_fraction: number | null;
  spread_km_day: number | null;
  robust_zscore: number | null;
  firms_type?: number | null;
  review_label?: string | null;
  review_category?: Category | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
}

export interface Contribution {
  feature: string;
  description: string;
  value: number | null;
  contribution: number;
  direction: "supports" | "against";
}

export interface Classification {
  class_code: ClassCode;
  class_label: string;
  category: Category;
  category_label: string;
  category_confidence: number;
  subtype_confidence: number;
  confidence_pct: number;
  probabilities: Record<string, number>;
  verification_required: boolean;
  verification_reasons: string[];
  level: "persistent_source" | "single_detection";
  model_version?: string;
  model_class_code?: ClassCode;
}

export interface Evidence {
  persistence_days: number;
  observation_days: number;
  detections_within_750m: number;
  night_fraction_within_750m: number;
  frp_median_within_750m: number;
  concurrent_pixels_within_2km: number;
  active_cells_within_5km_3d: number;
  spread_km_per_day: number;
  nearest_industrial_feature: FeatureRef | null;
  inside_feature: FeatureRef | null;
  nearest_by_category: Record<string, FeatureRef>;
  statements: string[];
}

export interface LandcoverInfo {
  available: boolean;
  reason?: string;
  product?: string;
  footprint_m?: number;
  dominant_class?: string;
  fractions?: Record<string, number>;
  item_id?: string;
  fetched_at?: string;
}

export interface Baseline {
  median_mw: number;
  mad_mw: number;
  scale_mw: number;
  n: number;
  days: number;
}

export interface FireApproach {
  status: "approaching" | "receding" | "holding" | "insufficient_data";
  summary: string;
  facility: string;
  facility_latitude: number;
  facility_longitude: number;
  side: string;
  bearing_from_facility_deg: number;
  detections_used: number;
  front_by_day: { date: string; closest_km: number }[];
  first_km: number | null;
  latest_km: number;
  closing_rate_km_per_day: number | null;
}

export interface WindInfo {
  status: "ok" | "unavailable" | "error";
  reason?: string;
  time_utc?: string;
  speed_kmh?: number;
  from_deg?: number;
  from_compass?: string;
  source?: string;
  attribution?: string;
  relation?: "towards" | "away" | "across" | "calm" | null;
  facility?: string | null;
  summary?: string;
  detection_id?: string;
}

export interface SeverityInfo {
  severity: Severity;
  severity_score: number;
  score_components: Record<string, number>;
  incident_type: string | null;
  is_cross_alert: boolean;
  robust_zscore: number | null;
  baseline: Baseline | null;
  triggers: string[];
  recommended_action: string;
  authorities: string[];
  reason_codes?: string[];
  policy_version?: string;
  fire_approach?: FireApproach;
}

export interface Emissions {
  applicable: boolean;
  note?: string;
  basis?: string;
  dry_matter_burned_t_per_h?: number;
  co2_t_per_h?: number;
  emission_factor_g_per_kg?: number;
  references?: string[];
}

export interface SourceSnapshot {
  id: number;
  latitude: number;
  longitude: number;
  first_seen: string;
  last_seen: string;
  detection_count: number;
  active_days: number;
  observation_days: number;
  persistence_ratio: number;
  night_fraction: number;
  frp_median: number;
  frp_p90: number;
  frp_max: number;
  extent_km: number;
  trend: string;
  trend_slope_mw_per_day?: number;
}

export interface Analysis {
  classification: Classification;
  evidence: Evidence;
  features: Record<string, number | null>;
  contributions: Contribution[];
  facility: FacilityRef | null;
  nearest_critical_infrastructure: FeatureRef | null;
  landcover: LandcoverInfo;
  severity: SeverityInfo;
  emissions: Emissions;
  source: SourceSnapshot | null;
  event_id: number | null;
}

export type ReviewScope = "detection" | "location";
export type LocationKind = "persistent_source" | "fire_event" | "single_detection";

export interface Review {
  id: number;
  detection_id: string;
  scope: ReviewScope;
  group_key: string | null;
  label: string;
  label_category: Category | null;
  model_class_code: ClassCode | null;
  model_category: Category | null;
  model_confidence_pct: number | null;
  model_version: string | null;
  agrees_with_model: boolean | null;
  evidence: string[];
  note: string | null;
  reviewer: string;
  created_at: string;
}

export interface LocationInfo {
  group_key: string;
  kind: LocationKind;
  detections: number;
}

export interface DetectionDetail extends DetectionSummary {
  analysis: Analysis;
  category_label: string;
  incidents: Incident[];
  imagery_evidence: ImageryEvidence | null;
  reviews: Review[];
  current_review: Review | null;
  location: LocationInfo;
}

export interface ThermalSource extends SourceSnapshot {
  class_code: ClassCode;
  class_label: string;
  class_color: string;
  category: Category;
  confidence_pct: number;
  verification_required: boolean;
  facility_id: string | null;
  max_severity: Severity;
  context: {
    nearest_feature: FeatureRef | null;
    inside_feature: FeatureRef | null;
    facility: FacilityRef | null;
    landcover: LandcoverInfo;
    probabilities: Record<string, number>;
    verification_reasons: string[];
    subtype_confidence: number;
  };
  updated_at: string;
}

export interface DailyPoint {
  date: string;
  detections: number;
  max_frp: number | null;
  median_frp: number | null;
}

export interface SourceDetail extends ThermalSource {
  detections: DetectionSummary[];
  daily: DailyPoint[];
  baseline: Baseline | null;
}

export interface Facility {
  id: string;
  name: string;
  facility_type: string;
  sector: string;
  operator: string | null;
  state: string | null;
  latitude: number;
  longitude: number;
  buffer_m: number;
  geometry: GeoJSON.Geometry | null;
  geometry_source: "osm" | "catalog_point";
  osm_element_id: string | null;
  osm_url: string | null;
  osm_name: string | null;
  osm_match_distance_km: number | null;
  status: "ALERT" | "ACTIVE" | "NO_DETECTIONS";
  detections: number;
  active_days: number;
  last_detection: string | null;
  median_frp: number | null;
  max_frp: number | null;
  max_severity: Severity | null;
  classes: Record<string, number>;
  persistent_sources: { id: number; class_code: ClassCode; class_label: string; active_days: number }[];
  open_incidents: number;
  baseline: Baseline | null;
  baseline_note: string | null;
}

export interface FacilityTimeseries {
  facility: Facility;
  window: Window | null;
  series: DailyPoint[];
  baseline: Baseline | null;
  alert_threshold_mw: number | null;
  zscore_threshold: number;
  note: string;
}

export interface Incident {
  id: number;
  detection_id: string;
  source_id: number | null;
  facility_id: string | null;
  incident_type: string;
  severity: Severity;
  title: string;
  summary: string;
  recommended_action: string;
  authorities: string[];
  status: IncidentStatus;
  is_drill: boolean;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  updated_at: string;
  updated_by: string | null;
  history: { at: string; by: string; from?: string; status: string; note: string | null }[];
  imagery_evidence?: ImageryEvidenceBrief | null;
  reason_codes?: string[];
  policy_version?: string | null;
  details?: { fire_approach?: FireApproach; wind?: WindInfo };
}

export interface IngestionRun {
  id: number;
  source: string;
  started_at: string;
  finished_at: string | null;
  status: "running" | "succeeded" | "failed";
  records_received: number;
  records_valid: number;
  records_rejected: number;
  records_outside_india: number;
  records_duplicate: number;
  records_inserted: number;
  message: string | null;
  details: Record<string, any>;
}

export interface ClassCount {
  code: ClassCode;
  label: string;
  category: Category;
  color: string;
  detections: number;
  persistent_sources: number;
}

export interface Funnel {
  detections: number;
  locations: number;
  persistent_sources: number;
  fire_events: number;
  routine_locations: number;
  routine_industrial_locations: number;
  routine_vegetation_locations: number;
  alerting_locations: number;
  review_locations: number;
  open_incidents: number;
  needing_attention: number;
  attention_share: number | null;
  definition: string;
}

export interface RegionSummary {
  id: string;
  name: string;
  bbox: [number, number, number, number];
  dominant: "industrial" | "vegetation" | "mixed";
  description: string;
  detections: number;
  industrial: number;
  vegetation: number;
  classes: Record<string, number>;
  persistent_sources: number;
  open_incidents: number;
  pending_review: number;
  review_locations: number;
}

export interface Summary {
  window: Window | null;
  generated_at: string | null;
  totals: {
    detections: number;
    persistent_sources: number;
    industrial_detections: number;
    vegetation_detections: number;
    verification_required: number;
    verification_pending: number;
    reviewed_detections: number;
    facilities_with_detections: number;
    catalog_facilities: number;
  };
  classes: ClassCount[];
  severity: Record<string, number>;
  satellites: Record<string, number>;
  data_sources: Record<string, number>;
  daynight: Record<string, number>;
  daily: { date: string; industrial: number; vegetation: number }[];
  hourly_utc: { hour_utc: number; industrial: number; vegetation: number }[];
  latest_detection: string | null;
  open_incidents: Record<string, number>;
  last_ingestion: IngestionRun | null;
  funnel: Funnel;
  regions: RegionSummary[];
}

export interface Health {
  status: "ok" | "degraded";
  problems: string[];
  version: string;
  detections: number;
  persistent_sources: number;
  observation_window: Window | null;
  last_ingestion: IngestionRun | null;
  analysis?: { finished_at?: string; detections?: number; duration_s?: number };
  next_scheduled_sync: string | null;
  open_incidents: number;
  model: { available: boolean; version?: string; trained_at?: string; algorithm?: string; training_data?: string };
  alert_policy_version?: string;
  reference_data: { osm_features: number; catalog_facilities: number; landcover_cache: { cells_cached: number; cells_with_data: number } };
  dataset?: { label: string | null; static: boolean };
  last_review_at?: string | null;
  offline_mode: boolean;
  sessions_survive_restart: boolean;
}

export interface User {
  username: string;
  role: string;
  title: string;
  permissions: string[];
}

export interface WhatIfResult {
  input: Record<string, any>;
  classification: Classification;
  evidence: Evidence;
  features: Record<string, number | null>;
  contributions: Contribution[];
  facility: FacilityRef | null;
  landcover: LandcoverInfo;
  stored_detections_used_as_context: number;
  emissions: Emissions;
  note: string;
}

export interface ImageryItem {
  id: string;
  collection: string;
  datetime: string;
  days_from_detection: number;
  cloud_cover_pct: number | null;
  platform: string | null;
  stac_url: string;
  preview_url: string | null;
  chip_url?: string;
  swir_chip_url?: string;
}

export interface ImageryResult {
  detection_id: string;
  status?: string;
  reason?: string;
  sentinel_2_l2a?: { status: string; items: ImageryItem[]; search_window_days: number; reason?: string };
  landsat_c2_l2?: { status: string; items: ImageryItem[]; search_window_days: number; reason?: string };
  sentinel_1_grd?: { status: string; items: ImageryItem[]; search_window_days: number; reason?: string };
  gibs_tiles: Record<string, string>;
  note?: string;
}

export interface Settings {
  zscore_threshold: number;
  frp_threshold_mw: number;
  cross_alert_km: number;
  high_intensity_frp_mw: number;
  auto_sync_interval_mins: number;
  satellite_auto_polling: boolean;
  retention_days: number;
  webhook_url: string;
  notify_incidents: boolean;
  notify_min_severity: "HIGH" | "CRITICAL";
  dashboard_url: string;
  firms_api_key_configured: boolean;
}

export interface AlertPolicy {
  version: string;
  rules_version: string;
  thresholds_fingerprint: string;
  thresholds: Record<string, number>;
  reason_codes: Record<string, string>;
}

export type ImageryStatus = "supports_industrial" | "supports_vegetation" | "mixed" | "heat_confirmed" | "no_evidence" | "inconclusive" | "none_found" | "unavailable" | "error";

export interface ImageryScene {
  id: string;
  datetime: string;
  date: string;
  days_from_detection: number;
  platform: string | null;
  scene_cloud_cover_pct: number | null;
  valid_pixels: number;
  land_fraction: number;
  cloud_fraction: number;
  hot_pixels: number;
  max_nhi_swir: number;
  nbr_land: number | null;
}

export interface ImageryEvidenceBrief {
  status: ImageryStatus;
  supports: Category | null;
  headline: string;
  checked_at?: string;
}

export interface ImageryEvidence extends ImageryEvidenceBrief {
  detection_id?: string;
  checked_at: string;
  hotspot?: {
    detected: boolean | null;
    scene_id?: string;
    date?: string;
    hot_pixels?: number;
    max_nhi_swir?: number;
    scenes_checked?: number;
    reason?: string;
    dates_with_heat?: string[];
    persistent?: boolean;
  };
  burn_scar?: { detected: boolean | null; dnbr?: number; dnbr_darkest_5pct?: number | null; before_date?: string; after_date?: string; reason?: string };
  scenes?: ImageryScene[];
  chips?: { scene_id: string; true_colour: string; swir: string };
  method?: string;
  references?: string[];
  footprint_m?: number;
}

export interface GisLayerInfo {
  name: string;
  title: string;
  description: string;
  geometry_type: string;
  features: number;
  fields: string[];
}

export interface GisLayers {
  crs: string;
  layers: GisLayerInfo[];
  store: { format: string; path: string; exists: boolean; size_bytes: number | null; updated_at: string | null; last_write: { written_at?: string | null; error?: string | null } };
  open_with: string;
}

export interface ReviewQueueItem {
  group_key: string;
  kind: LocationKind;
  flagged_detections: number;
  detections: number;
  first_seen: string;
  last_seen: string;
  max_frp: number;
  is_drill: boolean;
  alerting: boolean;
  detection: Pick<DetectionSummary, "detection_id" | "latitude" | "longitude" | "acq_datetime" | "frp" | "daynight" | "satellite" | "class_code" | "class_label" | "category" | "confidence_pct" | "severity" | "place" | "facility_name" | "data_source" | "source_id" | "event_id">;
  reasons: string[];
}

export interface ReviewQueue {
  locations: number;
  with_alerts: number;
  flagged_detections: number;
  items: ReviewQueueItem[];
}

export interface Agreement {
  agree: number;
  compared: number;
  share: number | null;
}

export interface ReviewStats {
  reviews: number;
  reviewers: Record<string, number>;
  last_review_at: string | null;
  labelled_detections: number;
  labelled_locations: number;
  detection_agreement: Agreement;
  location_agreement: Agreement;
  labels: Record<string, number>;
  confusion: { model_category: Category; analyst: string; detections: number }[];
  pending_flagged_detections: number;
  note: string;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  summary: string;
  details: Record<string, any>;
}

import type {
  AlertPolicy,
  AuditEntry,
  DetectionDetail,
  DetectionSummary,
  Facility,
  FacilityTimeseries,
  GisLayers,
  Health,
  ImageryEvidence,
  ImageryResult,
  Incident,
  IngestionRun,
  LocationInfo,
  Review,
  ReviewQueue,
  ReviewScope,
  ReviewStats,
  Settings,
  SourceDetail,
  Summary,
  ThermalSource,
  User,
  WhatIfResult,
  WindInfo,
  Window,
} from "./types";

const BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api").replace(/\/$/, "");
const TOKEN_KEY = "geothermal_sentinel_token";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts until reload */
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query) {
  if (!query) return path;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function request<T>(path: string, init: RequestInit = {}, query?: Query): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${BASE}${withQuery(path, query)}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the backend API. Start it with run_backend.bat (port 8000).");
  }
  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    if (response.status === 401 && token) setToken(null);
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in detail
          ? String((detail as { message: string }).message)
          : `Request failed (HTTP ${response.status})`;
    throw new ApiError(response.status, message, detail);
  }
  return response.json() as Promise<T>;
}

async function fetchBlob(path: string, query?: Query): Promise<Blob> {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(`${BASE}${withQuery(path, query)}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new ApiError(0, "Cannot reach the backend API. Start it with run_backend.bat (port 8000).");
  }
  if (!response.ok) throw new ApiError(response.status, `Download failed (HTTP ${response.status})`);
  return response.blob();
}

export interface DetectionFilters extends Query {
  class_code?: string;
  category?: string;
  severity?: string;
  facility_id?: string;
  source_id?: number;
  data_source?: string;
  start_date?: string;
  end_date?: string;
  bbox?: string;
  min_frp?: number;
  verification_required?: boolean;
}

export interface IngestResult {
  run_id: number;
  records_received: number;
  records_valid: number;
  records_rejected: number;
  records_outside_india: number;
  records_duplicate: number;
  records_inserted: number;
  rejected_sample: { row: number; reason: string }[];
  message: string;
  details: Record<string, any>;
  note?: string;
}

export interface SettingsResponse {
  settings: Settings;
  environment_map_key_configured: boolean;
  next_scheduled_sync: string | null;
  offline_mode: boolean;
  static_dataset: boolean;
  alert_policy: AlertPolicy;
}

export interface ReviewRequest {
  label: string;
  scope: ReviewScope;
  note?: string;
  evidence?: string[];
}

export const api = {
  health: () => request<Health>("/health"),
  summary: () => request<Summary>("/stats/summary"),
  persistence: () => request<any>("/stats/persistence"),
  model: () => request<any>("/stats/model"),

  detections: (filters: DetectionFilters = {}) =>
    request<{ total: number; items: DetectionSummary[]; window: Window | null; generated_at: string | null }>("/detections", {}, { limit: 20000, ...filters }),
  detection: (id: string) => request<DetectionDetail>(`/detections/${encodeURIComponent(id)}`),
  exportGeojson: (filters: DetectionFilters = {}) => fetchBlob("/detections/export.geojson", filters),
  exportCsv: (filters: DetectionFilters = {}) => fetchBlob("/detections/export.csv", filters),
  whatIf: (body: Record<string, unknown>) => request<WhatIfResult>("/detections/what-if", { method: "POST", body: JSON.stringify(body) }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<IngestResult>("/detections/upload", { method: "POST", body: form });
  },

  reviewDetection: (id: string, body: ReviewRequest) =>
    request<{ review: Review; incidents_noted: number[]; location: LocationInfo; reviews: Review[] }>(`/detections/${encodeURIComponent(id)}/reviews`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reviewQueue: (limit = 200) => request<ReviewQueue>("/reviews/queue", {}, { limit }),
  reviews: (limit = 200) => request<{ items: Review[]; stats: ReviewStats }>("/reviews", {}, { limit }),
  exportLabels: () => fetchBlob("/reviews/export.csv"),

  sources: (query: Query = {}) => request<{ total: number; items: ThermalSource[] }>("/sources", {}, query),
  source: (id: number) => request<SourceDetail>(`/sources/${id}`),

  facilities: () => request<{ total: number; items: Facility[] }>("/facilities"),
  facility: (id: string) => request<Facility & { detection_list: DetectionSummary[]; incidents: Incident[] }>(`/facilities/${id}`),
  facilityTimeseries: (id: string) => request<FacilityTimeseries>(`/facilities/${id}/timeseries`),

  incidents: (query: Query = {}) => request<{ total: number; items: Incident[] }>("/incidents", {}, query),
  updateIncident: (id: number, status: string, note?: string) =>
    request<Incident>(`/incidents/${id}`, { method: "PATCH", body: JSON.stringify({ status, note: note || null }) }),

  settings: () => request<SettingsResponse>("/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    request<{ settings: Settings; updated: string[]; reanalysed: boolean; alert_policy: AlertPolicy }>("/settings", { method: "PATCH", body: JSON.stringify(body) }),
  testAlert: () => request<{ delivered: boolean; http_status?: number; error?: string }>("/settings/test-alert", { method: "POST" }),
  checkFirmsKey: () => request<{ valid: boolean; status?: any; error?: string }>("/settings/firms-key/check", { method: "POST" }),
  audit: (query: Query = {}) => request<{ items: AuditEntry[] }>("/audit", {}, query),

  sync: (body: { mode: string; window: string; day_range: number }) => request<IngestResult>("/ingestion/sync", { method: "POST", body: JSON.stringify(body) }),
  runs: () => request<{ items: IngestionRun[] }>("/ingestion/runs"),

  runDrill: (kind: string, facility_id: string) => request<IngestResult>("/drills", { method: "POST", body: JSON.stringify({ kind, facility_id }) }),
  purgeDrills: () => request<{ detections_removed: number; incidents_removed: number; reviews_removed: number }>("/drills", { method: "DELETE" }),

  briefing: () => request<any>("/reports/briefing"),
  ask: (question: string) => request<{ intent: string; answer: string; grounding: string; suggestions: string[] }>("/assistant/query", { method: "POST", body: JSON.stringify({ question }) }),

  login: (username: string, password: string) => request<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => request<{ authenticated: boolean; user: User | null; demo_passwords_active: boolean }>("/auth/me"),

  osmContext: (lat: number, lon: number, live = false) => request<any>("/context/osm", {}, { lat, lon, live }),
  osmFeatures: (bbox: string) => request<GeoJSON.FeatureCollection & { truncated: boolean }>("/context/osm-features", {}, { bbox }),
  landcover: (lat: number, lon: number) => request<any>("/context/landcover", {}, { lat, lon }),
  imagery: (id: string) => request<ImageryResult>(`/context/imagery/${encodeURIComponent(id)}`),
  imageryEvidence: (id: string, refresh = false) =>
    request<ImageryEvidence>(`/context/imagery-evidence/${encodeURIComponent(id)}`, {}, { refresh: refresh || undefined }),
  wind: (id: string) => request<WindInfo>(`/context/wind/${encodeURIComponent(id)}`),

  gisLayers: () => request<GisLayers>("/gis/layers"),
  geopackage: () => fetchBlob("/gis/geopackage"),
  layerGeojson: (name: string) => fetchBlob(`/gis/layers/${encodeURIComponent(name)}.geojson`),
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

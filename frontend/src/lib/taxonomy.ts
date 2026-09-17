// Mirrors backend/app/pipeline/taxonomy.py and severity.py. Colours are Okabe-Ito based so the classes stay
// distinguishable under common colour-vision deficiencies.

export type ClassCode = "gas_flare" | "heavy_industry" | "mining_coal_fire" | "wildfire" | "agricultural" | "industrial_accident";
export type Category = "industrial" | "vegetation";
export type Severity = "NORMAL" | "HIGH" | "CRITICAL";
export type IncidentStatus = "OPEN" | "ACKNOWLEDGED" | "INVESTIGATING" | "RESOLVED" | "FALSE_POSITIVE";

export const CLASS_ORDER: ClassCode[] = ["gas_flare", "heavy_industry", "mining_coal_fire", "industrial_accident", "wildfire", "agricultural"];

export const CLASS_META: Record<ClassCode, { label: string; short: string; color: string; category: Category }> = {
  gas_flare: { label: "Gas Flare / Oil & Gas Facility", short: "Gas flare / oil & gas", color: "#E69F00", category: "industrial" },
  heavy_industry: { label: "Heavy Industry (Steel, Cement, Power, Kilns)", short: "Heavy industry", color: "#0072B2", category: "industrial" },
  mining_coal_fire: { label: "Mining / Coal Fire", short: "Mining / coal fire", color: "#CC79A7", category: "industrial" },
  industrial_accident: { label: "Suspected Industrial Fire / Explosion", short: "Suspected industrial accident", color: "#D55E00", category: "industrial" },
  wildfire: { label: "Wildfire / Forest Fire", short: "Wildfire", color: "#009E73", category: "vegetation" },
  agricultural: { label: "Agricultural / Biomass Burning", short: "Crop / biomass burning", color: "#C9A800", category: "vegetation" },
};

export const CATEGORY_META: Record<Category, { label: string; short: string; color: string }> = {
  industrial: { label: "Industrial / extractive heat source", short: "Industrial", color: "#6D28D9" },
  vegetation: { label: "Vegetation fire (forest or agricultural)", short: "Vegetation fire", color: "#15803D" },
};

export const SEVERITY_META: Record<Severity, { label: string; text: string; bg: string; rank: number }> = {
  CRITICAL: { label: "Critical", text: "text-crit", bg: "bg-crit-soft", rank: 2 },
  HIGH: { label: "High", text: "text-warn", bg: "bg-warn-soft", rank: 1 },
  NORMAL: { label: "Normal", text: "text-muted", bg: "bg-sunk", rank: 0 },
};

export const INCIDENT_STATUS_META: Record<IncidentStatus, { label: string; text: string; bg: string }> = {
  OPEN: { label: "Open", text: "text-crit", bg: "bg-crit-soft" },
  ACKNOWLEDGED: { label: "Acknowledged", text: "text-warn", bg: "bg-warn-soft" },
  INVESTIGATING: { label: "Investigating", text: "text-accent", bg: "bg-accent-soft" },
  RESOLVED: { label: "Resolved", text: "text-good", bg: "bg-good-soft" },
  FALSE_POSITIVE: { label: "False positive", text: "text-muted", bg: "bg-sunk" },
};

export const INCIDENT_TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  OPEN: ["ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"],
  ACKNOWLEDGED: ["INVESTIGATING", "RESOLVED", "FALSE_POSITIVE"],
  INVESTIGATING: ["RESOLVED", "FALSE_POSITIVE"],
  RESOLVED: ["OPEN"],
  FALSE_POSITIVE: ["OPEN"],
};

export const INCIDENT_TYPE_LABELS: Record<string, string> = {
  INDUSTRIAL_EXCURSION: "Industrial FRP excursion",
  INDUSTRIAL_HIGH_INTENSITY: "Unusual heat at an industrial site",
  CROSS_ALERT: "Vegetation fire near industry",
  HIGH_INTENSITY_VEGETATION_FIRE: "High-intensity vegetation fire",
};

export const IMAGERY_STATUS_LABELS: Record<string, string> = {
  supports_industrial: "Imagery supports an industrial heat source",
  supports_vegetation: "Imagery supports a vegetation fire",
  heat_confirmed: "Imagery confirms real heat",
  mixed: "Imagery shows a burn scar and persistent heat",
  no_evidence: "No hot spot or burn scar in clear imagery",
  inconclusive: "Imagery inconclusive",
  none_found: "No Sentinel-2 scene found",
  unavailable: "Imagery check not available",
  error: "Imagery check failed",
};

export const CONTEXT_CATEGORY_META: Record<string, { label: string; color: string }> = {
  oil_gas: { label: "Oil & gas", color: "#E69F00" },
  heavy_industry: { label: "Heavy industry", color: "#0072B2" },
  mining: { label: "Mining", color: "#CC79A7" },
};

export const SUBTYPE_LABELS: Record<string, string> = {
  refinery: "refinery",
  gas_flare: "gas flare",
  oil_gas_well: "oil / gas well",
  gas_processing: "gas processing plant",
  oil_field: "oil field",
  thermal_power: "thermal power plant",
  steel: "steel works",
  cement: "cement plant",
  smelter: "smelter",
  kiln: "brick kiln",
  foundry_coke: "foundry / coke oven",
  glass: "glass works",
  coal_mine: "coal mine",
  mine: "mine",
  oil_refinery: "refinery",
  petrochemical: "petrochemical complex",
  lng_terminal: "LNG terminal",
  chemical_plant: "chemical estate",
  steel_plant: "steel plant",
  cement_kiln: "cement plant",
  coal_mining: "coal mining area",
};

export const DATA_SOURCE_LABELS: Record<string, string> = {
  firms_public_nrt: "NASA FIRMS public NRT feed",
  firms_api: "NASA FIRMS API (MAP_KEY)",
  firms_archive: "NASA FIRMS archive (standard processing)",
  user_upload: "Uploaded CSV",
  drill: "Drill (simulated)",
  what_if: "What-if",
};

export const LANDCOVER_LABELS: Record<string, { label: string; color: string }> = {
  tree: { label: "Tree cover", color: "#2F7D32" },
  shrub_grass: { label: "Shrub / grass", color: "#B7A537" },
  crop: { label: "Cropland", color: "#E2A74F" },
  built: { label: "Built-up", color: "#8C4A4A" },
  bare: { label: "Bare ground", color: "#A7A29A" },
  water_wetland: { label: "Water / wetland", color: "#3C7DB8" },
  other: { label: "Other", color: "#C9CED4" },
};

// Analyst review labels (backend REVIEW_LABELS): the source classes plus outcomes the model cannot produce.
export const REVIEW_LABEL_META: Record<string, { label: string; category: Category | null; group: "Industrial" | "Vegetation fire" | "Other" }> = {
  gas_flare: { label: "Gas flare / oil & gas facility", category: "industrial", group: "Industrial" },
  heavy_industry: { label: "Heavy industry (steel, cement, power, kilns)", category: "industrial", group: "Industrial" },
  mining_coal_fire: { label: "Mining / coal fire", category: "industrial", group: "Industrial" },
  industrial_accident: { label: "Industrial fire or explosion", category: "industrial", group: "Industrial" },
  wildfire: { label: "Wildfire / forest fire", category: "vegetation", group: "Vegetation fire" },
  agricultural: { label: "Agricultural / biomass burning", category: "vegetation", group: "Vegetation fire" },
  other_heat_source: { label: "Other heat source (landfill, waste or urban fire)", category: null, group: "Other" },
  not_a_fire: { label: "No heat source (false detection)", category: null, group: "Other" },
  unsure: { label: "Unsure - needs a field check", category: null, group: "Other" },
};

export const REVIEW_EVIDENCE_LABELS: Record<string, string> = {
  satellite_imagery: "Recent satellite imagery",
  operator_contact: "Facility operator or safety officer",
  field_visit: "Field visit",
  official_report: "Official report or news",
  local_knowledge: "Local knowledge",
};

export const LOCATION_KIND_LABELS: Record<string, string> = {
  persistent_source: "persistent source",
  fire_event: "fire event",
  single_detection: "detection",
};

// Short names for the machine-readable alert reason codes; the full descriptions come with the alert policy (/api/settings).
export const REASON_CODE_LABELS: Record<string, string> = {
  ABN_BASELINE_EXCEEDED: "Far above its own baseline",
  ABN_ABOVE_P90: "Above its own 90th percentile",
  NEW_HEAT_AT_SITE: "New heat at an industrial site",
  MULTI_PIXEL_CLUSTER: "Several hot pixels in one pass",
  NO_BASELINE: "No baseline yet",
  VEG_FIRE_NEAR_INFRA: "Fire near critical infrastructure",
  FIRE_SPREAD_CELLS: "Fire spread over several cells",
  CONF_LOW: "Uncertain classification",
  FIRE_APPROACHING: "Fire front approaching",
  VEG_FRP_HIGH: "Very intense fire",
  VEG_LARGE_EVENT: "Widespread fire activity",
};

export const FIRE_APPROACH_META: Record<string, { label: string; tone: "error" | "warn" | "info" }> = {
  approaching: { label: "Fire front approaching the facility", tone: "error" },
  holding: { label: "Fire front holding its distance", tone: "warn" },
  receding: { label: "Fire front moving away", tone: "info" },
  insufficient_data: { label: "Direction of travel", tone: "info" },
};

export const FIRMS_TYPE_LABELS: Record<number, string> = {
  0: "presumed vegetation fire",
  1: "active volcano",
  2: "other static land source",
  3: "offshore",
};

export const REGION_DOMINANT_LABELS: Record<string, string> = {
  industrial: "Industry",
  vegetation: "Vegetation fires",
  mixed: "Industry and forest",
};

export function subtypeLabel(code?: string | null): string {
  if (!code) return "feature";
  return SUBTYPE_LABELS[code] ?? code.replace(/_/g, " ");
}

export function reviewLabel(code?: string | null): string {
  if (!code) return "—";
  return REVIEW_LABEL_META[code]?.label ?? code.replace(/_/g, " ");
}

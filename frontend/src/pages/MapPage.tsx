import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp, Download, FileSpreadsheet, Layers, List, Palette, Pause, Play, SlidersHorizontal, X } from "lucide-react";
import type { PageProps } from "../App";
import { MapView, type Basemap, type MapFocus } from "../components/MapView";
import { Button, Dot, Field, SeverityBadge, Segmented, cx, inputClass } from "../components/ui";
import { api, downloadBlob, type DetectionFilters } from "../lib/api";
import { fmtDay, fmtUtc, timeAgo } from "../lib/format";
import { errorMessage, useApp } from "../lib/store";
import { CLASS_META, CLASS_ORDER, DATA_SOURCE_LABELS, SEVERITY_META, reviewLabel, type Category } from "../lib/taxonomy";

const LIST_LIMIT = 250;
const INDIA_VIEW = { lat: 22.8, lon: 80.5, zoom: 5 };
const LAYER_OPTIONS: { key: "sources" | "facilities" | "osm"; label: string }[] = [
  { key: "sources", label: "Persistent sources" },
  { key: "facilities", label: "Catalog facilities" },
  { key: "osm", label: "OpenStreetMap industry (zoom in)" },
];
const BASEMAPS: { value: Basemap; label: string }[] = [
  { value: "light", label: "Light map" },
  { value: "satellite", label: "Satellite imagery" },
  { value: "viirs", label: "VIIRS true colour (latest day)" },
];

function dateList(start?: string, end?: string): string[] {
  if (!start || !end) return [];
  const out: string[] = [];
  const cursor = new Date(`${start}T00:00:00Z`);
  const last = new Date(`${end}T00:00:00Z`);
  while (cursor <= last) {
    out.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return out;
}

function inBox(box: [number, number, number, number] | undefined, lat: number, lon: number): boolean {
  if (!box) return true;
  const [west, south, east, north] = box;
  return lat >= south && lat <= north && lon >= west && lon <= east;
}

// Floating panels start open only where the screen has room for them beside the map.
function roomFor(minWidth: number, minHeight = 0) {
  return window.innerWidth >= minWidth && window.innerHeight >= minHeight;
}

function FloatingCard({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("pointer-events-auto rounded-2xl border border-line bg-panel/95 shadow-float backdrop-blur", className)}>{children}</div>;
}

function MenuHeading({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-[12.5px] font-bold uppercase tracking-[0.08em] text-muted">{children}</div>;
}

function Legend({ showSources, showRegion }: { showSources: boolean; showRegion: boolean }) {
  return (
    <FloatingCard className="w-[min(340px,calc(100vw-2rem))] px-4 py-3">
      <div className="mb-2 font-display text-[15px] font-semibold text-ink">Detections by class</div>
      <div className="grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-2">
        {CLASS_ORDER.map((code) => (
          <span key={code} className="flex items-center gap-2 text-[13.5px] text-ink-2">
            <Dot color={CLASS_META[code].color} />
            {CLASS_META[code].short}
          </span>
        ))}
      </div>
      <ul className="mt-2.5 space-y-1 border-t border-line pt-2.5 text-[13px] text-muted">
        <li>Marker size = fire radiative power (FRP)</li>
        <li>Red / orange ring = critical / high severity</li>
        <li>Dashed outline = needs verification</li>
        {showSources && <li>Large ring = persistent source</li>}
        {showRegion && <li>Dashed blue box = focus region</li>}
      </ul>
    </FloatingCard>
  );
}

export function MapPage({ params }: PageProps) {
  const { detections, sources, facilities, summary, openDetection, selectedDetectionId, notify } = useApp();
  const [region, setRegion] = useState<string>(params.get("region") ?? "all");
  const [category, setCategory] = useState<"all" | Category>("all");
  const [classCode, setClassCode] = useState<string>(params.get("class_code") ?? "all");
  const [severity, setSeverity] = useState<"all" | "alerts" | "CRITICAL">("all");
  const [dataSource, setDataSource] = useState("all");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [verifyOnly, setVerifyOnly] = useState(false);
  const [minFrp, setMinFrp] = useState(0);
  const [search, setSearch] = useState("");
  const [layers, setLayers] = useState({ sources: true, facilities: true, osm: false });
  const [basemap, setBasemap] = useState<Basemap>("light");
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [timelineIndex, setTimelineIndex] = useState<number | null>(null);
  const [timelineMode, setTimelineMode] = useState<"day" | "cumulative">("day");
  const [playing, setPlaying] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(() => roomFor(768));
  const [moreFilters, setMoreFilters] = useState(false);
  const [listOpen, setListOpen] = useState(() => roomFor(1280));
  const [legendOpen, setLegendOpen] = useState(() => roomFor(1280, 760));
  const [menu, setMenu] = useState<"layers" | "export" | null>(null);

  const detectionParam = params.get("detection");
  const facilityParam = params.get("facility");
  const latParam = params.get("lat");
  const lonParam = params.get("lon");
  const regionParam = params.get("region");

  const regions = summary?.regions ?? [];
  const activeRegion = regions.find((r) => r.id === region);
  const box = activeRegion?.bbox;

  useEffect(() => {
    const code = params.get("class_code");
    if (code) setClassCode(code);
  }, [params]);

  useEffect(() => {
    if (regionParam) setRegion(regionParam);
  }, [regionParam]);

  const regionKey = activeRegion ? `${activeRegion.id}|${activeRegion.bbox.join(",")}` : "";
  useEffect(() => {
    if (!regionKey) return;
    const [id, bbox] = regionKey.split("|");
    const [west, south, east, north] = bbox.split(",").map(Number);
    setFocus({ lat: (south + north) / 2, lon: (west + east) / 2, zoom: 7, bounds: [[south, west], [north, east]], key: `r-${id}` });
  }, [regionKey]);

  useEffect(() => {
    if (detectionParam) {
      const d = detections.find((item) => item.detection_id === detectionParam);
      if (d) {
        setHighlight(d.detection_id);
        setFocus({ lat: d.latitude, lon: d.longitude, zoom: 11, key: `d-${d.detection_id}` });
      }
    } else if (facilityParam) {
      const f = facilities.find((item) => item.id === facilityParam);
      if (f) setFocus({ lat: f.latitude, lon: f.longitude, zoom: 12, key: `f-${f.id}` });
    } else if (latParam && lonParam) {
      setFocus({ lat: Number(latParam), lon: Number(lonParam), zoom: Number(params.get("zoom") ?? 11), key: `p-${latParam}-${lonParam}` });
    }
    // Focus once per target, and again when the data first arrives - not on every refresh of the detection list.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [detectionParam, facilityParam, latParam, lonParam, detections.length, facilities.length]);

  function chooseRegion(value: string) {
    setRegion(value);
    if (value === "all") setFocus({ ...INDIA_VIEW, key: `india-${Date.now()}` });
  }

  const q = search.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      detections.filter((d) => {
        if (!inBox(box, d.latitude, d.longitude)) return false;
        if (category !== "all" && d.category !== category) return false;
        if (classCode !== "all" && d.class_code !== classCode) return false;
        if (severity === "alerts" && d.severity === "NORMAL") return false;
        if (severity === "CRITICAL" && d.severity !== "CRITICAL") return false;
        if (dataSource !== "all" && d.data_source !== dataSource) return false;
        if (startDate && d.acq_date < startDate) return false;
        if (endDate && d.acq_date > endDate) return false;
        if (verifyOnly && !d.verification_required) return false;
        if (minFrp > 0 && d.frp < minFrp) return false;
        if (q && !`${d.place ?? ""} ${d.facility_name ?? ""} ${d.detection_id}`.toLowerCase().includes(q)) return false;
        return true;
      }),
    [detections, box, category, classCode, severity, dataSource, startDate, endDate, verifyOnly, minFrp, q],
  );

  const listed = useMemo(
    () =>
      [...filtered]
        .sort((a, b) => SEVERITY_META[b.severity].rank - SEVERITY_META[a.severity].rank || b.acq_datetime.localeCompare(a.acq_datetime))
        .slice(0, LIST_LIMIT),
    [filtered],
  );

  const visibleSources = useMemo(
    () => sources.filter((s) => inBox(box, s.latitude, s.longitude) && (category === "all" || s.category === category) && (classCode === "all" || s.class_code === classCode)),
    [sources, box, category, classCode],
  );

  const windowStart = summary?.window?.start;
  const windowEnd = summary?.window?.end;
  const dates = useMemo(() => dateList(windowStart, windowEnd), [windowStart, windowEnd]);
  const dataSources = Object.keys(summary?.data_sources ?? {});

  // Timeline: step through the observation window one day at a time (or cumulatively) to watch fires spread and sources recur.
  useEffect(() => {
    if (timelineIndex === null || !dates[timelineIndex]) return;
    setStartDate(timelineMode === "day" ? dates[timelineIndex] : "");
    setEndDate(dates[timelineIndex]);
  }, [timelineIndex, timelineMode, dates]);

  useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => setTimelineIndex((current) => (current === null ? 0 : Math.min(current + 1, dates.length - 1))), 1500);
    return () => window.clearInterval(timer);
  }, [playing, dates.length]);

  useEffect(() => {
    if (!playing || timelineIndex !== dates.length - 1) return undefined;
    const timer = window.setTimeout(() => setPlaying(false), 1500);
    return () => window.clearTimeout(timer);
  }, [playing, timelineIndex, dates.length]);

  function togglePlay() {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (timelineIndex === null || timelineIndex >= dates.length - 1) setTimelineIndex(0);
    setPlaying(true);
  }

  function showAllDays() {
    setPlaying(false);
    setTimelineIndex(null);
    setStartDate("");
    setEndDate("");
  }

  const activeFilters = [region !== "all", category !== "all", classCode !== "all", severity !== "all", dataSource !== "all", Boolean(startDate || endDate), minFrp > 0, verifyOnly, Boolean(q)].filter(Boolean).length;

  function resetFilters() {
    chooseRegion("all");
    setCategory("all");
    setClassCode("all");
    setSeverity("all");
    setDataSource("all");
    setMinFrp(0);
    setVerifyOnly(false);
    setSearch("");
    showAllDays();
  }

  function exportFilters(): DetectionFilters {
    return {
      category: category === "all" ? undefined : category,
      class_code: classCode === "all" ? undefined : classCode,
      severity: severity === "alerts" ? "HIGH,CRITICAL" : severity === "CRITICAL" ? "CRITICAL" : undefined,
      data_source: dataSource === "all" ? undefined : dataSource,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      min_frp: minFrp || undefined,
      bbox: box ? box.join(",") : undefined,
      verification_required: verifyOnly ? true : undefined,
    };
  }

  async function exportDetections(format: "geojson" | "csv") {
    setExporting(format);
    try {
      const blob = format === "csv" ? await api.exportCsv(exportFilters()) : await api.exportGeojson(exportFilters());
      downloadBlob(blob, `thermal_detections${activeRegion ? `_${activeRegion.id}` : ""}.${format}`);
      notify("success", `${format === "csv" ? "CSV" : "GeoJSON"} exported with the current filters${q ? " (the text search is not applied to exports)" : ""}.`);
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setExporting(null);
    }
  }

  async function exportGeopackage() {
    setExporting("gpkg");
    try {
      downloadBlob(await api.geopackage(), "geothermal_sentinel.gpkg");
      notify("success", "GeoPackage downloaded with every layer: detections, persistent sources, incidents, facilities, OSM industry and the India boundary.");
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setExporting(null);
    }
  }

  function select(id: string) {
    setHighlight(id);
    openDetection(id);
  }

  return (
    <div className={cx("map-shell relative h-full min-h-[560px] overflow-hidden", listOpen && "map-list-open")}>
      <div className="absolute inset-0">
        <MapView
          detections={filtered}
          sources={visibleSources}
          facilities={facilities}
          layers={layers}
          basemap={basemap}
          imageryDate={summary?.window?.end}
          focus={focus}
          selectedId={highlight ?? selectedDetectionId}
          regionBox={box ?? null}
          onSelectDetection={select}
          onSelectSource={(id) => (window.location.hash = `/sources?source=${id}`)}
          onSelectFacility={(id) => (window.location.hash = `/facilities?facility=${id}`)}
        />
      </div>

      {menu && <div className="fixed inset-0 z-[1001]" onClick={() => setMenu(null)} aria-hidden />}

      {/* Top row: filters on the left, map tools on the right. */}
      <div className="pointer-events-none absolute inset-x-3 top-3 z-[1002] flex flex-col-reverse items-end gap-2 sm:inset-x-4 sm:top-4 sm:flex-row sm:items-start sm:justify-between">
        <FloatingCard className="w-full sm:w-[350px]">
          <div className="flex items-center justify-between gap-2 px-4 py-3">
            <button className="flex min-w-0 items-center gap-2 text-left" onClick={() => setFiltersOpen(!filtersOpen)} aria-expanded={filtersOpen}>
              <SlidersHorizontal size={18} className="text-accent" aria-hidden />
              <span className="font-display text-[16px] font-semibold text-ink">Filters</span>
              {activeFilters > 0 && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[12.5px] font-semibold text-accent">{activeFilters} active</span>}
            </button>
            <div className="flex items-center gap-1">
              {activeFilters > 0 && (
                <button className="rounded-lg px-2 py-1 text-[13.5px] font-medium text-accent hover:bg-accent-soft" onClick={resetFilters}>
                  Reset
                </button>
              )}
              <button className="rounded-lg p-1.5 text-muted hover:bg-sunk hover:text-ink" onClick={() => setFiltersOpen(!filtersOpen)} aria-label={filtersOpen ? "Collapse filters" : "Expand filters"}>
                {filtersOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
              </button>
            </div>
          </div>
          <div className="border-t border-line px-4 py-2.5 text-[14px] text-ink-2">
            <b className="num text-ink">{filtered.length.toLocaleString("en-IN")}</b> of {detections.length.toLocaleString("en-IN")} detections
            {activeRegion ? ` in ${activeRegion.name}` : ""}
          </div>
          {filtersOpen && (
            <div className="flex max-h-[calc(100vh-290px)] flex-col gap-3 overflow-y-auto border-t border-line px-4 py-3.5">
              <Field label="Region">
                <select className={inputClass} value={region} onChange={(e) => chooseRegion(e.target.value)}>
                  <option value="all">All India</option>
                  {regions.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="flex flex-col gap-1.5">
                <span className="text-[13.5px] font-semibold text-ink-2">Category</span>
                <Segmented
                  value={category}
                  onChange={setCategory}
                  options={[
                    { value: "all", label: "All" },
                    { value: "industrial", label: "Industrial" },
                    { value: "vegetation", label: "Vegetation" },
                  ]}
                />
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                <Field label="Class">
                  <select className={inputClass} value={classCode} onChange={(e) => setClassCode(e.target.value)}>
                    <option value="all">All classes</option>
                    {CLASS_ORDER.map((code) => (
                      <option key={code} value={code}>
                        {CLASS_META[code].short}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Severity">
                  <select className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)}>
                    <option value="all">Any</option>
                    <option value="alerts">High and critical</option>
                    <option value="CRITICAL">Critical only</option>
                  </select>
                </Field>
              </div>
              <button className="flex items-center gap-1.5 self-start text-[14px] font-medium text-accent hover:underline" onClick={() => setMoreFilters(!moreFilters)} aria-expanded={moreFilters}>
                {moreFilters ? "Fewer filters" : "More filters"}
                <ChevronDown size={16} className={cx("transition-transform", moreFilters && "rotate-180")} aria-hidden />
              </button>
              {moreFilters && (
                <>
                  <div className="grid grid-cols-2 gap-2.5">
                    <Field label="From">
                      <select
                        className={inputClass}
                        value={startDate}
                        onChange={(e) => {
                          setPlaying(false);
                          setTimelineIndex(null);
                          setStartDate(e.target.value);
                        }}
                      >
                        <option value="">First day</option>
                        {dates.map((d) => (
                          <option key={d} value={d}>
                            {fmtDay(d)}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="To">
                      <select
                        className={inputClass}
                        value={endDate}
                        onChange={(e) => {
                          setPlaying(false);
                          setTimelineIndex(null);
                          setEndDate(e.target.value);
                        }}
                      >
                        <option value="">Last day</option>
                        {dates.map((d) => (
                          <option key={d} value={d}>
                            {fmtDay(d)}
                          </option>
                        ))}
                      </select>
                    </Field>
                  </div>
                  {dataSources.length > 1 && (
                    <Field label="Data source">
                      <select className={inputClass} value={dataSource} onChange={(e) => setDataSource(e.target.value)}>
                        <option value="all">All data sources</option>
                        {dataSources.map((s) => (
                          <option key={s} value={s}>
                            {DATA_SOURCE_LABELS[s] ?? s}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                  <div className="grid grid-cols-2 items-end gap-2.5">
                    <Field label="Min FRP (MW)">
                      <input className={inputClass} type="number" min={0} step={1} value={minFrp} onChange={(e) => setMinFrp(Number(e.target.value) || 0)} />
                    </Field>
                    <label className="flex h-[42px] items-center gap-2 text-[14px] text-ink-2">
                      <input type="checkbox" checked={verifyOnly} onChange={(e) => setVerifyOnly(e.target.checked)} />
                      Needs verification
                    </label>
                  </div>
                  <Field label="Search">
                    <input className={inputClass} placeholder="Place, facility or detection id" value={search} onChange={(e) => setSearch(e.target.value)} />
                  </Field>
                </>
              )}
            </div>
          )}
        </FloatingCard>

        <div className="pointer-events-auto relative flex items-center gap-2">
          <Button icon={Layers} variant={menu === "layers" ? "primary" : "secondary"} onClick={() => setMenu(menu === "layers" ? null : "layers")} aria-expanded={menu === "layers"}>
            <span className="hidden sm:inline">Layers</span>
          </Button>
          <Button icon={Download} variant={menu === "export" ? "primary" : "secondary"} onClick={() => setMenu(menu === "export" ? null : "export")} aria-expanded={menu === "export"}>
            <span className="hidden sm:inline">Export</span>
          </Button>
          <Button icon={List} variant={listOpen ? "primary" : "secondary"} onClick={() => setListOpen(!listOpen)} className="max-md:hidden" aria-pressed={listOpen}>
            Detections
          </Button>
          {menu === "layers" && (
            <FloatingCard className="absolute right-0 top-12 w-72 p-4">
              <MenuHeading>Layers</MenuHeading>
              {LAYER_OPTIONS.map(({ key, label }) => (
                <label key={key} className="flex items-center gap-2.5 py-1.5 text-[14.5px] text-ink">
                  <input type="checkbox" checked={layers[key]} onChange={(e) => setLayers({ ...layers, [key]: e.target.checked })} />
                  {label}
                </label>
              ))}
              <div className="mt-3">
                <MenuHeading>Base map</MenuHeading>
              </div>
              {BASEMAPS.map(({ value, label }) => (
                <label key={value} className="flex items-center gap-2.5 py-1.5 text-[14.5px] text-ink">
                  <input type="radio" name="basemap" checked={basemap === value} onChange={() => setBasemap(value)} />
                  {label}
                </label>
              ))}
            </FloatingCard>
          )}
          {menu === "export" && (
            <FloatingCard className="absolute right-0 top-12 w-80 p-4">
              <MenuHeading>Export</MenuHeading>
              <p className="mb-3 text-[13.5px] leading-snug text-muted">Detections with the current filters (the text search is not applied).</p>
              <div className="flex flex-col gap-2">
                <Button icon={Download} loading={exporting === "geojson"} onClick={() => exportDetections("geojson")}>
                  GeoJSON
                </Button>
                <Button icon={FileSpreadsheet} loading={exporting === "csv"} onClick={() => exportDetections("csv")}>
                  CSV
                </Button>
                <Button icon={Layers} loading={exporting === "gpkg"} onClick={exportGeopackage} title="All GIS layers as an OGC GeoPackage for QGIS or ArcGIS">
                  GeoPackage, all layers
                </Button>
              </div>
            </FloatingCard>
          )}
        </div>
      </div>

      {listOpen && (
        <aside className="absolute bottom-4 right-4 top-[72px] z-[1000] hidden w-[360px] flex-col overflow-hidden rounded-2xl border border-line bg-panel/95 shadow-float backdrop-blur md:flex">
          <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
            <div className="min-w-0">
              <div className="font-display text-[16px] font-semibold text-ink">Detections</div>
              <div className="text-[13.5px] text-muted">
                {filtered.length > LIST_LIMIT
                  ? `The ${LIST_LIMIT} most severe and recent of ${filtered.length.toLocaleString("en-IN")}`
                  : `${filtered.length.toLocaleString("en-IN")} shown, most severe first`}
              </div>
              {summary?.latest_detection && (
                <div className="text-[13px] text-muted">
                  Newest {fmtUtc(summary.latest_detection, false)} ({timeAgo(summary.latest_detection)})
                </div>
              )}
            </div>
            <button className="rounded-lg p-1.5 text-muted hover:bg-sunk hover:text-ink" onClick={() => setListOpen(false)} aria-label="Hide the detection list">
              <X size={18} />
            </button>
          </div>
          <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
            {listed.map((d) => (
              <li key={d.detection_id}>
                <button
                  onClick={() => {
                    select(d.detection_id);
                    setFocus({ lat: d.latitude, lon: d.longitude, zoom: 11, key: `l-${d.detection_id}` });
                  }}
                  className={cx("flex w-full flex-col gap-1 px-4 py-3 text-left transition-colors hover:bg-slate-50", highlight === d.detection_id && "bg-accent-soft")}
                >
                  <div className="flex items-center gap-2 text-[14.5px]">
                    <Dot color={CLASS_META[d.class_code].color} />
                    <span className="truncate font-semibold text-ink">{CLASS_META[d.class_code].short}</span>
                    {d.severity !== "NORMAL" && (
                      <span className="ml-auto">
                        <SeverityBadge severity={d.severity} />
                      </span>
                    )}
                  </div>
                  <div className="truncate text-[14px] text-ink-2">{d.place ?? `${d.latitude.toFixed(3)}, ${d.longitude.toFixed(3)}`}</div>
                  <div className="num text-[13px] text-muted">
                    {fmtUtc(d.acq_datetime, false)} · {d.frp.toFixed(1)} MW · {d.daynight === "N" ? "night" : "day"}
                    {d.review_label ? <span className="text-good"> · analyst: {reviewLabel(d.review_label)}</span> : d.verification_required && <span className="text-warn"> · verify</span>}
                  </div>
                </button>
              </li>
            ))}
            {listed.length === 0 && <li className="px-4 py-8 text-[14.5px] text-muted">No detections match these filters.</li>}
          </ul>
        </aside>
      )}

      {/* Bottom bar: legend and the day-by-day timeline. */}
      <div className={cx("pointer-events-none absolute bottom-7 left-3 right-3 z-[1000] flex flex-col items-start gap-2 sm:left-4 sm:right-4", listOpen && "md:right-[392px]")}>
        {legendOpen && <Legend showSources={layers.sources} showRegion={Boolean(box)} />}
        <FloatingCard className="flex w-full max-w-[820px] flex-wrap items-center gap-2 px-3 py-2">
          <Button size="sm" icon={Palette} variant={legendOpen ? "primary" : "secondary"} onClick={() => setLegendOpen(!legendOpen)} aria-pressed={legendOpen}>
            Legend
          </Button>
          {dates.length > 1 && (
            <>
              <span className="hidden h-6 w-px bg-line sm:block" aria-hidden />
              <Button size="sm" icon={playing ? Pause : Play} onClick={togglePlay} title="Step through the observation window day by day">
                {playing ? "Pause" : "Play"}
              </Button>
              <input
                type="range"
                min={0}
                max={dates.length - 1}
                step={1}
                value={timelineIndex ?? dates.length - 1}
                onChange={(e) => {
                  setPlaying(false);
                  setTimelineIndex(Number(e.target.value));
                }}
                className="min-w-[120px] flex-1"
                aria-label="Day in the observation window"
              />
              <span className="num min-w-[112px] text-[14px] font-semibold text-ink">
                {timelineIndex === null ? "All days" : `${timelineMode === "day" ? "" : "Up to "}${fmtDay(dates[timelineIndex])}`}
              </span>
              <Segmented
                value={timelineMode}
                onChange={setTimelineMode}
                options={[
                  { value: "day", label: "Single day" },
                  { value: "cumulative", label: "Cumulative" },
                ]}
              />
              {timelineIndex !== null && (
                <button className="rounded-lg px-2 py-1 text-[14px] font-medium text-accent hover:bg-accent-soft" onClick={showAllDays}>
                  All days
                </button>
              )}
            </>
          )}
        </FloatingCard>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { MapPin } from "lucide-react";
import type { PageProps } from "../App";
import { FrpSeriesChart, LandcoverBar, ProbabilityBars } from "../components/charts";
import { Button, Callout, ClassBadge, KeyValues, Modal, Panel, SectionHeading, Segmented, SeverityBadge, Spinner, VerifyBadge, cx, inputBase } from "../components/ui";
import { api } from "../lib/api";
import { fmtInt, fmtNum, fmtPct, fmtUtc, fmtWindow } from "../lib/format";
import { navigate } from "../lib/router";
import { errorMessage, useApp } from "../lib/store";
import { CLASS_META, CLASS_ORDER, subtypeLabel, type Category } from "../lib/taxonomy";
import type { SourceDetail, ThermalSource } from "../lib/types";

type SortKey = "active_days" | "detection_count" | "frp_median" | "frp_max" | "last_seen";

function describePlace(s: ThermalSource): string {
  if (s.context.facility) return s.context.facility.name;
  if (s.context.inside_feature) return s.context.inside_feature.name ?? `Inside ${subtypeLabel(s.context.inside_feature.subtype)}`;
  const n = s.context.nearest_feature;
  if (n && n.distance_km <= 5) return `${fmtNum(n.distance_km, 1)} km from ${n.name ?? subtypeLabel(n.subtype)}`;
  return s.context.landcover?.dominant_class ? `${s.context.landcover.dominant_class} area` : "Unmapped location";
}

export function SourcesPage({ params }: PageProps) {
  const { sources, summary, openDetection } = useApp();
  const [category, setCategory] = useState<"all" | Category>("all");
  const [classCode, setClassCode] = useState("all");
  const [minDays, setMinDays] = useState(2);
  const [verifyOnly, setVerifyOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("active_days");
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [page, setPage] = useState({ key: "", count: 50 });

  const selectedId = params.get("source");

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    if (!selectedId) return;
    let cancelled = false;
    api
      .source(Number(selectedId))
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setDetailError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const q = search.trim().toLowerCase();
  const rows = useMemo(() => {
    const list = sources.filter((s) => {
      if (category !== "all" && s.category !== category) return false;
      if (classCode !== "all" && s.class_code !== classCode) return false;
      if (s.active_days < minDays) return false;
      if (verifyOnly && !s.verification_required) return false;
      if (q && !describePlace(s).toLowerCase().includes(q)) return false;
      return true;
    });
    return list.sort((a, b) => (sort === "last_seen" ? b.last_seen.localeCompare(a.last_seen) : (b[sort] as number) - (a[sort] as number)));
  }, [sources, category, classCode, minDays, verifyOnly, q, sort]);

  const windowDays = summary?.window?.days ?? 0;
  // Long tables show 50 rows at a time; changing a filter or the sort starts again from the top.
  const filterKey = [category, classCode, minDays, verifyOnly, q, sort].join("|");
  const visibleCount = page.key === filterKey ? page.count : 50;

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 p-4 md:p-6">
      <Callout tone="info">
        A <b>persistent source</b> is a location (within 750 m) where FIRMS detected heat on at least two separate days of the observation window ({fmtWindow(summary?.window)}).
        Recurrence is the strongest sign of industrial heat; each source is classified on all of its detections together.
      </Callout>

      <Panel
        title={`${fmtInt(rows.length)} persistent sources`}
        subtitle="Click a row for the day-by-day FRP record, context and detections"
        actions={
          <>
            <Segmented
              value={category}
              onChange={setCategory}
              options={[
                { value: "all", label: "All" },
                { value: "industrial", label: "Industrial" },
                { value: "vegetation", label: "Vegetation" },
              ]}
            />
            <select className={cx(inputBase, "w-auto")} value={classCode} onChange={(e) => setClassCode(e.target.value)} aria-label="Class">
              <option value="all">All classes</option>
              {CLASS_ORDER.map((code) => (
                <option key={code} value={code}>
                  {CLASS_META[code].short}
                </option>
              ))}
            </select>
            <select className={cx(inputBase, "w-auto")} value={minDays} onChange={(e) => setMinDays(Number(e.target.value))} aria-label="Minimum active days">
              {Array.from({ length: Math.max(windowDays - 1, 1) }, (_, i) => i + 2).map((d) => (
                <option key={d} value={d}>
                  active ≥ {d} days
                </option>
              ))}
            </select>
            <select className={cx(inputBase, "w-auto")} value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort">
              <option value="active_days">Most active days</option>
              <option value="detection_count">Most detections</option>
              <option value="frp_median">Highest median FRP</option>
              <option value="frp_max">Highest max FRP</option>
              <option value="last_seen">Most recent</option>
            </select>
            <label className="flex items-center gap-1.5 text-[14px] text-ink-2">
              <input type="checkbox" checked={verifyOnly} onChange={(e) => setVerifyOnly(e.target.checked)} />
              Needs verification
            </label>
            <input className={cx(inputBase, "w-44")} placeholder="Search place" value={search} onChange={(e) => setSearch(e.target.value)} />
          </>
        }
        bodyClassName="p-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-[14px]">
            <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Class</th>
                <th className="px-2 py-2 font-medium">Place</th>
                <th className="px-2 py-2 text-right font-medium">Active days</th>
                <th className="px-2 py-2 text-right font-medium">Detections</th>
                <th className="px-2 py-2 text-right font-medium">Night share</th>
                <th className="px-2 py-2 text-right font-medium">Median / max FRP</th>
                <th className="px-2 py-2 font-medium">Trend</th>
                <th className="px-4 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.slice(0, visibleCount).map((s) => (
                <tr key={s.id} className="cursor-pointer hover:bg-sunk" onClick={() => navigate("sources", { source: s.id })}>
                  <td className="px-4 py-2">
                    <ClassBadge code={s.class_code} compact />
                    <div className="text-[13px] text-muted">{fmtNum(s.confidence_pct, 0)}% category confidence</div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="text-ink">{describePlace(s)}</div>
                    <div className="num text-[13px] text-muted">
                      {s.latitude.toFixed(3)}, {s.longitude.toFixed(3)}
                    </div>
                  </td>
                  <td className="num px-2 py-2 text-right">
                    {s.active_days} / {s.observation_days}
                  </td>
                  <td className="num px-2 py-2 text-right">{s.detection_count}</td>
                  <td className="num px-2 py-2 text-right">{fmtPct(s.night_fraction)}</td>
                  <td className="num px-2 py-2 text-right">
                    {fmtNum(s.frp_median)} / {fmtNum(s.frp_max)} MW
                  </td>
                  <td className="px-2 py-2 text-ink-2">{s.trend.replace("_", " ")}</td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1">
                      {s.max_severity !== "NORMAL" && <SeverityBadge severity={s.max_severity} />}
                      {s.verification_required && <VerifyBadge />}
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-muted">
                    No persistent sources match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {rows.length > visibleCount && (
          <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3 text-[14px] text-muted">
            Showing {fmtInt(visibleCount)} of {fmtInt(rows.length)}
            <Button size="sm" onClick={() => setPage({ key: filterKey, count: visibleCount + 50 })}>
              Show 50 more
            </Button>
          </div>
        )}
      </Panel>

      <Modal
        open={Boolean(selectedId)}
        onClose={() => navigate("sources")}
        width="max-w-4xl"
        title={detail ? <ClassBadge code={detail.class_code} /> : "Persistent source"}
        subtitle={detail ? `${describePlace(detail)} · first seen ${fmtUtc(detail.first_seen)} · last seen ${fmtUtc(detail.last_seen)}` : undefined}
      >
        {detailError && <Callout tone="error">{detailError}</Callout>}
        {!detail && !detailError && <Spinner />}
        {detail && (
          <div className="text-[14.5px]">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {detail.max_severity !== "NORMAL" && <SeverityBadge severity={detail.max_severity} />}
              {detail.verification_required && <VerifyBadge title={detail.context.verification_reasons.join("; ")} />}
              <Button size="sm" icon={MapPin} onClick={() => navigate("map", { lat: detail.latitude, lon: detail.longitude, zoom: 12 })}>
                Show on map
              </Button>
            </div>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <div>
                <SectionHeading>Record</SectionHeading>
                <KeyValues
                  rows={[
                    ["Active days", `${detail.active_days} of ${detail.observation_days} (${fmtPct(detail.persistence_ratio)})`],
                    ["Detections", fmtInt(detail.detection_count)],
                    ["Night share", fmtPct(detail.night_fraction)],
                    ["FRP median / p90 / max", `${fmtNum(detail.frp_median)} / ${fmtNum(detail.frp_p90)} / ${fmtNum(detail.frp_max)} MW`],
                    ["Spatial extent", `${fmtNum(detail.extent_km, 2)} km from centre`],
                    ["Trend", `${detail.trend.replace("_", " ")}${detail.trend_slope_mw_per_day ? ` (${fmtNum(detail.trend_slope_mw_per_day, 2)} MW/day)` : ""}`],
                    ["Baseline", detail.baseline ? `median ${fmtNum(detail.baseline.median_mw)} MW, scale ${fmtNum(detail.baseline.scale_mw)} MW` : "needs 6 detections on 3 days"],
                  ]}
                />
              </div>
              <div>
                <SectionHeading>Context</SectionHeading>
                <div className="flex flex-col gap-1.5 text-ink-2">
                  {detail.context.facility && <span>Catalog facility: <b className="text-ink">{detail.context.facility.name}</b></span>}
                  {detail.context.inside_feature && (
                    <span>
                      Inside {subtypeLabel(detail.context.inside_feature.subtype)} {detail.context.inside_feature.name && <b className="text-ink">{detail.context.inside_feature.name}</b>}{" "}
                      {detail.context.inside_feature.osm_url && (
                        <a className="text-accent hover:underline" href={detail.context.inside_feature.osm_url} target="_blank" rel="noreferrer">
                          {detail.context.inside_feature.feature_id}
                        </a>
                      )}
                    </span>
                  )}
                  {!detail.context.inside_feature && detail.context.nearest_feature && (
                    <span>
                      Nearest mapped feature: {detail.context.nearest_feature.name ?? subtypeLabel(detail.context.nearest_feature.subtype)} ({fmtNum(detail.context.nearest_feature.distance_km, 2)} km){" "}
                      {detail.context.nearest_feature.osm_url && (
                        <a className="text-accent hover:underline" href={detail.context.nearest_feature.osm_url} target="_blank" rel="noreferrer">
                          {detail.context.nearest_feature.feature_id}
                        </a>
                      )}
                    </span>
                  )}
                </div>
                {detail.context.landcover?.available && detail.context.landcover.fractions && (
                  <div className="mt-2">
                    <LandcoverBar fractions={detail.context.landcover.fractions} />
                  </div>
                )}
              </div>
            </div>

            <SectionHeading hint="days without a point had no detection (no fire seen, or cloud)">Maximum FRP per day</SectionHeading>
            <FrpSeriesChart series={detail.daily} baselineMedian={detail.baseline?.median_mw} />

            <SectionHeading hint={`subtype confidence ${fmtPct(detail.context.subtype_confidence)}`}>Class probabilities (all detections)</SectionHeading>
            <ProbabilityBars probabilities={detail.context.probabilities} highlight={detail.class_code} />

            <SectionHeading>Detections</SectionHeading>
            <div className="max-h-64 overflow-y-auto rounded-lg border border-line">
              <table className="w-full text-[14px]">
                <tbody className="divide-y divide-line">
                  {[...detail.detections].reverse().map((d) => (
                    <tr key={d.detection_id} className="cursor-pointer hover:bg-sunk" onClick={() => openDetection(d.detection_id)}>
                      <td className="px-3 py-1.5">{fmtUtc(d.acq_datetime)}</td>
                      <td className="px-2 py-1.5 text-ink-2">{d.satellite}</td>
                      <td className="px-2 py-1.5 text-ink-2">{d.daynight === "N" ? "night" : "day"}</td>
                      <td className="num px-2 py-1.5 text-right">{fmtNum(d.frp)} MW</td>
                      <td className="px-3 py-1.5 text-right">{d.severity !== "NORMAL" && <SeverityBadge severity={d.severity} />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

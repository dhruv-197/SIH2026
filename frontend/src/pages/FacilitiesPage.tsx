import { useEffect, useMemo, useState } from "react";
import { ExternalLink, MapPin } from "lucide-react";
import type { PageProps } from "../App";
import { FrpSeriesChart } from "../components/charts";
import { Button, Callout, ClassBadge, KeyValues, Modal, Panel, SectionHeading, SeverityBadge, Spinner, Stat, cx, inputBase } from "../components/ui";
import { api } from "../lib/api";
import { fmtInt, fmtNum, fmtUtc } from "../lib/format";
import { navigate } from "../lib/router";
import { errorMessage, useApp } from "../lib/store";
import type { ClassCode } from "../lib/taxonomy";
import type { DetectionSummary, Facility, FacilityTimeseries, Incident } from "../lib/types";

const STATUS_META: Record<Facility["status"], { label: string; className: string }> = {
  ALERT: { label: "Open alert", className: "bg-crit-soft text-crit" },
  ACTIVE: { label: "Heat detected", className: "bg-accent-soft text-accent" },
  NO_DETECTIONS: { label: "No detections", className: "bg-sunk text-muted" },
};

export function FacilitiesPage({ params }: PageProps) {
  const { facilities, openDetection } = useApp();
  const [sector, setSector] = useState("all");
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<(Facility & { detection_list: DetectionSummary[]; incidents: Incident[] }) | null>(null);
  const [series, setSeries] = useState<FacilityTimeseries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedId = params.get("facility");

  useEffect(() => {
    setDetail(null);
    setSeries(null);
    setError(null);
    if (!selectedId) return;
    let cancelled = false;
    Promise.all([api.facility(selectedId), api.facilityTimeseries(selectedId)])
      .then(([f, s]) => {
        if (cancelled) return;
        setDetail(f);
        setSeries(s);
      })
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const sectors = useMemo(() => Array.from(new Set(facilities.map((f) => f.sector))).sort(), [facilities]);
  const q = search.trim().toLowerCase();
  const rows = useMemo(
    () =>
      facilities
        .filter((f) => (sector === "all" || f.sector === sector) && (status === "all" || f.status === status) && (!q || `${f.name} ${f.operator} ${f.state}`.toLowerCase().includes(q)))
        .sort((a, b) => b.open_incidents - a.open_incidents || b.detections - a.detections || a.name.localeCompare(b.name)),
    [facilities, sector, status, q],
  );

  const matched = facilities.filter((f) => f.osm_element_id).length;

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 p-4 md:p-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Catalog facilities" value={facilities.length} hint="nationally significant refineries, steel, power, mines, LNG" />
        <Stat label="Matched to OpenStreetMap" value={matched} hint="boundary from a real OSM element" />
        <Stat label="With detections" value={facilities.filter((f) => f.detections > 0).length} hint="in the current observation window" />
        <Stat label="With open alerts" value={facilities.filter((f) => f.status === "ALERT").length} color={facilities.some((f) => f.status === "ALERT") ? "#c0262d" : undefined} />
      </div>

      <Panel
        title="Facilities"
        subtitle="Baselines are learned from each facility's own detections; no operating values are assumed"
        actions={
          <>
            <select className={cx(inputBase, "w-auto")} value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector">
              <option value="all">All sectors</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select className={cx(inputBase, "w-auto")} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="all">Any status</option>
              <option value="ALERT">Open alert</option>
              <option value="ACTIVE">Heat detected</option>
              <option value="NO_DETECTIONS">No detections</option>
            </select>
            <input className={cx(inputBase, "w-48")} placeholder="Search name, operator, state" value={search} onChange={(e) => setSearch(e.target.value)} />
          </>
        }
        bodyClassName="p-0"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-[14px]">
            <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">Facility</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 text-right font-medium">Detections</th>
                <th className="px-2 py-2 text-right font-medium">Days</th>
                <th className="px-2 py-2 text-right font-medium">Median / max FRP</th>
                <th className="px-2 py-2 font-medium">Learned baseline</th>
                <th className="px-4 py-2 font-medium">Geometry</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((f) => (
                <tr key={f.id} className="cursor-pointer hover:bg-sunk" onClick={() => navigate("facilities", { facility: f.id })}>
                  <td className="px-4 py-2">
                    <div className="font-medium text-ink">{f.name}</div>
                    <div className="text-[13px] text-muted">
                      {f.sector} · {f.state}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <span className={cx("rounded-lg px-1.5 py-0.5 text-[13px] font-semibold", STATUS_META[f.status].className)}>{STATUS_META[f.status].label}</span>
                    {f.open_incidents > 0 && <div className="mt-0.5 text-[13px] text-crit">{f.open_incidents} open incident(s)</div>}
                  </td>
                  <td className="num px-2 py-2 text-right">{fmtInt(f.detections)}</td>
                  <td className="num px-2 py-2 text-right">{f.active_days}</td>
                  <td className="num px-2 py-2 text-right">{f.median_frp == null ? "—" : `${fmtNum(f.median_frp)} / ${fmtNum(f.max_frp)} MW`}</td>
                  <td className="num px-2 py-2 text-ink-2">{f.baseline ? `${fmtNum(f.baseline.median_mw)} ± ${fmtNum(f.baseline.scale_mw)} MW` : <span className="text-muted">not enough detections</span>}</td>
                  <td className="px-4 py-2 text-[13.5px]">
                    {f.osm_url ? (
                      <a href={f.osm_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline" onClick={(e) => e.stopPropagation()}>
                        {f.osm_element_id} <ExternalLink size={11} />
                      </a>
                    ) : (
                      <span className="text-muted">catalog point (not in OSM)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Modal open={Boolean(selectedId)} onClose={() => navigate("facilities")} width="max-w-4xl" title={detail?.name ?? "Facility"} subtitle={detail ? `${detail.sector} · ${detail.operator ?? ""} · ${detail.state ?? ""}` : undefined}>
        {error && <Callout tone="error">{error}</Callout>}
        {!detail && !error && <Spinner />}
        {detail && series && (
          <div className="text-[14.5px]">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className={cx("rounded-lg px-1.5 py-0.5 text-[13px] font-semibold", STATUS_META[detail.status].className)}>{STATUS_META[detail.status].label}</span>
              <Button size="sm" icon={MapPin} onClick={() => navigate("map", { facility: detail.id })}>
                Show on map
              </Button>
            </div>
            <KeyValues
              rows={[
                ["OpenStreetMap match", detail.osm_url ? <a key="osm" className="text-accent hover:underline" href={detail.osm_url} target="_blank" rel="noreferrer">{detail.osm_element_id} {detail.osm_name ? `(${detail.osm_name})` : ""}</a> : "No matching OSM element - approximate catalog location used"],
                ["Detections in window", `${fmtInt(detail.detections)} on ${detail.active_days} day(s)`],
                ["Last detection", detail.last_detection ? fmtUtc(detail.last_detection) : "—"],
                ["Learned baseline", detail.baseline ? `median ${fmtNum(detail.baseline.median_mw)} MW, robust scale ${fmtNum(detail.baseline.scale_mw)} MW (${detail.baseline.n} detections over ${detail.baseline.days} days)` : detail.baseline_note],
                ["Alert threshold", series.alert_threshold_mw != null ? `${fmtNum(series.alert_threshold_mw)} MW (median + ${series.zscore_threshold} × scale)` : "available once a baseline exists"],
              ]}
            />
            <SectionHeading hint={series.note}>Maximum FRP per day</SectionHeading>
            {detail.detections > 0 ? <FrpSeriesChart series={series.series} baselineMedian={series.baseline?.median_mw} threshold={series.alert_threshold_mw} /> : <div className="text-muted">No detections in this window.</div>}

            {Object.keys(detail.classes).length > 0 && (
              <>
                <SectionHeading>How its detections were classified</SectionHeading>
                <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                  {Object.entries(detail.classes).map(([code, n]) => (
                    <span key={code} className="inline-flex items-center gap-1.5">
                      <ClassBadge code={code as ClassCode} compact /> <span className="num text-muted">{n}</span>
                    </span>
                  ))}
                </div>
              </>
            )}

            {detail.persistent_sources.length > 0 && (
              <>
                <SectionHeading>Persistent sources at this facility</SectionHeading>
                <div className="flex flex-wrap gap-2">
                  {detail.persistent_sources.map((s) => (
                    <button key={s.id} className="rounded-lg border border-line px-2 py-1 text-[13.5px] hover:bg-sunk" onClick={() => navigate("sources", { source: s.id })}>
                      <ClassBadge code={s.class_code} compact /> · {s.active_days} days
                    </button>
                  ))}
                </div>
              </>
            )}

            {detail.detection_list.length > 0 && (
              <>
                <SectionHeading>Recent detections</SectionHeading>
                <div className="max-h-60 overflow-y-auto rounded-lg border border-line">
                  <table className="w-full text-[14px]">
                    <tbody className="divide-y divide-line">
                      {detail.detection_list.slice(0, 60).map((d) => (
                        <tr key={d.detection_id} className="cursor-pointer hover:bg-sunk" onClick={() => openDetection(d.detection_id)}>
                          <td className="px-3 py-1.5">{fmtUtc(d.acq_datetime)}</td>
                          <td className="px-2 py-1.5">
                            <ClassBadge code={d.class_code} compact />
                          </td>
                          <td className="num px-2 py-1.5 text-right">{fmtNum(d.frp)} MW</td>
                          <td className="px-3 py-1.5 text-right">{d.severity !== "NORMAL" && <SeverityBadge severity={d.severity} />}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

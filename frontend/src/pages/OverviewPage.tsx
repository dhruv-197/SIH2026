import { Fragment, useEffect, useState } from "react";
import { ArrowRight, ChevronRight, ClipboardCheck, Factory, MapPin, Satellite, Siren, Trees } from "lucide-react";
import type { PageProps } from "../App";
import { ClassBars, DailyCategoryChart, HourlyChart } from "../components/charts";
import { Button, Callout, Disclosure, KeyValues, Panel, SectionHeading, SeverityBadge, Spinner, Stat, cx } from "../components/ui";
import { api } from "../lib/api";
import { fmtInt, fmtIst, fmtPct, fmtUtc, fmtWindow, timeAgo } from "../lib/format";
import { navigate } from "../lib/router";
import { useApp } from "../lib/store";
import { CATEGORY_META, INCIDENT_TYPE_LABELS, REGION_DOMINANT_LABELS, SEVERITY_META } from "../lib/taxonomy";
import type { Facility, Funnel, Incident, RegionSummary } from "../lib/types";

const OPEN = ["OPEN", "ACKNOWLEDGED", "INVESTIGATING"];

function FunnelPanel({ funnel }: { funnel: Funnel }) {
  const steps = [
    { label: "Raw detections", value: funnel.detections, hint: "hot pixels inside India" },
    { label: "Thermal locations", value: funnel.locations, hint: `${fmtInt(funnel.persistent_sources)} persistent · ${fmtInt(funnel.fire_events)} fire events` },
    { label: "Routine, no action", value: funnel.routine_locations, hint: `${fmtInt(funnel.routine_industrial_locations)} industrial · ${fmtInt(funnel.routine_vegetation_locations)} vegetation` },
  ];
  return (
    <Panel title="From raw detections to decisions" subtitle={`${fmtInt(funnel.detections)} hot pixels became ${fmtInt(funnel.needing_attention)} items that need a person`}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1.25fr]">
        {steps.map((step, index) => (
          <Fragment key={step.label}>
            <div className="rounded-xl border border-line bg-slate-50 px-4 py-3.5">
              <div className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
                {index + 1}. {step.label}
              </div>
              <div className="num mt-1 font-display text-[28px] font-bold leading-tight tracking-tight text-ink">{fmtInt(step.value)}</div>
              <div className="text-[14px] leading-snug text-ink-2">{step.hint}</div>
            </div>
            <ChevronRight size={22} className="hidden self-center text-line-strong xl:block" aria-hidden />
          </Fragment>
        ))}
        <div className="flex flex-col justify-between gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3.5">
          <div>
            <div className="text-[13px] font-semibold uppercase tracking-[0.06em] text-indigo-700">4. Need a person</div>
            <div className="num mt-1 font-display text-[34px] font-extrabold leading-tight tracking-tight text-indigo-950">{fmtInt(funnel.needing_attention)}</div>
            <div className="text-[14px] leading-snug text-indigo-900/80">
              {fmtInt(funnel.open_incidents)} open incidents · {fmtInt(funnel.review_locations)} locations to review
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="primary" icon={Siren} onClick={() => navigate("incidents")}>
              Incidents
            </Button>
            <Button size="sm" icon={ClipboardCheck} onClick={() => navigate("review")}>
              Review queue
            </Button>
          </div>
        </div>
      </div>
      <details className="mt-4 text-[14px]">
        <summary className="inline-flex font-medium text-accent hover:underline">How locations and attention are counted</summary>
        <p className="mt-2 max-w-[90ch] leading-relaxed text-muted">{funnel.definition}</p>
      </details>
    </Panel>
  );
}

function CategorySplit({ industrial, vegetation }: { industrial: number; vegetation: number }) {
  const total = industrial + vegetation;
  if (!total) return <span className="text-[13.5px] text-muted">no detections</span>;
  const share = industrial / total;
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex h-2 overflow-hidden rounded-full bg-sunk" aria-hidden>
        <div style={{ width: `${share * 100}%`, background: CATEGORY_META.industrial.color }} />
        <div style={{ width: `${(1 - share) * 100}%`, background: CATEGORY_META.vegetation.color }} />
      </div>
      <div className="num flex justify-between gap-2 text-[12.5px] text-muted">
        <span>{fmtPct(share)} industrial</span>
        <span>{fmtPct(1 - share)} vegetation</span>
      </div>
    </div>
  );
}

function IncidentsPanel({ incidents }: { incidents: Incident[] }) {
  return (
    <Panel
      title="Open incidents"
      subtitle={incidents.length ? "Most severe first" : undefined}
      tone="neutral"
      actions={
        <Button size="sm" icon={ArrowRight} onClick={() => navigate("incidents")}>
          All incidents
        </Button>
      }
      bodyClassName="p-0"
    >
      {incidents.length === 0 ? (
        <div className="px-5 py-6 text-[15px] text-muted">No open incidents.</div>
      ) : (
        <ul className="divide-y divide-line">
          {incidents.slice(0, 5).map((incident) => (
            <li key={incident.id}>
              <button className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-slate-50" onClick={() => navigate("incidents", { incident: incident.id })}>
                <span className={cx("mt-2 h-2.5 w-2.5 shrink-0 rounded-full", incident.severity === "CRITICAL" ? "bg-crit" : "bg-amber-500")} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-[15px] font-semibold leading-snug text-ink">{incident.title}</span>
                  <span className="mt-0.5 block text-[13.5px] text-muted">
                    {INCIDENT_TYPE_LABELS[incident.incident_type] ?? incident.incident_type} · updated {timeAgo(incident.updated_at)}
                    {incident.is_drill ? " · DRILL" : ""}
                  </span>
                </span>
                <SeverityBadge severity={incident.severity} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {incidents.length > 5 && (
        <div className="border-t border-line px-5 py-3 text-[14px] text-muted">
          and {incidents.length - 5} more on the{" "}
          <button className="font-medium text-accent hover:underline" onClick={() => navigate("incidents")}>
            Incidents page
          </button>
        </div>
      )}
    </Panel>
  );
}

function RegionsPanel({ regions }: { regions: RegionSummary[] }) {
  return (
    <Panel title="Focus regions" subtitle="Click a region to open it on the map" bodyClassName="p-0">
      <ul className="divide-y divide-line">
        {regions.map((region) => (
          <li key={region.id}>
            <button
              title={region.description}
              className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 px-5 py-3.5 text-left transition-colors hover:bg-slate-50 sm:grid-cols-[minmax(0,1.15fr)_minmax(150px,1fr)_auto]"
              onClick={() => navigate("map", { region: region.id })}
            >
              <span className="min-w-0">
                <span className="block truncate text-[15px] font-semibold text-ink">{region.name}</span>
                <span className="block truncate text-[13.5px] text-muted">
                  {REGION_DOMINANT_LABELS[region.dominant]} · {fmtInt(region.detections)} detections
                  {region.review_locations ? ` · ${region.review_locations} to review` : ""}
                </span>
              </span>
              <span className="hidden sm:block">
                <CategorySplit industrial={region.industrial} vegetation={region.vegetation} />
              </span>
              <span className="flex items-center gap-2">
                {region.open_incidents > 0 ? (
                  <span className="num whitespace-nowrap rounded-full bg-rose-50 px-2.5 py-0.5 text-[13px] font-semibold text-crit">
                    {region.open_incidents} incident{region.open_incidents === 1 ? "" : "s"}
                  </span>
                ) : (
                  <span className="whitespace-nowrap text-[13px] text-muted">no incidents</span>
                )}
                <ChevronRight size={18} className="text-muted" aria-hidden />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function FacilitiesTable({ facilities }: { facilities: Facility[] }) {
  if (facilities.length === 0) return <p className="text-[14.5px] text-muted">No catalog facility has detections in this window.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[14px]">
        <thead className="text-left text-[12.5px] uppercase tracking-wide text-muted">
          <tr>
            <th className="py-2 pr-3 font-semibold">Facility</th>
            <th className="px-2 py-2 text-right font-semibold">Detections</th>
            <th className="px-2 py-2 text-right font-semibold">Days</th>
            <th className="py-2 pl-2 text-right font-semibold">Median FRP</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {facilities.map((f) => (
            <tr key={f.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate("facilities", { facility: f.id })}>
              <td className="py-2.5 pr-3">
                <div className="font-medium text-ink">{f.name}</div>
                <div className="text-[13px] text-muted">
                  {f.sector}
                  {f.open_incidents > 0 && <span className="ml-1 font-semibold text-crit">· {f.open_incidents} open incident(s)</span>}
                </div>
              </td>
              <td className="num px-2 py-2.5 text-right">{fmtInt(f.detections)}</td>
              <td className="num px-2 py-2.5 text-right">{f.active_days}</td>
              <td className="num py-2.5 pl-2 text-right">{f.median_frp == null ? "—" : `${f.median_frp.toFixed(1)} MW`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OverviewPage(_props: PageProps) {
  const { summary, health, incidents, facilities, loading } = useApp();
  const [model, setModel] = useState<any | null>(null);

  useEffect(() => {
    api.model().then(setModel).catch(() => undefined);
  }, []);

  if (loading && !summary) return <Spinner label="Loading detections" />;
  if (!summary) {
    return (
      <div className="p-6">
        <Callout tone="error" title="No data available">
          The dashboard could not load data from the API. Start the backend with <code>run_backend.bat</code> and reload this page.
        </Callout>
      </div>
    );
  }

  const t = summary.totals;
  const openIncidents = incidents
    .filter((i) => OPEN.includes(i.status))
    .sort((a, b) => SEVERITY_META[b.severity].rank - SEVERITY_META[a.severity].rank || b.updated_at.localeCompare(a.updated_at));
  const critical = openIncidents.filter((i) => i.severity === "CRITICAL").length;
  const activeFacilities = [...facilities].filter((f) => f.detections > 0).sort((a, b) => b.open_incidents - a.open_incidents || b.detections - a.detections).slice(0, 8);
  const report = model?.report;
  const real = report?.real_data_checks?.summary;
  const archive = report?.archive_data_checks?.summary;
  const labels = model?.analyst_reviews;
  const staticDataset = Boolean(health?.dataset?.static);

  if (t.detections === 0) {
    return (
      <div className="p-6">
        <Callout tone="info" title="No detections stored yet">
          Use <b>Sync FIRMS</b> to download the latest NASA FIRMS detections, or upload a FIRMS CSV on the Data page.
        </Callout>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 p-4 md:p-6">
      {staticDataset && (
        <Callout tone="info" title={health?.dataset?.label ?? "Archive dataset"}>
          A fixed week of real NASA FIRMS archive data in its own database, for demonstration: it is not live monitoring, and FIRMS sync, uploads and drills are off.
        </Callout>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat tone="sky" icon={Satellite} label="Detections" value={fmtInt(t.detections)} hint={`inside India · ${summary.window?.days ?? 0}-day window`} />
        <Stat tone="violet" icon={Factory} label="Industrial / extractive" value={fmtInt(t.industrial_detections)} hint={`${fmtPct(t.industrial_detections / t.detections)} of detections`} />
        <Stat tone="emerald" icon={Trees} label="Vegetation fires" value={fmtInt(t.vegetation_detections)} hint="forest and crop burning" />
        <Stat tone="rose" icon={Siren} label="Open incidents" value={fmtInt(openIncidents.length)} hint={critical ? `${critical} critical` : "none critical"} />
      </div>

      {summary.funnel && <FunnelPanel funnel={summary.funnel} />}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.7fr_1fr]">
        <Panel
          title="Detections per day"
          subtitle="By the classifier's decision"
          actions={
            <Button size="sm" icon={MapPin} onClick={() => navigate("map")}>
              Open map
            </Button>
          }
        >
          <DailyCategoryChart data={summary.daily} height={260} />
        </Panel>
        <Panel title="Source classes" subtitle="Click a class to see it on the map">
          <ClassBars classes={summary.classes.filter((c) => c.detections > 0)} onSelect={(code) => navigate("map", { class_code: code })} />
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <IncidentsPanel incidents={openIncidents} />
        {summary.regions?.length > 0 && <RegionsPanel regions={summary.regions} />}
      </div>

      <Disclosure title="More detail" subtitle="Time of detection, most active facilities, and data and model provenance">
        <div className="grid grid-cols-1 gap-8 xl:grid-cols-2">
          <div className="min-w-0">
            <SectionHeading hint="IST = UTC + 5:30">Time of detection (UTC)</SectionHeading>
            <p className="mb-2 text-[14px] text-muted">Industrial heat is mostly detected on night overpasses; crop fires mostly by day.</p>
            <HourlyChart data={summary.hourly_utc} />
          </div>
          <div className="min-w-0">
            <SectionHeading>Most active catalog facilities</SectionHeading>
            <FacilitiesTable facilities={activeFacilities} />
          </div>
        </div>
        <SectionHeading>Data and model provenance</SectionHeading>
        <KeyValues
          rows={[
            [staticDataset ? "Archive window" : "FIRMS window", fmtWindow(summary.window)],
            ["Latest detection", summary.latest_detection ? `${fmtUtc(summary.latest_detection)} (${fmtIst(summary.latest_detection)})` : "—"],
            ["Last ingestion", health?.last_ingestion ? `${health.last_ingestion.source}, ${timeAgo(health.last_ingestion.finished_at ?? health.last_ingestion.started_at)} (${fmtInt(health.last_ingestion.records_inserted)} new)` : "—"],
            ["Persistent sources", `${fmtInt(t.persistent_sources)} locations active on 2 or more days`],
            ["Awaiting verification", `${fmtInt(t.verification_pending)} detections with mixed or thin evidence`],
            ["Satellites", Object.entries(summary.satellites).map(([k, v]) => `${k} ${fmtInt(v)}`).join(" · ")],
            ["Industrial context", health ? `${fmtInt(health.reference_data.osm_features)} OpenStreetMap features, ${health.reference_data.catalog_facilities} catalog facilities` : "—"],
            ["Land cover", health ? `ESA WorldCover for ${fmtInt(health.reference_data.landcover_cache.cells_with_data)} footprints` : "—"],
            ["Model", health?.model.available ? `v${health.model.version}, trained ${fmtUtc(health.model.trained_at)}` : "not trained"],
            ["Alert policy", health?.alert_policy_version ? `v${health.alert_policy_version} (rules version + threshold fingerprint)` : "—"],
            ["Held-out simulated scenes", report?.simulation ? `${fmtPct(report.simulation.category_accuracy, 1)} industrial-vs-vegetation accuracy` : "—"],
            [
              "Real FIRMS checks",
              real
                ? `${fmtPct(real.mapped_industrial_agreement, 1)} of recurring detections at mapped industry called industrial (${fmtPct(real.mapped_industrial_agreement_without_maps, 1)} with maps hidden); ${fmtPct(real.vegetation_agreement, 1)} of forest/crop fires far from industry called vegetation`
                : "run backend/ml/evaluate_real.py",
            ],
            ...(archive?.nasa_static_source_agreement != null
              ? ([["Archive week vs NASA flag", `${fmtPct(archive.nasa_static_source_agreement, 1)} of NASA static heat sources shown as industrial; ${fmtPct(archive.nasa_presumed_vegetation_agreement, 1)} of presumed vegetation fires shown as vegetation`]] as [string, string][])
              : []),
            ["Analyst labels", labels?.reviews ? `${fmtInt(labels.labelled_detections)} detections at ${fmtInt(labels.labelled_locations)} locations; agreement with the model ${fmtPct(labels.location_agreement.share)}` : "none yet - see the Review queue"],
          ]}
        />
        <p className="mt-4 text-[14px] leading-relaxed text-muted">
          Real-data checks compare against independent map, land-cover and NASA evidence, not field-verified labels. See{" "}
          <button className="font-medium text-accent hover:underline" onClick={() => navigate("model")}>
            Model and what-if
          </button>{" "}
          for the full evaluation.
        </p>
      </Disclosure>
    </div>
  );
}

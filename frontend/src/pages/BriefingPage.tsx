import { useEffect, useState } from "react";
import { Download, Printer, RefreshCw } from "lucide-react";
import type { PageProps } from "../App";
import { Logo } from "../components/Logo";
import { Button, Callout, ClassBadge, SeverityBadge, Spinner, StatusBadge } from "../components/ui";
import { downloadBlob, api } from "../lib/api";
import { fmtInt, fmtIst, fmtNum, fmtPct, fmtUtc, fmtWindow } from "../lib/format";
import { errorMessage } from "../lib/store";
import { FIRE_APPROACH_META, INCIDENT_TYPE_LABELS, REASON_CODE_LABELS, type ClassCode } from "../lib/taxonomy";

export function BriefingPage(_props: PageProps) {
  const [briefing, setBriefing] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setBriefing(await api.briefing());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (error) return <div className="p-5"><Callout tone="error">{error}</Callout></div>;
  if (!briefing) return <Spinner label="Preparing briefing" />;
  const h = briefing.headline;
  const funnel = briefing.funnel;
  const real = briefing.model.real_data_checks;
  const archive = briefing.model.archive_data_checks;
  const labels = briefing.analyst_reviews;
  const codes = Object.entries(briefing.alert_policy?.reason_codes ?? {}) as [string, string][];

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 p-4 md:p-6">
      <div className="no-print flex flex-wrap gap-2">
        <Button icon={RefreshCw} loading={busy} onClick={load}>
          Regenerate
        </Button>
        <Button icon={Printer} onClick={() => window.print()}>
          Print / save as PDF
        </Button>
        <Button icon={Download} onClick={() => downloadBlob(new Blob([JSON.stringify(briefing, null, 2)], { type: "application/json" }), `thermal-briefing-${briefing.generated_at.slice(0, 10)}.json`)}>
          Download JSON
        </Button>
      </div>

      <article className="print-sheet mx-auto w-full max-w-4xl rounded-2xl border border-line bg-panel shadow-card px-8 py-7 text-[14.5px] leading-relaxed">
        <header className="border-b border-line pb-4">
          <Logo tone="light" size={40} subtitle="NASA FIRMS fire intelligence for India" />
          <h1 className="mt-5 text-[30px] font-bold leading-tight tracking-tight">Thermal anomaly briefing</h1>
          <div className="mt-1 text-ink-2">
            Observation window {fmtWindow(briefing.observation_window)} · generated {fmtUtc(briefing.generated_at)} ({fmtIst(briefing.generated_at)})
          </div>
          {briefing.dataset?.static && <div className="mt-1 font-medium text-accent">{briefing.dataset.label} - archive data for demonstration, not live monitoring.</div>}
        </header>

        <section className="mt-5">
          <h2 className="text-[18px] font-semibold">Summary</h2>
          <p className="mt-1 max-w-[70ch] text-ink-2">
            NASA FIRMS recorded <b>{fmtInt(h.detections)}</b> active-fire detections inside India in this window. The classifier attributes <b>{fmtInt(h.industrial_detections)}</b> ({fmtPct(h.industrial_detections / Math.max(h.detections, 1))}) to industrial or
            extractive heat sources and <b>{fmtInt(h.vegetation_detections)}</b> to vegetation fires. <b>{fmtInt(h.persistent_sources)}</b> locations were active on more than one day. {fmtInt(h.open_incidents)} incident(s) are open
            {h.critical_incidents ? `, ${h.critical_incidents} of them critical` : ""}; {fmtInt(h.detections_awaiting_review ?? h.detections_needing_verification)} detections carry mixed evidence and await an analyst's review.
            {funnel && (
              <>
                {" "}Grouped into {fmtInt(funnel.locations)} thermal locations, the feed leaves <b>{fmtInt(funnel.needing_attention)}</b> items for an analyst: {fmtInt(funnel.open_incidents)} open incident(s) and{" "}
                {fmtInt(funnel.review_locations)} location(s) with uncertain evidence.
              </>
            )}
          </p>
        </section>

        <section className="mt-5 overflow-x-auto">
          <h2 className="text-[18px] font-semibold">Detections by source type</h2>
          <table className="mt-2 w-full text-[14px]">
            <tbody className="divide-y divide-line">
              {briefing.by_class.map((c: any) => (
                <tr key={c.code}>
                  <td className="py-1.5">
                    <ClassBadge code={c.code as ClassCode} />
                  </td>
                  <td className="py-1.5 text-muted">{c.category === "industrial" ? "Industrial" : "Vegetation"}</td>
                  <td className="num py-1.5 text-right">{fmtInt(c.detections)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {briefing.regions?.length > 0 && (
          <section className="mt-5 overflow-x-auto">
            <h2 className="text-[18px] font-semibold">Focus regions</h2>
            <table className="mt-2 w-full text-[14px]">
              <thead className="text-left text-[12.5px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="py-1 font-medium">Region</th>
                  <th className="py-1 text-right font-medium">Detections</th>
                  <th className="py-1 text-right font-medium">Industrial</th>
                  <th className="py-1 text-right font-medium">Vegetation</th>
                  <th className="py-1 text-right font-medium">Open incidents</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {briefing.regions.map((r: any) => (
                  <tr key={r.id}>
                    <td className="py-1.5">{r.name}</td>
                    <td className="num py-1.5 text-right">{fmtInt(r.detections)}</td>
                    <td className="num py-1.5 text-right">{fmtInt(r.industrial)}</td>
                    <td className="num py-1.5 text-right">{fmtInt(r.vegetation)}</td>
                    <td className="num py-1.5 text-right">{r.open_incidents}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className="mt-5 overflow-x-auto">
          <h2 className="text-[18px] font-semibold">Open incidents</h2>
          {briefing.open_incidents.length === 0 ? (
            <p className="text-muted">None.</p>
          ) : (
            <table className="mt-2 w-full text-[14px]">
              <tbody className="divide-y divide-line">
                {briefing.open_incidents.map((i: any) => (
                  <tr key={i.id} className="align-top">
                    <td className="py-2 pr-2">
                      <SeverityBadge severity={i.severity} />
                    </td>
                    <td className="py-2 pr-2">
                      <StatusBadge status={i.status} />
                    </td>
                    <td className="py-2">
                      <div className="font-medium text-ink">
                        {i.title}
                        {i.is_drill ? " (drill)" : ""}
                      </div>
                      <div className="text-muted">{INCIDENT_TYPE_LABELS[i.incident_type] ?? i.incident_type} · {i.summary}</div>
                      {i.reason_codes?.length > 0 && <div className="text-ink-2">Reasons: {i.reason_codes.map((code: string) => REASON_CODE_LABELS[code] ?? code).join(", ")}</div>}
                      {i.details?.fire_approach && (
                        <div className={i.details.fire_approach.status === "approaching" ? "font-medium text-crit" : "text-ink-2"}>
                          {FIRE_APPROACH_META[i.details.fire_approach.status]?.label}: {i.details.fire_approach.summary}
                        </div>
                      )}
                      {i.details?.wind?.summary && <div className="text-ink-2">{i.details.wind.summary}</div>}
                      {i.imagery_evidence && <div className="text-ink-2">Sentinel-2 check: {i.imagery_evidence.headline}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="mt-5 overflow-x-auto">
          <h2 className="text-[18px] font-semibold">Most active catalog facilities</h2>
          <table className="mt-2 w-full text-[14px]">
            <thead className="text-left text-[12.5px] uppercase tracking-wide text-muted">
              <tr>
                <th className="py-1 font-medium">Facility</th>
                <th className="py-1 text-right font-medium">Detections</th>
                <th className="py-1 text-right font-medium">Days</th>
                <th className="py-1 text-right font-medium">Median FRP</th>
                <th className="py-1 text-right font-medium">Open incidents</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {briefing.most_active_facilities.map((f: any) => (
                <tr key={f.id}>
                  <td className="py-1.5">
                    {f.name} <span className="text-muted">· {f.state}</span>
                  </td>
                  <td className="num py-1.5 text-right">{fmtInt(f.detections)}</td>
                  <td className="num py-1.5 text-right">{f.active_days}</td>
                  <td className="num py-1.5 text-right">{fmtNum(f.median_frp)} MW</td>
                  <td className="num py-1.5 text-right">{f.open_incidents}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-5 overflow-x-auto">
          <h2 className="text-[18px] font-semibold">Most persistent thermal sources</h2>
          <table className="mt-2 w-full text-[14px]">
            <thead className="text-left text-[12.5px] uppercase tracking-wide text-muted">
              <tr>
                <th className="py-1 font-medium">Source type</th>
                <th className="py-1 font-medium">Location</th>
                <th className="py-1 text-right font-medium">Active days</th>
                <th className="py-1 text-right font-medium">Median / max FRP</th>
                <th className="py-1 text-right font-medium">Trend</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {briefing.top_persistent_sources.map((s: any) => (
                <tr key={s.id}>
                  <td className="py-1.5">{s.class_label}</td>
                  <td className="num py-1.5">
                    {s.latitude.toFixed(3)}, {s.longitude.toFixed(3)}
                  </td>
                  <td className="num py-1.5 text-right">{s.active_days}</td>
                  <td className="num py-1.5 text-right">
                    {fmtNum(s.frp_median)} / {fmtNum(s.frp_max)} MW
                  </td>
                  <td className="py-1.5 text-right">{String(s.trend).replace("_", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-5">
          <h2 className="text-[18px] font-semibold">Method, evidence and limitations</h2>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-2">
            <li>Detections: {briefing.data_provenance.detections}.</li>
            <li>Industrial context: {briefing.data_provenance.industrial_context}.</li>
            <li>Land cover: {briefing.data_provenance.land_cover}.</li>
            {briefing.data_provenance.satellite_imagery && <li>Satellite imagery: {briefing.data_provenance.satellite_imagery}.</li>}
            {briefing.data_provenance.weather && <li>Weather: {briefing.data_provenance.weather}.</li>}
            <li>
              Classifier {briefing.model.metadata?.version ? `v${briefing.model.metadata.version}` : ""}: {fmtPct(briefing.model.simulation_category_accuracy, 1)} industrial-versus-vegetation accuracy on held-out simulated scenes
              {real ? `; on real detections, ${fmtPct(real.mapped_industrial_agreement, 1)} agreement at mapped industrial sites and ${fmtPct(real.vegetation_agreement, 1)} for forest and crop fires far from industry` : ""}
              {archive?.nasa_static_source_agreement != null ? `; on the archive week, ${fmtPct(archive.nasa_static_source_agreement, 1)} of NASA's static heat sources were classified industrial` : ""}.
            </li>
            {briefing.alert_policy && (
              <li>
                Alerts follow alert policy v{briefing.alert_policy.version}
                {codes.length > 0 ? `; reason codes above: ${codes.map(([code, description]) => `${code} (${description})`).join("; ")}` : ""}.
              </li>
            )}
            {labels && (
              <li>
                Analyst labels: {labels.reviews ? `${fmtInt(labels.labelled_detections)} detections at ${fmtInt(labels.labelled_locations)} locations, agreeing with the model at ${fmtPct(labels.location_agreement.share)} of labelled locations` : "none recorded yet"}.
              </li>
            )}
            {briefing.limitations.map((l: string) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </section>
      </article>
    </div>
  );
}

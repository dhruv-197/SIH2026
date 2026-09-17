import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ArrowRight, Download, Play } from "lucide-react";
import type { PageProps } from "../App";
import { ConfusionMatrix, ContributionList, LandcoverBar, ProbabilityBars } from "../components/charts";
import { Button, Callout, CategoryBadge, ClassBadge, Field, Panel, SectionHeading, Spinner, Stat, cx, inputClass, Disclosure } from "../components/ui";
import { api, downloadBlob } from "../lib/api";
import { fmtInt, fmtNum, fmtPct, fmtWindow } from "../lib/format";
import { navigate } from "../lib/router";
import { errorMessage, useApp } from "../lib/store";
import { CLASS_META, subtypeLabel, type ClassCode } from "../lib/taxonomy";
import type { ReviewStats, WhatIfResult } from "../lib/types";

const FEATURE_LABELS: Record<string, string> = {
  frp_log: "Fire radiative power",
  bright_mir: "MIR brightness temperature",
  bright_tir: "TIR brightness temperature",
  delta_t: "MIR − TIR temperature difference",
  mir_saturated: "MIR saturation",
  is_night: "Night overpass",
  is_modis: "MODIS sensor",
  pixel_area_km2: "Pixel size",
  persistence_days: "Days with detections within 750 m",
  persistence_ratio: "Share of observed days with detections",
  detections_750m: "Detections within 750 m",
  night_fraction_750m: "Night share at the location",
  frp_median_750m_log: "Typical FRP at the location",
  frp_cv_750m: "FRP variability at the location",
  concurrent_pixels_2km: "Simultaneous detections within 2 km",
  event_cells_5km: "Active cells within 5 km (3 days)",
  event_days_5km: "Active days within 5 km (3 days)",
  spread_km_day: "Day-to-day movement of fire activity",
  isolation_other_cells_5km: "Other active cells within 5 km",
  dist_oil_gas_km: "Distance to mapped oil & gas",
  dist_heavy_industry_km: "Distance to mapped heavy industry",
  dist_mining_km: "Distance to mapped mine",
  inside_industrial: "Inside mapped industrial polygon",
  lc_tree: "Tree cover fraction",
  lc_shrub_grass: "Shrub / grass fraction",
  lc_crop: "Cropland fraction",
  lc_built: "Built-up fraction",
  lc_bare: "Bare ground fraction",
  lc_water_wetland: "Water / wetland fraction",
  lc_available: "Land cover available",
};

const FAMILY_LABELS: Record<string, string> = {
  flare_refinery_mapped: "Gas flares at a mapped refinery",
  flare_unmapped: "Gas flares at an unmapped site",
  flare_upset_mapped: "Flaring upset at a mapped oil & gas plant",
  flare_upset_unmapped: "Flaring upset at an unmapped plant",
  oil_field_wells: "Oil field well pads",
  heavy_plant_mapped: "Mapped steel / power / cement plant",
  heavy_plant_unmapped: "Unmapped heavy industrial plant",
  industrial_fire_mapped: "Accidental fire inside a mapped plant",
  brick_kilns_cropland: "Brick kilns among cropland",
  coal_fire_mapped: "Coal fires in a mapped mine",
  coal_fire_unmapped: "Coal fires, mine not mapped",
  forest_fire: "Forest fire",
  forest_fire_near_industry: "Forest fire near industry",
  vegetation_fire_on_premises: "Vegetation fire inside plant or mine premises",
  grass_scrub_fire: "Grass / scrub fire",
  crop_burning: "Crop residue burning",
  crop_burning_near_industry: "Crop burning next to industry",
  plantation_burning: "Plantation burning",
};

const PRESETS = [
  { label: "Night hotspot at Numaligarh refinery, Assam", values: { latitude: 26.62, longitude: 93.73, frp: 3.5, bright_ti4: 330, bright_ti5: 292, daynight: "N" } },
  { label: "Daytime fire in Uttarakhand forest", values: { latitude: 30.2, longitude: 79.2, frp: 25, bright_ti4: 350, bright_ti5: 305, daynight: "D" } },
  { label: "Paddy stubble fire, Punjab", values: { latitude: 30.25, longitude: 75.84, frp: 6, bright_ti4: 335, bright_ti5: 302, daynight: "D" } },
  { label: "Hotspot inside Bhilai Steel Plant", values: { latitude: 21.19, longitude: 81.4, frp: 3, bright_ti4: 326, bright_ti5: 294, daynight: "N" } },
];

function WhatIfPanel() {
  const { notify } = useApp();
  const [form, setForm] = useState({ latitude: 26.62, longitude: 93.73, frp: 3.5, bright_ti4: 330, bright_ti5: 292, daynight: "N", instrument: "VIIRS" });
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [busy, setBusy] = useState(false);

  function update(key: string, value: string | number) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      setResult(await api.whatIf(form));
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="What-if analysis"
      subtitle="Classify a hypothetical detection with the deployed pipeline. Stored detections near the location are used as context (persistence, nearby fires); nothing is saved."
    >
      <div className="mb-3 flex flex-wrap gap-2">
        {PRESETS.map((preset) => (
          <button key={preset.label} className="rounded-lg border border-line px-2 py-1 text-[13.5px] text-ink-2 hover:bg-sunk" onClick={() => setForm((current) => ({ ...current, ...preset.values }))}>
            {preset.label}
          </button>
        ))}
      </div>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Field label="Latitude">
          <input className={inputClass} type="number" step="any" min={-90} max={90} value={form.latitude} onChange={(e) => update("latitude", Number(e.target.value))} required />
        </Field>
        <Field label="Longitude">
          <input className={inputClass} type="number" step="any" min={-180} max={180} value={form.longitude} onChange={(e) => update("longitude", Number(e.target.value))} required />
        </Field>
        <Field label="FRP (MW)">
          <input className={inputClass} type="number" step="any" min={0} value={form.frp} onChange={(e) => update("frp", Number(e.target.value))} required />
        </Field>
        <Field label="MIR brightness (K)">
          <input className={inputClass} type="number" step="any" min={200} max={550} value={form.bright_ti4} onChange={(e) => update("bright_ti4", Number(e.target.value))} required />
        </Field>
        <Field label="TIR brightness (K)">
          <input className={inputClass} type="number" step="any" min={150} max={420} value={form.bright_ti5} onChange={(e) => update("bright_ti5", Number(e.target.value))} required />
        </Field>
        <Field label="Overpass">
          <select className={inputClass} value={form.daynight} onChange={(e) => update("daynight", e.target.value)}>
            <option value="D">Day</option>
            <option value="N">Night</option>
          </select>
        </Field>
        <Field label="Sensor">
          <select className={inputClass} value={form.instrument} onChange={(e) => update("instrument", e.target.value)}>
            <option value="VIIRS">VIIRS 375 m</option>
            <option value="MODIS">MODIS 1 km</option>
          </select>
        </Field>
        <div className="flex items-end">
          <Button type="submit" variant="primary" icon={Play} loading={busy} className="w-full">
            Classify
          </Button>
        </div>
      </form>

      {result && (
        <div className="mt-4 grid grid-cols-1 gap-5 border-t border-line pt-4 text-[14.5px] lg:grid-cols-2">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <ClassBadge code={result.classification.class_code} />
              <CategoryBadge category={result.classification.category} confidence={result.classification.confidence_pct} />
            </div>
            {result.classification.verification_required && (
              <Callout tone="warn" className="mt-2" title="Would be flagged for verification">
                {result.classification.verification_reasons.join(". ")}.
              </Callout>
            )}
            <SectionHeading>Evidence</SectionHeading>
            <ul className="list-disc space-y-1 pl-5 text-ink-2">
              {result.evidence.statements.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
            <div className="mt-2 text-[13.5px] text-muted">{result.stored_detections_used_as_context} stored detections within ~10 km were used as context.</div>
            {result.landcover.available && result.landcover.fractions && (
              <>
                <SectionHeading>Land cover</SectionHeading>
                <LandcoverBar fractions={result.landcover.fractions} />
              </>
            )}
          </div>
          <div>
            <SectionHeading>Class probabilities</SectionHeading>
            <ProbabilityBars probabilities={result.classification.probabilities} highlight={result.classification.class_code} />
            <SectionHeading>Strongest model evidence</SectionHeading>
            <ContributionList items={result.contributions} />
          </div>
        </div>
      )}
    </Panel>
  );
}

function CheckCard({ title, detail, value, caption, note }: { title: string; detail: string; value: number | null | undefined; caption: string; note?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-slate-50 p-4">
      <div className="text-[14px] font-semibold text-ink">{title}</div>
      <div className="text-[13.5px] text-muted">{detail}</div>
      <div className="num mt-2 font-display text-[32px] font-semibold">{fmtPct(value, 1)}</div>
      <div className="text-[14px] text-ink-2">{caption}</div>
      {note && <div className="mt-1 text-[14px] text-ink-2">{note}</div>}
    </div>
  );
}

function ArchiveChecksPanel({ checks }: { checks: any }) {
  const a = checks.A_mapped_industrial_sites;
  const b = checks.B_vegetation_far_from_industry;
  const c = checks.C_nasa_static_source_flag;
  return (
    <Panel
      title="Checks on the archive week"
      subtitle={`${fmtInt(checks.detections_evaluated)} real detections, ${fmtWindow(checks.observation_window)}, from NASA FIRMS standard processing in the focus regions - a season with crop and forest fires. Independent evidence, not field-verified ground truth.`}
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <CheckCard
          title="Recurring detections inside mapped industry"
          detail="active on ≥ 3 days inside an OpenStreetMap industrial or mining polygon"
          value={a.share_predicted_industrial}
          caption={`classified industrial · n = ${fmtInt(a.detections)}`}
          note={
            <>
              With every map feature hidden: <b>{fmtPct(a.ablation_without_map_features_share_industrial, 1)}</b>
            </>
          }
        />
        <CheckCard
          title="Single-day fires in forest or cropland far from industry"
          detail="WorldCover tree or cropland ≥ 60 %, ≥ 10 km from mapped industry"
          value={b.share_predicted_vegetation}
          caption={`classified vegetation fire · n = ${fmtInt(b.detections)}`}
          note={
            <>
              With land cover hidden: <b>{fmtPct(b.ablation_without_landcover_share_vegetation, 1)}</b>
            </>
          }
        />
        {c && (
          <CheckCard
            title="NASA's static-source flag"
            detail="FIRMS type 2, 'other static land source', derived by NASA from years of recurrence"
            value={c.static_land_source.share_shown_industrial}
            caption={`shown as industrial · n = ${fmtInt(c.static_land_source.detections)}`}
            note={
              <>
                Of NASA's presumed vegetation fires (type 0), <b>{fmtPct(c.presumed_vegetation_fire.share_shown_vegetation, 1)}</b> are shown as vegetation (n = {fmtInt(c.presumed_vegetation_fire.detections)}).
              </>
            }
          />
        )}
      </div>
      {c && (
        <p className="mt-3 text-[13.5px] leading-relaxed text-muted">
          {c.note} NASA flags only locations with a long record of heat, so new or intermittent industrial sources count as "presumed vegetation" in its flag.
        </p>
      )}
    </Panel>
  );
}

function AnalystLabelsPanel({ stats }: { stats: ReviewStats }) {
  const { notify } = useApp();
  const [busy, setBusy] = useState(false);

  async function exportLabels() {
    setBusy(true);
    try {
      downloadBlob(await api.exportLabels(), "analyst_labels.csv");
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Analyst labels"
      subtitle="The start of a real validation set: labels from the review queue, stored next to the model's output and exported as training rows with their evidence"
      actions={
        <>
          <Button size="sm" icon={Download} loading={busy} disabled={!stats.reviews} onClick={exportLabels}>
            Export labels (CSV)
          </Button>
          <Button size="sm" icon={ArrowRight} onClick={() => navigate("review")}>
            Review queue
          </Button>
        </>
      }
    >
      {stats.reviews === 0 ? (
        <div className="text-[14.5px] text-ink-2">
          No labels yet. {fmtInt(stats.pending_flagged_detections)} flagged detections are waiting in the review queue; every label becomes a checked example for the next model.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Labelled detections" value={fmtInt(stats.labelled_detections)} hint={`at ${fmtInt(stats.labelled_locations)} locations`} />
          <Stat label="Location agreement" value={fmtPct(stats.location_agreement.share)} hint={`${stats.location_agreement.agree} of ${stats.location_agreement.compared} with a category`} />
          <Stat label="Detection agreement" value={fmtPct(stats.detection_agreement.share)} hint={`${fmtInt(stats.detection_agreement.agree)} of ${fmtInt(stats.detection_agreement.compared)}`} />
          <Stat label="Still to review" value={fmtInt(stats.pending_flagged_detections)} hint="flagged detections without a label" />
        </div>
      )}
      <p className="mt-3 text-[13.5px] text-muted">{stats.note}</p>
    </Panel>
  );
}

export function ModelPage(_props: PageProps) {
  const [data, setData] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.model().then(setData).catch((e) => setError(errorMessage(e)));
  }, []);

  const report = data?.report;
  const sim = report?.simulation;
  const real = report?.real_data_checks;
  const archive = report?.archive_data_checks;
  const importance: { feature: string; gain: number }[] = report?.feature_importance_gain ?? [];
  const maxGain = Math.max(...importance.map((f) => f.gain), 1);

  const classificationSteps = (
        <ol className="max-w-5xl list-decimal space-y-1.5 pl-5 text-[14.5px] leading-relaxed text-ink-2">
          <li>Each NASA FIRMS record is validated (no invented defaults) and kept only if it falls inside India.</li>
          <li>
            30 features are measured from observations alone: radiometry (FRP, brightness temperatures, day/night); recurrence within 750 m across the observation window; the pattern of surrounding fire
            activity; distance to real OpenStreetMap oil &amp; gas, heavy industry and mining features; and ESA WorldCover fractions in the 375 m pixel footprint.
          </li>
          <li>A gradient-boosted tree model gives a probability for each of five source types. The industrial-versus-vegetation decision uses the summed probabilities; the subtype is chosen within that group.</li>
          <li>Locations with detections on two or more days are grouped into persistent sources and classified on all their detections together.</li>
          <li>
            Alerts are statistical rules with visible triggers: an FRP excursion far above a source's own history becomes a suspected industrial accident (critical); a
            large cluster of new heat at a mapped plant becomes a possible fire or emergency flaring alert; a vegetation fire of some size near critical infrastructure
            becomes a cross-alert, even when its classification is uncertain.
          </li>
          <li>
            Every alert carries machine-readable reason codes and the version of the alert policy (rules plus thresholds) that raised it. For a fire near a facility, the
            closest detection on each day shows whether the front is approaching: an approaching front makes the cross-alert critical, and the wind at the overpass is recorded.
          </li>
          <li>
            Open incidents are checked against Sentinel-2 imagery: shortwave-infrared hot spots confirm real heat, and a burn scar (a drop in the normalized burn ratio) points to a
            vegetation fire. A finding that contradicts the classification flags the detection for verification.
          </li>
          <li>
            Results with mixed or thin evidence go to a review queue instead of the alert queue. Analysts' labels are stored next to the model's output, never over it, and export as
            training rows.
          </li>
        </ol>
  );

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 p-4 md:p-6">
      {error && <Callout tone="error">{error}</Callout>}
      {!data && !error && <Spinner label="Loading evaluation report" />}
      {data && !report && <Callout tone="warn">No evaluation report yet. Run <code>py backend/ml/train.py</code> and <code>py backend/ml/evaluate_real.py</code>.</Callout>}

      {report && sim && (
        <>
          <Callout tone="warn" title="How to read these numbers">
            {report.important_caveat}
          </Callout>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <Stat tone="indigo" label="Industrial vs vegetation" value={fmtPct(sim.category_accuracy, 1)} hint={`held-out simulated scenes (${fmtInt(sim.scenes)})`} />
            <Stat label="Source type macro F1" value={fmtNum(sim.class_macro_f1, 3)} hint="across 5 source types" />
            <Stat label="Single-day locations" value={fmtPct(sim.by_evidence.single_day_location.category_accuracy, 1)} hint="category accuracy without recurrence" />
            <Stat label="Flagged for verification" value={fmtPct(sim.verification_policy.flag_rate, 1)} hint={`${fmtPct(sim.verification_policy.category_accuracy_when_not_flagged, 1)} correct when not flagged`} />
            <Stat label="Calibration error" value={fmtNum(sim.calibration.category_expected_calibration_error, 3)} hint="expected calibration error, lower is better" />
          </div>

          {real && (
            <Panel title="Checks on real NASA FIRMS detections" subtitle={`${fmtInt(real.detections_evaluated)} detections, ${fmtWindow(real.observation_window)}. Proxy labels come from independent evidence; they are not field-verified ground truth.`}>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-line bg-slate-50 p-4">
                  <div className="text-[14px] font-semibold text-ink">Recurring detections inside mapped industry</div>
                  <div className="text-[13.5px] text-muted">active on ≥ 3 days, inside an OpenStreetMap industrial or mining polygon (or ≤ 500 m from a flare, well or kiln)</div>
                  <div className="num mt-2 font-display text-[32px] font-semibold">{fmtPct(real.A_mapped_industrial_sites.share_predicted_industrial, 1)}</div>
                  <div className="text-[14px] text-ink-2">classified industrial · n = {fmtInt(real.A_mapped_industrial_sites.detections)}</div>
                  <div className="mt-1 text-[14px] text-ink-2">
                    With every map feature hidden from the model: <b>{fmtPct(real.A_mapped_industrial_sites.ablation_without_map_features_share_industrial, 1)}</b> - the model does not simply read the map.
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5 text-[13px] text-muted">
                    {Object.entries(real.A_mapped_industrial_sites.feature_subtypes ?? {}).map(([k, v]) => (
                      <span key={k} className="rounded-lg bg-sunk px-1.5 py-0.5">
                        {subtypeLabel(k)} {String(v)}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-line bg-slate-50 p-4">
                  <div className="text-[14px] font-semibold text-ink">Single-day fires in forest or cropland far from industry</div>
                  <div className="text-[13.5px] text-muted">WorldCover tree or cropland ≥ 60 %, ≥ 10 km from any mapped industrial feature</div>
                  <div className="num mt-2 font-display text-[32px] font-semibold">{fmtPct(real.B_vegetation_far_from_industry.share_predicted_vegetation, 1)}</div>
                  <div className="text-[14px] text-ink-2">classified vegetation fire · n = {fmtInt(real.B_vegetation_far_from_industry.detections)}</div>
                  <div className="mt-1 text-[14px] text-ink-2">
                    With land cover hidden from the model: <b>{fmtPct(real.B_vegetation_far_from_industry.ablation_without_landcover_share_vegetation, 1)}</b>
                  </div>
                </div>
              </div>
              <details className="mt-3 text-[14px] text-ink-2">
                <summary className="cursor-pointer text-accent">Method and limitations</summary>
                <p className="mt-2 whitespace-pre-line leading-relaxed">{real.method}</p>
              </details>
            </Panel>
          )}

          {archive && <ArchiveChecksPanel checks={archive} />}
        </>
      )}

      {data?.analyst_reviews && <AnalystLabelsPanel stats={data.analyst_reviews} />}

      <WhatIfPanel />

      <Disclosure title="How a detection is classified" subtitle="From a NASA FIRMS record to an alert, in eight steps">
        {classificationSteps}
      </Disclosure>

      {report && sim && (
        <Disclosure title="Simulation evaluation details" subtitle="Per source type, confusion matrices, scenario families and the most influential features">
          <div className="grid grid-cols-1 gap-8 xl:grid-cols-2">
            <div className="min-w-0">
              <SectionHeading hint={`out-of-fold, ${fmtInt(sim.detections)} simulated detections`}>Per source type</SectionHeading>
              <div className="overflow-x-auto">
              <table className="w-full text-[14px]">
                <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Source type</th>
                    <th className="px-2 py-2 text-right font-medium">Precision</th>
                    <th className="px-2 py-2 text-right font-medium">Recall</th>
                    <th className="px-2 py-2 text-right font-medium">F1</th>
                    <th className="px-4 py-2 text-right font-medium">Detections</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(sim.per_class as Record<string, any>).map(([code, m]) => (
                    <tr key={code}>
                      <td className="px-4 py-2">
                        <ClassBadge code={code as ClassCode} compact />
                      </td>
                      <td className="num px-2 py-2 text-right">{fmtNum(m.precision, 3)}</td>
                      <td className="num px-2 py-2 text-right">{fmtNum(m.recall, 3)}</td>
                      <td className="num px-2 py-2 text-right">{fmtNum(m.f1, 3)}</td>
                      <td className="num px-4 py-2 text-right">{fmtInt(m.support)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            </div>
            <div className="min-w-0">
              <SectionHeading hint="held-out simulated scenes">Confusion matrices</SectionHeading>
              <ConfusionMatrix labels={sim.category_confusion.labels} matrix={sim.category_confusion.matrix} labelFor={(l) => (l === "industrial" ? "Industrial" : "Vegetation")} />
              <div className="mt-4" />
              <ConfusionMatrix labels={sim.class_confusion.labels} matrix={sim.class_confusion.matrix} labelFor={(l) => CLASS_META[l as ClassCode]?.short ?? l} />
            </div>
            <div className="min-w-0">
              <SectionHeading hint="hard families are built to confuse the model">Scenario families</SectionHeading>
              <div className="overflow-x-auto">
              <table className="w-full text-[14px]">
                <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
                  <tr>
                    <th className="px-4 py-2 font-medium">Scenario</th>
                    <th className="px-2 py-2 text-right font-medium">Category acc.</th>
                    <th className="px-2 py-2 text-right font-medium">Type acc.</th>
                    <th className="px-4 py-2 text-right font-medium">Flagged</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(sim.per_family as Record<string, any>)
                    .sort((a, b) => Number(b[1].hard_case) - Number(a[1].hard_case) || a[1].class_accuracy - b[1].class_accuracy)
                    .map(([family, m]) => (
                      <tr key={family}>
                        <td className="px-4 py-2">
                          {FAMILY_LABELS[family] ?? family}
                          {m.hard_case && <span className="ml-1.5 rounded-lg bg-warn-soft px-1 text-[12px] font-semibold text-warn">hard</span>}
                        </td>
                        <td className="num px-2 py-2 text-right">{fmtPct(m.category_accuracy, 1)}</td>
                        <td className={cx("num px-2 py-2 text-right", m.class_accuracy < 0.8 && "font-semibold text-warn")}>{fmtPct(m.class_accuracy, 1)}</td>
                        <td className="num px-4 py-2 text-right">{fmtPct(m.verification_flag_rate, 1)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              </div>
            </div>
            <div className="min-w-0">
              <SectionHeading hint="total gain in the trained model">Most influential features</SectionHeading>
              <div className="flex flex-col gap-2">
                {importance.slice(0, 14).map((f) => (
                  <div key={f.feature} className="grid grid-cols-[210px_1fr] items-center gap-3 text-[14px]">
                    <span className="truncate text-ink-2">{FEATURE_LABELS[f.feature] ?? f.feature}</span>
                    <div className="h-2 rounded-sm bg-sunk">
                      <div className="h-full rounded-sm bg-accent" style={{ width: `${(f.gain / maxGain) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Disclosure>
      )}
    </div>
  );
}

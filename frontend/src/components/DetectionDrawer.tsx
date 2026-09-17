import { useEffect, useState, type ReactNode } from "react";
import { ExternalLink, MapPin, Radar, RefreshCw, Satellite, Search, Wind } from "lucide-react";
import { api } from "../lib/api";
import { fmtCoord, fmtDay, fmtIst, fmtNum, fmtPct, fmtUtc } from "../lib/format";
import { navigate } from "../lib/router";
import { errorMessage, useApp } from "../lib/store";
import {
  DATA_SOURCE_LABELS,
  FIRE_APPROACH_META,
  FIRMS_TYPE_LABELS,
  IMAGERY_STATUS_LABELS,
  INCIDENT_TYPE_LABELS,
  LOCATION_KIND_LABELS,
  REASON_CODE_LABELS,
  reviewLabel,
  subtypeLabel,
  type Category,
} from "../lib/taxonomy";
import type { Analysis, DetectionDetail, FeatureRef, FireApproach, ImageryEvidence, ImageryItem, ImageryResult, WindInfo } from "../lib/types";
import { ContributionList, LandcoverBar, ProbabilityBars } from "./charts";
import { ReviewPanel } from "./ReviewPanel";
import { Button, Callout, CategoryBadge, ClassBadge, Drawer, KeyValues, ReasonCodeChips, SectionHeading, SeverityBadge, Spinner, StatusBadge, VerifyBadge, cx } from "./ui";

function FeatureLine({ feature, prefix }: { feature: FeatureRef; prefix: string }) {
  return (
    <span>
      {prefix} {feature.name ? <b>{feature.name}</b> : subtypeLabel(feature.subtype)} ({subtypeLabel(feature.subtype)}
      {feature.distance_km > 0 ? `, ${fmtNum(feature.distance_km, 2)} km` : ""})
      {feature.osm_url && (
        <a href={feature.osm_url} target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center gap-0.5 text-accent hover:underline">
          {feature.feature_id} <ExternalLink size={11} />
        </a>
      )}
    </span>
  );
}

function SceneCard({ item, label }: { item: ImageryItem; label: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-line p-2">
      <div className="text-[13.5px] font-semibold">{label}</div>
      <div className="grid grid-cols-2 gap-1.5">
        {item.chip_url && <img src={item.chip_url} alt={`${label} true colour`} className="aspect-square w-full rounded-sm bg-sunk object-cover" loading="lazy" />}
        {item.swir_chip_url && <img src={item.swir_chip_url} alt={`${label} SWIR`} className="aspect-square w-full rounded-sm bg-sunk object-cover" loading="lazy" />}
        {!item.chip_url && item.preview_url && <img src={item.preview_url} alt={`${label} preview`} className="col-span-2 max-h-48 w-full rounded-sm bg-sunk object-contain" loading="lazy" />}
      </div>
      {item.chip_url && <div className="text-[12.5px] text-muted">Left: true colour · right: SWIR false colour (B12/B8A/B4), 4 × 4 km around the detection</div>}
      <div className="num text-[13px] text-ink-2">
        {fmtUtc(item.datetime)} · {item.days_from_detection > 0 ? "+" : ""}
        {item.days_from_detection} days{item.cloud_cover_pct != null ? ` · cloud ${fmtNum(item.cloud_cover_pct, 0)}%` : ""}
      </div>
      <a href={item.stac_url} target="_blank" rel="noreferrer" className="truncate text-[12.5px] text-accent hover:underline">
        {item.id}
      </a>
    </div>
  );
}

function ImageryEvidenceCard({ evidence, category, busy, onRecheck }: { evidence: ImageryEvidence; category: Category; busy: boolean; onRecheck?: () => void }) {
  const agrees = evidence.supports ? evidence.supports === category : null;
  const tone = evidence.status === "error" ? "error" : agrees === false ? "warn" : agrees ? "success" : "info";
  const title = agrees === null ? (IMAGERY_STATUS_LABELS[evidence.status] ?? evidence.status) : agrees ? "Imagery agrees with the classification" : evidence.supports === "industrial" ? "Imagery points to an industrial heat source" : "Imagery points to a vegetation fire";
  const hotspot = evidence.hotspot;
  const burn = evidence.burn_scar;
  return (
    <div className="flex flex-col gap-2">
      <Callout tone={tone} title={title}>
        {evidence.headline}
      </Callout>
      {(hotspot || burn) && (
        <KeyValues
          rows={[
            [
              "Hot spot (SWIR)",
              hotspot?.detected
                ? `${hotspot.hot_pixels} hot pixels on ${hotspot.date} (max NHI ${fmtNum(hotspot.max_nhi_swir, 2)})`
                : hotspot?.detected === false
                  ? "none in the clear scenes within 12 days"
                  : `not testable: ${hotspot?.reason ?? "no scene"}`,
            ],
            ["Dates with heat", hotspot?.dates_with_heat?.length ? `${hotspot.dates_with_heat.join(", ")}${hotspot.persistent ? " (persistent)" : ""}` : "none"],
            [
              "Burn scar (NBR)",
              !burn || burn.detected == null
                ? `not testable: ${burn?.reason ?? "no scene"}`
                : `dNBR ${fmtNum(burn.dnbr, 2)}${burn.dnbr_darkest_5pct != null ? ` (darkest 5%: ${fmtNum(burn.dnbr_darkest_5pct, 2)})` : ""} from ${burn.before_date} to ${burn.after_date}: ${burn.detected ? "burn scar" : "no burn scar"}`,
            ],
            ["Measured", `${evidence.scenes?.length ?? 0} Sentinel-2 scenes · checked ${fmtUtc(evidence.checked_at)}`],
          ]}
        />
      )}
      {evidence.chips && (
        <div className="grid grid-cols-2 gap-1.5">
          <img src={evidence.chips.true_colour} alt="Sentinel-2 true colour around the detection" className="aspect-square w-full rounded-sm bg-sunk object-cover" loading="lazy" />
          <img src={evidence.chips.swir} alt="Sentinel-2 shortwave-infrared false colour around the detection" className="aspect-square w-full rounded-sm bg-sunk object-cover" loading="lazy" />
        </div>
      )}
      {evidence.scenes && evidence.scenes.length > 0 && (
        <details className="text-[13.5px] text-ink-2">
          <summary className="cursor-pointer text-accent">Scene measurements</summary>
          <table className="mt-1 w-full">
            <tbody className="divide-y divide-line">
              {evidence.scenes.map((s) => (
                <tr key={s.id}>
                  <td className="py-1 pr-2">{s.date}</td>
                  <td className="num py-1 pr-2">
                    {s.days_from_detection > 0 ? "+" : ""}
                    {s.days_from_detection} d
                  </td>
                  <td className="num py-1 pr-2">cloud {fmtPct(s.cloud_fraction)}</td>
                  <td className="num py-1 pr-2">{s.hot_pixels} hot px</td>
                  <td className="num py-1">NBR {s.nbr_land == null ? "—" : fmtNum(s.nbr_land, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {evidence.method && <div className="text-[12.5px] leading-snug text-muted">{evidence.method}</div>}
      {onRecheck && (
        <div>
          <Button size="sm" variant="ghost" icon={RefreshCw} loading={busy} onClick={onRecheck}>
            Re-check imagery
          </Button>
        </div>
      )}
    </div>
  );
}

function FireApproachCard({ approach }: { approach: FireApproach }) {
  const meta = FIRE_APPROACH_META[approach.status] ?? FIRE_APPROACH_META.insufficient_data;
  return (
    <Callout tone={meta.tone} className="mt-2" title={meta.label}>
      <div>{approach.summary}.</div>
      {approach.front_by_day.length > 1 && (
        <div className="num mt-1 text-[13.5px] text-ink-2">
          Closest detection per day: {approach.front_by_day.map((day) => `${fmtDay(day.date)} ${fmtNum(day.closest_km, 1)} km`).join(" → ")}
        </div>
      )}
      <div className="mt-1 text-[13px] text-muted">Measured from 375 m detections on separate days; cloud or a missed overpass can hide the front.</div>
    </Callout>
  );
}

function WindCheck({ detectionId }: { detectionId: string }) {
  const { notify } = useApp();
  const [wind, setWind] = useState<WindInfo | null>(null);
  const [busy, setBusy] = useState(false);

  async function check() {
    setBusy(true);
    try {
      setWind(await api.wind(detectionId));
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!wind) {
    return (
      <div className="mt-2">
        <Button size="sm" icon={Wind} loading={busy} onClick={check}>
          Wind at the overpass
        </Button>
      </div>
    );
  }
  if (wind.status !== "ok") return <div className="mt-2 text-[13.5px] text-muted">Wind not available: {wind.reason}.</div>;
  return (
    <div className={cx("mt-2 rounded-lg border px-3 py-2 text-[14px]", wind.relation === "towards" ? "border-crit/40 bg-crit-soft" : "border-line bg-sunk")}>
      <b>{wind.summary}.</b>
      <div className="text-[13px] text-muted">
        {wind.source} · {wind.attribution}
      </div>
    </div>
  );
}

function severityRows(a: Analysis): [ReactNode, ReactNode][] {
  const rows: [ReactNode, ReactNode][] = [
    ["Severity score", `${fmtNum(a.severity.severity_score, 0)} / 100`],
    ["Alert type", a.severity.incident_type ? INCIDENT_TYPE_LABELS[a.severity.incident_type] ?? a.severity.incident_type : "No alert"],
  ];
  if (a.severity.reason_codes?.length) {
    rows.push(["Reason codes", <code key="codes" className="text-[13.5px]">{a.severity.reason_codes.join(" · ")}</code>]);
  }
  rows.push(
    ["Source baseline", a.severity.baseline ? `median ${fmtNum(a.severity.baseline.median_mw)} MW, scale ${fmtNum(a.severity.baseline.scale_mw)} MW (${a.severity.baseline.n} detections, ${a.severity.baseline.days} days)` : "No baseline yet (needs 6 detections on 3 days)"],
    ["Robust z-score", a.severity.robust_zscore == null ? "—" : fmtNum(a.severity.robust_zscore, 1)],
    ["Recommended action", a.severity.recommended_action],
  );
  return rows;
}

function firmsRows(detail: DetectionDetail): [ReactNode, ReactNode][] {
  const rows: [ReactNode, ReactNode][] = [
    ["Detection id", <code key="id">{detail.detection_id}</code>],
    ["FRP", `${fmtNum(detail.frp, 2)} MW`],
    ["MIR / TIR brightness", `${fmtNum(detail.bright_mir, 1)} K / ${fmtNum(detail.bright_tir, 1)} K (Δ ${fmtNum((detail.bright_mir ?? 0) - (detail.bright_tir ?? 0), 1)} K)`],
    ["Day / night", detail.daynight === "D" ? "Day" : "Night"],
    ["Pixel size", detail.scan && detail.track ? `${fmtNum(detail.scan, 2)} × ${fmtNum(detail.track, 2)} km` : "—"],
    ["Confidence / version", `${detail.confidence} / ${detail.version}`],
    ["Data source", DATA_SOURCE_LABELS[detail.data_source] ?? detail.data_source],
  ];
  if (detail.firms_type != null) {
    rows.push(["NASA static-source flag", `type ${detail.firms_type}: ${FIRMS_TYPE_LABELS[detail.firms_type] ?? "unknown"} (not used by the model)`]);
  }
  return rows;
}

export function DetectionDrawer() {
  const { selectedDetectionId, openDetection, notify, user } = useApp();
  const [detail, setDetail] = useState<DetectionDetail | null>(null);
  const [evidence, setEvidence] = useState<ImageryEvidence | null>(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imagery, setImagery] = useState<ImageryResult | null>(null);
  const [imageryBusy, setImageryBusy] = useState(false);
  const [osm, setOsm] = useState<any | null>(null);
  const [osmBusy, setOsmBusy] = useState(false);

  useEffect(() => {
    setDetail(null);
    setError(null);
    setImagery(null);
    setOsm(null);
    setEvidence(null);
    if (!selectedDetectionId) return;
    let cancelled = false;
    api
      .detection(selectedDetectionId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError(errorMessage(e)));
    return () => {
      cancelled = true;
    };
  }, [selectedDetectionId]);

  async function loadImagery() {
    if (!detail) return;
    setImageryBusy(true);
    try {
      setImagery(await api.imagery(detail.detection_id));
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setImageryBusy(false);
    }
  }

  async function checkEvidence(refresh: boolean) {
    if (!detail) return;
    setEvidenceBusy(true);
    try {
      setEvidence(await api.imageryEvidence(detail.detection_id, refresh));
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setEvidenceBusy(false);
    }
  }

  async function liveOsm() {
    if (!detail) return;
    setOsmBusy(true);
    try {
      setOsm(await api.osmContext(detail.latitude, detail.longitude, true));
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setOsmBusy(false);
    }
  }

  const open = Boolean(selectedDetectionId);
  const a = detail?.analysis;
  const c = a?.classification;
  const shownEvidence = evidence ?? detail?.imagery_evidence ?? null;
  const nearInfrastructure = Boolean(a && c?.category === "vegetation" && a.nearest_critical_infrastructure && a.nearest_critical_infrastructure.distance_km <= 10);

  return (
    <Drawer
      open={open}
      onClose={() => openDetection(null)}
      title={detail ? <ClassBadge code={detail.class_code} /> : "Detection"}
      subtitle={detail ? `${fmtUtc(detail.acq_datetime)} · ${fmtIst(detail.acq_datetime)} · ${detail.satellite} ${detail.instrument}` : undefined}
    >
      {error && <Callout tone="error">{error}</Callout>}
      {!detail && !error && <Spinner />}
      {detail && a && c && (
        <div className="text-[14.5px]">
          <div className="flex flex-wrap items-center gap-2">
            <CategoryBadge category={c.category} confidence={c.confidence_pct} />
            <SeverityBadge severity={detail.severity} />
            {c.verification_required && !detail.current_review && <VerifyBadge />}
            {detail.current_review && <span className="rounded-lg bg-good-soft px-1.5 py-0.5 text-[13px] font-semibold text-good">Analyst: {reviewLabel(detail.current_review.label)}</span>}
            {detail.data_source === "drill" && <span className="rounded-lg bg-warn-soft px-1.5 py-0.5 text-[13px] font-semibold text-warn">Drill (simulated)</span>}
          </div>
          <div className="mt-2 text-ink-2">
            {detail.place ?? "No named place"} · {fmtCoord(detail.latitude, detail.longitude)}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" icon={MapPin} onClick={() => { openDetection(null); navigate("map", { detection: detail.detection_id }); }}>
              Show on map
            </Button>
            {detail.source_id && (
              <Button size="sm" icon={Radar} onClick={() => { openDetection(null); navigate("sources", { source: detail.source_id }); }}>
                Open persistent source
              </Button>
            )}
          </div>

          <SectionHeading hint={c.level === "persistent_source" ? "Decided on all detections at this location" : "Decided on this detection"}>Why this classification</SectionHeading>
          {c.verification_required && (
            <Callout tone="warn" className="mb-2" title="Verify before acting">
              {c.verification_reasons.join(". ")}.
            </Callout>
          )}
          <ul className="list-disc space-y-1 pl-5 text-ink-2">
            {a.evidence.statements.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>

          <SectionHeading hint={detail.location.kind !== "single_detection" ? `${LOCATION_KIND_LABELS[detail.location.kind]} ${detail.location.group_key} · ${detail.location.detections} detections` : undefined}>
            Analyst review
          </SectionHeading>
          <ReviewPanel key={detail.detection_id} detail={detail} onChange={(reviews) => setDetail({ ...detail, reviews, current_review: reviews[0] ?? null })} />

          <SectionHeading hint={`subtype confidence ${fmtPct(c.subtype_confidence)}`}>Class probabilities</SectionHeading>
          <ProbabilityBars probabilities={c.probabilities} highlight={c.model_class_code ?? c.class_code} />

          <SectionHeading hint="for this detection">Strongest model evidence</SectionHeading>
          <ContributionList items={a.contributions} />

          <SectionHeading hint={a.severity.policy_version ? `alert policy ${a.severity.policy_version}` : undefined}>Severity and alerting</SectionHeading>
          <KeyValues rows={severityRows(a)} />
          {a.severity.reason_codes && a.severity.reason_codes.length > 0 && (
            <div className="mt-2">
              <ReasonCodeChips codes={a.severity.reason_codes} labels={REASON_CODE_LABELS} />
            </div>
          )}
          {a.severity.triggers.length > 0 && (
            <Callout tone={detail.severity === "CRITICAL" ? "error" : "warn"} className="mt-2" title="Alert triggered because">
              {a.severity.triggers.join("; ")}
            </Callout>
          )}
          {a.severity.fire_approach && <FireApproachCard approach={a.severity.fire_approach} />}
          {(a.severity.is_cross_alert || nearInfrastructure) && <WindCheck detectionId={detail.detection_id} />}
          {a.severity.authorities.length > 0 && <div className="mt-2 text-[13.5px] text-muted">Suggested notification: {a.severity.authorities.join(", ")}</div>}
          {detail.incidents.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {detail.incidents.map((inc) => (
                <button key={inc.id} onClick={() => { openDetection(null); navigate("incidents", { incident: inc.id }); }} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2 py-1 text-[13.5px] hover:bg-sunk">
                  Incident #{inc.id} <StatusBadge status={inc.status} />
                </button>
              ))}
            </div>
          )}

          <SectionHeading>Geographic context</SectionHeading>
          <div className="flex flex-col gap-1.5 text-ink-2">
            {a.facility && (
              <span>
                Catalog facility:{" "}
                <button className="font-semibold text-accent hover:underline" onClick={() => { openDetection(null); navigate("facilities", { facility: a.facility!.id }); }}>
                  {a.facility.name}
                </button>{" "}
                ({fmtNum(a.facility.distance_km, 2)} km)
              </span>
            )}
            {a.evidence.inside_feature && <FeatureLine feature={a.evidence.inside_feature} prefix="Inside" />}
            {!a.evidence.inside_feature && a.evidence.nearest_industrial_feature && <FeatureLine feature={a.evidence.nearest_industrial_feature} prefix="Nearest mapped feature:" />}
            {a.nearest_critical_infrastructure && a.nearest_critical_infrastructure.feature_id !== a.evidence.nearest_industrial_feature?.feature_id && (
              <FeatureLine feature={a.nearest_critical_infrastructure} prefix="Nearest critical infrastructure:" />
            )}
            {!a.evidence.nearest_industrial_feature && <span>No mapped industrial or mining feature within 50 km.</span>}
          </div>
          <div className="mt-3">
            {a.landcover.available && a.landcover.fractions ? (
              <>
                <div className="mb-1 text-[13.5px] text-muted">ESA WorldCover 2021 in the 375 m pixel footprint (dominant: {a.landcover.dominant_class})</div>
                <LandcoverBar fractions={a.landcover.fractions} />
              </>
            ) : (
              <div className="text-[13.5px] text-muted">Land cover not available: {a.landcover.reason}.</div>
            )}
          </div>
          <div className="mt-3">
            <Button size="sm" icon={Search} loading={osmBusy} onClick={liveOsm}>
              Check live OpenStreetMap
            </Button>
            {osm?.live_overpass && (
              <div className="mt-2 text-[13.5px]">
                {osm.live_overpass.status !== "ok" ? (
                  <span className="text-muted">Live Overpass query failed: {osm.live_overpass.reason}</span>
                ) : osm.live_overpass.count === 0 ? (
                  <span className="text-muted">No industrial, power or quarry features within 5 km in live OpenStreetMap.</span>
                ) : (
                  <ul className="space-y-0.5">
                    {osm.live_overpass.elements.slice(0, 12).map((el: any) => (
                      <li key={el.osm_id}>
                        <a className="text-accent hover:underline" href={el.osm_url} target="_blank" rel="noreferrer">
                          {el.osm_id}
                        </a>{" "}
                        {el.tags.name ?? ""} <span className="text-muted">{Object.entries(el.tags).filter(([k]) => k !== "name").map(([k, v]) => `${k}=${v}`).join(", ")}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          <SectionHeading hint="Sentinel-2 shortwave infrared, independent of the classifier">Imagery evidence</SectionHeading>
          {shownEvidence ? (
            <ImageryEvidenceCard evidence={shownEvidence} category={c.category} busy={evidenceBusy} onRecheck={user ? () => checkEvidence(true) : undefined} />
          ) : (
            <div className="flex flex-col items-start gap-1.5">
              <Button size="sm" icon={Satellite} loading={evidenceBusy} onClick={() => checkEvidence(false)}>
                Check Sentinel-2 for hot spots and burn scars
              </Button>
              <span className="text-[13.5px] text-muted">Measures the scenes from 30 days before to 20 days after the detection (about 10 seconds).</span>
            </div>
          )}

          <SectionHeading hint="nearest real acquisitions, not simultaneous">Satellite imagery</SectionHeading>
          {!imagery ? (
            <Button size="sm" icon={Satellite} loading={imageryBusy} onClick={loadImagery}>
              Find Sentinel-2, Landsat and Sentinel-1 scenes
            </Button>
          ) : imagery.status === "skipped" ? (
            <div className="text-muted">{imagery.reason}</div>
          ) : (
            <div className="flex flex-col gap-2">
              {imagery.sentinel_2_l2a?.items.length ? (
                <SceneCard item={imagery.sentinel_2_l2a.items[0]} label="Sentinel-2 L2A" />
              ) : (
                <div className="text-[13.5px] text-muted">No Sentinel-2 scene under 60% cloud within ±15 days.</div>
              )}
              {imagery.landsat_c2_l2?.items.length ? (
                <SceneCard item={imagery.landsat_c2_l2.items[0]} label="Landsat Collection 2 L2" />
              ) : (
                <div className="text-[13.5px] text-muted">No Landsat scene within ±16 days.</div>
              )}
              <div className="text-[13.5px] text-ink-2">
                Sentinel-1 SAR (cloud-independent):{" "}
                {imagery.sentinel_1_grd?.items.length
                  ? imagery.sentinel_1_grd.items.map((s) => `${fmtUtc(s.datetime)} (${s.days_from_detection > 0 ? "+" : ""}${s.days_from_detection} d)`).join(", ")
                  : "no scene within ±12 days"}
              </div>
            </div>
          )}

          {a.emissions.applicable && (
            <>
              <SectionHeading hint={a.emissions.basis}>Emission estimate</SectionHeading>
              <KeyValues
                rows={[
                  ["Dry matter burning", `${fmtNum(a.emissions.dry_matter_burned_t_per_h)} t/h`],
                  ["CO₂ emission rate", `${fmtNum(a.emissions.co2_t_per_h)} t/h`],
                ]}
              />
              <div className="mt-1 text-[12.5px] text-muted">{a.emissions.references?.join(" · ")}</div>
            </>
          )}

          <SectionHeading>FIRMS record</SectionHeading>
          <KeyValues rows={firmsRows(detail)} />
        </div>
      )}
    </Drawer>
  );
}

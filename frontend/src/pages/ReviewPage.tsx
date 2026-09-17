import { useCallback, useEffect, useState } from "react";
import { Check, Download, MapPin, RefreshCw, Search } from "lucide-react";
import type { PageProps } from "../App";
import { SignInHint } from "../components/Toasts";
import { Button, Callout, CategoryBadge, ClassBadge, Panel, SeverityBadge, Spinner, Stat } from "../components/ui";
import { api, downloadBlob } from "../lib/api";
import { fmtInt, fmtPct, fmtUtc, timeAgo } from "../lib/format";
import { navigate } from "../lib/router";
import { errorMessage, useApp } from "../lib/store";
import { CLASS_META, LOCATION_KIND_LABELS, REVIEW_EVIDENCE_LABELS, reviewLabel } from "../lib/taxonomy";
import type { Review, ReviewQueue, ReviewStats } from "../lib/types";

export function ReviewPage(_props: PageProps) {
  const { can, notify, openDetection, refresh, summary, health } = useApp();
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [recent, setRecent] = useState<{ items: Review[]; stats: ReviewStats } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(20);

  const load = useCallback(async () => {
    try {
      const [q, r] = await Promise.all([api.reviewQueue(200), api.reviews(100)]);
      setQueue(q);
      setRecent(r);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, summary?.generated_at, health?.last_review_at]);

  async function confirm(detectionId: string, classCode: string, groupKey: string) {
    setBusy(groupKey);
    try {
      const result = await api.reviewDetection(detectionId, { label: classCode, scope: "location" });
      notify("success", `Confirmed the model's label for ${result.location.detections} detection(s).`);
      await Promise.all([load(), refresh()]);
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function exportLabels() {
    setBusy("export");
    try {
      downloadBlob(await api.exportLabels(), "analyst_labels.csv");
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (error) {
    return (
      <div className="p-5">
        <Callout tone="error">{error}</Callout>
      </div>
    );
  }
  if (!queue || !recent) return <Spinner label="Loading the review queue" />;
  const stats = recent.stats;

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-5 p-4 md:p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          tone="amber"
          label="Awaiting review"
          value={fmtInt(queue.locations)}
          hint={`locations · ${fmtInt(queue.flagged_detections)} flagged detections${queue.with_alerts ? ` · ${fmtInt(queue.with_alerts)} also have alerts` : ""}`}
        />
        <Stat tone="emerald" label="Labelled by analysts" value={fmtInt(stats.labelled_detections)} hint={`detections at ${fmtInt(stats.labelled_locations)} locations`} />
        <Stat
          tone="indigo"
          label="Agreement with the model"
          value={fmtPct(stats.location_agreement.share)}
          hint={stats.location_agreement.compared ? `${stats.location_agreement.agree} of ${stats.location_agreement.compared} labelled locations` : "no comparable labels yet"}
        />
        <Stat label="Labels recorded" value={fmtInt(stats.reviews)} hint={stats.last_review_at ? `last ${timeAgo(stats.last_review_at)}` : "none yet"} />
      </div>

      <Callout tone="info" title="Uncertain results come here instead of the alert queue">
        Each location below has detections with mixed or thin evidence. An analyst's label is stored next to the model's output, never over it, and every label exports as a training
        row with its evidence. {stats.note}
      </Callout>
      <SignInHint permission="review_detections" action="label detections" />

      <Panel
        title={`${fmtInt(queue.locations)} location(s) to review`}
        subtitle="Most urgent first: alerts, then the least confident classifications"
        actions={
          <Button size="sm" icon={RefreshCw} onClick={load}>
            Refresh
          </Button>
        }
        bodyClassName="p-0"
      >
        {queue.items.length === 0 ? (
          <div className="p-4 text-[14.5px] text-muted">Nothing to review.</div>
        ) : (
          <ul className="divide-y divide-line">
            {queue.items.slice(0, shown).map((item) => {
              const d = item.detection;
              return (
                <li key={item.group_key} className="flex flex-col gap-2 px-5 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    {d.severity !== "NORMAL" && <SeverityBadge severity={d.severity} />}
                    <ClassBadge code={d.class_code} compact />
                    <CategoryBadge category={d.category} confidence={d.confidence_pct} />
                    {item.is_drill && <span className="rounded-lg bg-warn-soft px-1.5 py-0.5 text-[12.5px] font-semibold text-warn">DRILL</span>}
                    <span className="ml-auto text-[13px] text-muted">
                      {LOCATION_KIND_LABELS[item.kind]} {item.group_key} · {item.flagged_detections} of {item.detections} detection(s) flagged · last seen {fmtUtc(item.last_seen, false)}
                    </span>
                  </div>
                  <div className="text-[14.5px] font-medium text-ink">{d.place ?? `${d.latitude.toFixed(3)}, ${d.longitude.toFixed(3)}`}</div>
                  {item.reasons.length > 0 && <div className="text-[14px] text-ink-2">{item.reasons.join(". ")}.</div>}
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" icon={Search} onClick={() => openDetection(d.detection_id)}>
                      Open and label
                    </Button>
                    <Button size="sm" variant="ghost" icon={MapPin} onClick={() => navigate("map", { detection: d.detection_id })}>
                      Show on map
                    </Button>
                    {can("review_detections") && (
                      <Button size="sm" variant="ghost" icon={Check} loading={busy === item.group_key} onClick={() => confirm(d.detection_id, d.class_code, item.group_key)}>
                        Confirm model: {CLASS_META[d.class_code]?.short ?? d.class_code}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        {queue.items.length > shown && (
          <div className="border-t border-line px-5 py-3">
            <Button size="sm" onClick={() => setShown(shown + 20)}>
              Show {Math.min(20, queue.items.length - shown)} more ({fmtInt(queue.items.length - shown)} remaining)
            </Button>
          </div>
        )}
      </Panel>

      <Panel
        title="Recent labels"
        subtitle="Newest first. The model's output at the time of review is kept with every label."
        actions={
          <Button size="sm" icon={Download} loading={busy === "export"} onClick={exportLabels} title="Every labelled detection with its FIRMS record, model output, label provenance and the 30 model features">
            Export labels (CSV)
          </Button>
        }
        bodyClassName="p-0"
      >
        {recent.items.length === 0 ? (
          <div className="p-4 text-[14.5px] text-muted">No labels recorded yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-[14px]">
              <thead className="bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">When</th>
                  <th className="px-2 py-2 font-medium">Analyst</th>
                  <th className="px-2 py-2 font-medium">Label</th>
                  <th className="px-2 py-2 font-medium">Model said</th>
                  <th className="px-2 py-2 font-medium">Agrees</th>
                  <th className="px-2 py-2 font-medium">Applies to</th>
                  <th className="px-4 py-2 font-medium">Evidence and note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {recent.items.map((review) => (
                  <tr key={review.id} className="cursor-pointer hover:bg-sunk" onClick={() => openDetection(review.detection_id)}>
                    <td className="whitespace-nowrap px-4 py-2">{fmtUtc(review.created_at)}</td>
                    <td className="px-2 py-2">{review.reviewer}</td>
                    <td className="px-2 py-2 font-medium text-ink">{reviewLabel(review.label)}</td>
                    <td className="px-2 py-2">{review.model_class_code ? <ClassBadge code={review.model_class_code} compact /> : "—"}</td>
                    <td className="px-2 py-2">
                      {review.agrees_with_model == null ? <span className="text-muted">n/a</span> : review.agrees_with_model ? <span className="font-semibold text-good">yes</span> : <span className="font-semibold text-crit">no</span>}
                    </td>
                    <td className="px-2 py-2 text-ink-2">{review.scope === "location" ? `location ${review.group_key}` : "detection"}</td>
                    <td className="px-4 py-2 text-ink-2">{[review.evidence.map((e) => REVIEW_EVIDENCE_LABELS[e] ?? e).join(", "), review.note].filter(Boolean).join(" - ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

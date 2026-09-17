import { useState } from "react";
import { Check, History, PenLine } from "lucide-react";
import { api } from "../lib/api";
import { fmtUtc } from "../lib/format";
import { errorMessage, useApp } from "../lib/store";
import { CLASS_META, LOCATION_KIND_LABELS, REVIEW_EVIDENCE_LABELS, REVIEW_LABEL_META, reviewLabel } from "../lib/taxonomy";
import type { DetectionDetail, Review, ReviewScope } from "../lib/types";
import { SignInHint } from "./Toasts";
import { Button, Callout, cx, inputClass } from "./ui";

const GROUPS = ["Industrial", "Vegetation fire", "Other"] as const;

function scopeText(review: Review, kind: string) {
  return review.scope === "location" ? `whole ${LOCATION_KIND_LABELS[kind] ?? "location"}` : "this detection";
}

/** An analyst's label for a detection or its whole location, stored next to the model's output (never over it). */
export function ReviewPanel({ detail, onChange }: { detail: DetectionDetail; onChange: (reviews: Review[]) => void }) {
  const { can, notify, refresh } = useApp();
  const current = detail.current_review;
  const location = detail.location;
  const multiple = location.kind !== "single_detection" && location.detections > 1;
  const [editing, setEditing] = useState(!current);
  const [label, setLabel] = useState<string>(current?.label ?? detail.class_code);
  const [scope, setScope] = useState<ReviewScope>(multiple ? "location" : "detection");
  const [evidence, setEvidence] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const modelLabel = CLASS_META[detail.class_code]?.label ?? detail.class_code;

  async function save(chosen: string, key: string) {
    setBusy(key);
    try {
      const result = await api.reviewDetection(detail.detection_id, { label: chosen, scope, note: note.trim() || undefined, evidence });
      onChange(result.reviews);
      setEditing(false);
      setNote("");
      setEvidence([]);
      const where = scope === "location" ? `${result.location.detections} detections at this ${LOCATION_KIND_LABELS[result.location.kind]}` : "this detection";
      const noted = result.incidents_noted.length ? ` Added to the history of incident #${result.incidents_noted.join(", #")}.` : "";
      notify("success", `Label saved for ${where}.${noted}`);
      await refresh();
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const agrees = current?.label_category == null ? null : current.label_category === detail.category;
  return (
    <div className="flex flex-col gap-2">
      {current ? (
        <Callout tone={agrees === null ? "info" : agrees ? "success" : "warn"} title={`Analyst label: ${reviewLabel(current.label)}`}>
          <div>
            {agrees === null
              ? "This label has no industrial-or-vegetation category, so it is not compared with the model."
              : agrees
                ? "Agrees with the model's category."
                : `Disagrees with the model (${modelLabel}); the model's output stays unchanged next to this label.`}
          </div>
          <div className="text-[13.5px] text-ink-2">
            {current.reviewer} · {fmtUtc(current.created_at)} · {scopeText(current, location.kind)}
            {current.evidence.length > 0 && ` · evidence: ${current.evidence.map((e) => REVIEW_EVIDENCE_LABELS[e] ?? e).join(", ")}`}
          </div>
          {current.note && <div className="mt-1 text-[14px] italic">"{current.note}"</div>}
        </Callout>
      ) : detail.verification_required ? (
        <Callout tone="warn" title="Awaiting analyst review">
          The evidence is mixed or thin. A label is stored next to the model's output and becomes a real, checked training example.
        </Callout>
      ) : (
        <div className="text-[14px] text-muted">No analyst label. This detection is not flagged, so a label is optional.</div>
      )}

      {!can("review_detections") ? (
        <SignInHint permission="review_detections" action="label detections" />
      ) : editing ? (
        <div className="flex flex-col gap-2.5 rounded-lg border border-line p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" icon={Check} loading={busy === "confirm"} onClick={() => save(detail.class_code, "confirm")}>
              Confirm model: {CLASS_META[detail.class_code]?.short ?? detail.class_code}
            </Button>
            <span className="text-[13.5px] text-muted">or choose another label</span>
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]">
            <select className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Analyst label">
              {GROUPS.map((group) => (
                <optgroup key={group} label={group}>
                  {Object.entries(REVIEW_LABEL_META)
                    .filter(([, meta]) => meta.group === group)
                    .map(([code, meta]) => (
                      <option key={code} value={code}>
                        {meta.label}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
            <Button size="sm" icon={PenLine} loading={busy === "save"} onClick={() => save(label, "save")}>
              Save label
            </Button>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[14px]" role="radiogroup" aria-label="What the label applies to">
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={scope === "detection"} onChange={() => setScope("detection")} /> This detection
            </label>
            <label className={cx("flex items-center gap-1.5", !multiple && "text-muted")}>
              <input type="radio" checked={scope === "location"} disabled={!multiple} onChange={() => setScope("location")} /> Whole {LOCATION_KIND_LABELS[location.kind]} ({location.detections}{" "}
              detections)
            </label>
          </div>
          <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-[14px]">
            <legend className="mb-1 text-[13.5px] text-muted">Evidence used</legend>
            {Object.entries(REVIEW_EVIDENCE_LABELS).map(([code, text]) => (
              <label key={code} className="flex items-center gap-1.5">
                <input type="checkbox" checked={evidence.includes(code)} onChange={(e) => setEvidence(e.target.checked ? [...evidence, code] : evidence.filter((item) => item !== code))} />
                {text}
              </label>
            ))}
          </fieldset>
          <input className={inputClass} placeholder="Note (optional), e.g. what the operator said" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
          {current && (
            <div>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div>
          <Button size="sm" icon={PenLine} onClick={() => setEditing(true)}>
            Change label
          </Button>
        </div>
      )}

      {detail.reviews.length > 1 && (
        <details className="text-[13.5px] text-ink-2">
          <summary className="cursor-pointer text-accent">
            <History size={12} className="mr-1 inline" aria-hidden />
            Earlier labels ({detail.reviews.length - 1})
          </summary>
          <ol className="mt-1 space-y-0.5">
            {detail.reviews.slice(1).map((review) => (
              <li key={review.id}>
                {fmtUtc(review.created_at)} · <b>{review.reviewer}</b>: {reviewLabel(review.label)} ({scopeText(review, location.kind)})
                {review.note ? ` - "${review.note}"` : ""}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

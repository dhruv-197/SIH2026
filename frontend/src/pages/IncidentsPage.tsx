import { useEffect, useMemo, useState, type ReactNode } from "react";
import { History, MapPin, Search, ShieldAlert } from "lucide-react";
import type { PageProps } from "../App";
import { SignInHint } from "../components/Toasts";
import { Button, ReasonCodeChips, Segmented, SeverityBadge, StatusBadge, cx, inputBase } from "../components/ui";
import { api } from "../lib/api";
import { fmtUtc, timeAgo } from "../lib/format";
import { navigate } from "../lib/router";
import { errorMessage, useApp } from "../lib/store";
import { FIRE_APPROACH_META, INCIDENT_STATUS_META, INCIDENT_TRANSITIONS, INCIDENT_TYPE_LABELS, REASON_CODE_LABELS, SEVERITY_META } from "../lib/taxonomy";
import type { Incident } from "../lib/types";

const OPEN = ["OPEN", "ACKNOWLEDGED", "INVESTIGATING"];

function ContextRow({ label, children, alert = false }: { label: string; children: ReactNode; alert?: boolean }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[170px_1fr] sm:gap-4">
      <dt className="text-[13.5px] font-semibold text-muted">{label}</dt>
      <dd className={cx("text-[14.5px] leading-relaxed", alert ? "font-medium text-crit" : "text-ink-2")}>{children}</dd>
    </div>
  );
}

function IncidentCard({ incident, facilityName, highlighted, codeDescriptions }: { incident: Incident; facilityName?: string; highlighted: boolean; codeDescriptions: Record<string, string> }) {
  const { can, refreshIncidents, notify, openDetection } = useApp();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(highlighted);
  const allowed = can("triage_incidents");
  const approach = incident.details?.fire_approach;
  const wind = incident.details?.wind;
  const hasContext = Boolean(approach || wind?.summary || incident.imagery_evidence || facilityName);

  async function move(status: string) {
    setBusy(status);
    try {
      await api.updateIncident(incident.id, status, note);
      setNote("");
      notify("success", `Incident #${incident.id} marked ${INCIDENT_STATUS_META[status as keyof typeof INCIDENT_STATUS_META].label.toLowerCase()}`);
      await refreshIncidents();
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <article id={`incident-${incident.id}`} className={cx("overflow-hidden rounded-2xl border bg-panel shadow-card", highlighted ? "border-accent ring-2 ring-accent/25" : "border-line")}>
      <div className={cx("h-1.5", incident.severity === "CRITICAL" ? "bg-crit" : incident.severity === "HIGH" ? "bg-amber-500" : "bg-slate-300")} aria-hidden />
      <div className="flex flex-col gap-3.5 px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={incident.severity} />
          <StatusBadge status={incident.status} />
          <span className="text-[14px] font-medium text-ink-2">{INCIDENT_TYPE_LABELS[incident.incident_type] ?? incident.incident_type}</span>
          {incident.is_drill && <span className="rounded-full bg-warn-soft px-2.5 py-0.5 text-[12.5px] font-semibold text-warn">DRILL · simulated data</span>}
          <span className="ml-auto text-[13px] text-muted">
            #{incident.id} · updated {timeAgo(incident.updated_at)}
            {incident.updated_by ? ` by ${incident.updated_by}` : ""}
          </span>
        </div>
        <div>
          <h3 className="text-[19px] font-semibold leading-snug text-ink">{incident.title}</h3>
          <p className="mt-1.5 text-[15px] leading-relaxed text-ink-2">{incident.summary}</p>
        </div>
        <ReasonCodeChips codes={incident.reason_codes} descriptions={codeDescriptions} labels={REASON_CODE_LABELS} />
        {hasContext && (
          <dl className="flex flex-col gap-2 rounded-xl border border-line bg-slate-50 px-4 py-3">
            {approach && (
              <ContextRow label={FIRE_APPROACH_META[approach.status]?.label ?? "Fire front"} alert={approach.status === "approaching"}>
                {approach.summary}.
              </ContextRow>
            )}
            {wind?.summary && (
              <ContextRow label="Wind" alert={wind.relation === "towards"}>
                {wind.summary}.
              </ContextRow>
            )}
            {incident.imagery_evidence && <ContextRow label="Sentinel-2 check">{incident.imagery_evidence.headline}</ContextRow>}
            {facilityName && <ContextRow label="Facility">{facilityName}</ContextRow>}
          </dl>
        )}
        <div className="rounded-xl border border-sky-100 bg-sky-50 px-4 py-3">
          <div className="text-[12.5px] font-bold uppercase tracking-[0.08em] text-sky-800">Recommended action</div>
          <p className="mt-1 text-[15px] leading-relaxed text-ink">{incident.recommended_action}</p>
          {incident.authorities.length > 0 && <p className="mt-1 text-[14px] text-ink-2">Notify: {incident.authorities.join(", ")}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" icon={Search} onClick={() => openDetection(incident.detection_id)}>
            Latest detection
          </Button>
          {incident.latitude != null && incident.longitude != null && (
            <Button size="sm" icon={MapPin} onClick={() => navigate("map", { lat: incident.latitude, lon: incident.longitude, zoom: 12 })}>
              Show on map
            </Button>
          )}
          <Button size="sm" variant="ghost" icon={History} onClick={() => setShowHistory(!showHistory)}>
            History ({incident.history.length})
          </Button>
          <span className="ml-auto text-[13px] text-muted">
            Opened {fmtUtc(incident.created_at)}
            {incident.policy_version ? ` · alert policy ${incident.policy_version}` : ""}
          </span>
        </div>
      </div>
      {showHistory && (
        <ol className="border-t border-line bg-slate-50 px-5 py-3 text-[14px]">
          {incident.history.map((h, i) => (
            <li key={i} className="py-1 text-ink-2">
              <span className="text-muted">{fmtUtc(h.at)}</span> · <b className="text-ink">{h.by}</b> set <b>{h.status}</b>
              {h.note ? ` - "${h.note}"` : ""}
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
        {allowed ? (
          <>
            <input className={cx(inputBase, "min-w-[220px] flex-1")} placeholder="Note for the log (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
            {INCIDENT_TRANSITIONS[incident.status].map((next) => (
              <Button key={next} size="sm" variant={next === "RESOLVED" ? "primary" : next === "FALSE_POSITIVE" ? "ghost" : "secondary"} loading={busy === next} onClick={() => move(next)}>
                {next === "OPEN" ? "Reopen" : INCIDENT_STATUS_META[next].label}
              </Button>
            ))}
          </>
        ) : (
          <SignInHint permission="triage_incidents" action="update incidents" />
        )}
      </div>
    </article>
  );
}

export function IncidentsPage({ params }: PageProps) {
  const { incidents, facilities } = useApp();
  const [view, setView] = useState<"open" | "closed" | "all">("open");
  const [severity, setSeverity] = useState("all");
  const [showDrills, setShowDrills] = useState(true);
  const [codeDescriptions, setCodeDescriptions] = useState<Record<string, string>>({});
  const highlighted = Number(params.get("incident") ?? 0);

  useEffect(() => {
    api.settings().then((s) => setCodeDescriptions(s.alert_policy?.reason_codes ?? {})).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!highlighted) return;
    const incident = incidents.find((i) => i.id === highlighted);
    if (incident && !OPEN.includes(incident.status)) setView("all");
    window.setTimeout(() => document.getElementById(`incident-${highlighted}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 150);
    // Scroll when the highlighted incident changes or the list first loads - not on every poll of the incidents.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [highlighted, incidents.length]);

  const facilityNames = useMemo(() => Object.fromEntries(facilities.map((f) => [f.id, f.name])), [facilities]);
  const rows = useMemo(
    () =>
      incidents
        .filter((i) => (view === "all" ? true : view === "open" ? OPEN.includes(i.status) : !OPEN.includes(i.status)))
        .filter((i) => severity === "all" || i.severity === severity)
        .filter((i) => showDrills || !i.is_drill)
        .sort((a, b) => SEVERITY_META[b.severity].rank - SEVERITY_META[a.severity].rank || b.updated_at.localeCompare(a.updated_at)),
    [incidents, view, severity, showDrills],
  );
  const noun = view === "open" ? "open incident" : view === "closed" ? "closed incident" : "incident";

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-line bg-panel px-5 py-4 shadow-card">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-rose-100 text-rose-700">
            <ShieldAlert size={22} aria-hidden />
          </span>
          <div className="min-w-0">
            <div className="font-display text-[20px] font-bold tracking-tight text-ink">
              {rows.length} {noun}
              {rows.length === 1 ? "" : "s"}
            </div>
            <div className="text-[14px] text-muted">Raised by versioned rules, most severe first. Thermal data alone cannot confirm a fire or leak: verify before acting.</div>
          </div>
        </div>
        <div className="flex max-w-full flex-wrap items-center gap-2">
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: "open", label: "Open" },
              { value: "closed", label: "Closed" },
              { value: "all", label: "All" },
            ]}
          />
          <select className={cx(inputBase, "w-auto")} value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity">
            <option value="all">Any severity</option>
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
          </select>
          <label className="flex items-center gap-2 px-1 text-[14px] text-ink-2">
            <input type="checkbox" checked={showDrills} onChange={(e) => setShowDrills(e.target.checked)} />
            Show drills
          </label>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-line-strong bg-panel px-5 py-12 text-center text-[15px] text-muted">No incidents in this view.</div>
      ) : (
        rows.map((incident) => (
          <IncidentCard
            key={incident.id}
            incident={incident}
            facilityName={incident.facility_id ? facilityNames[incident.facility_id] : undefined}
            highlighted={incident.id === highlighted}
            codeDescriptions={codeDescriptions}
          />
        ))
      )}
    </div>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { FlaskConical, KeyRound, RefreshCw, Save, Send, Trash2 } from "lucide-react";
import type { PageProps } from "../App";
import { SignInHint } from "../components/Toasts";
import { Button, Callout, Field, Panel, Spinner, cx, inputClass, inputBase } from "../components/ui";
import { api, type SettingsResponse } from "../lib/api";
import { fmtUtc } from "../lib/format";
import { errorMessage, useApp } from "../lib/store";
import { REASON_CODE_LABELS } from "../lib/taxonomy";
import type { AuditEntry, Settings } from "../lib/types";

const THRESHOLDS: { key: keyof Settings; label: string; hint: string; min: number; max: number; step: number; unit: string }[] = [
  { key: "zscore_threshold", label: "Excursion z-score", hint: "Robust standard deviations above a source's own median FRP before a critical excursion is raised.", min: 2, max: 10, step: 0.5, unit: "σ" },
  { key: "frp_threshold_mw", label: "Industrial intensity without history", hint: "FRP that is abnormal at a mapped industrial site with no baseline: one detection, or the total of a same-overpass cluster of new activity (possible fire or emergency flaring).", min: 5, max: 5000, step: 5, unit: "MW" },
  { key: "cross_alert_km", label: "Cross-alert distance", hint: "A vegetation fire of at least 5 MW this close to critical infrastructure raises an alert, even when the classification is uncertain (brick kilns excluded). A fire front approaching the facility makes it critical.", min: 0.5, max: 10, step: 0.5, unit: "km" },
  { key: "high_intensity_frp_mw", label: "High-intensity vegetation fire", hint: "FRP above which a vegetation fire is reported as high severity.", min: 20, max: 5000, step: 10, unit: "MW" },
  { key: "retention_days", label: "Retention", hint: "Detections older than this (relative to the newest detection) are removed.", min: 7, max: 365, step: 1, unit: "days" },
];

const AUDIT_FILTERS = [
  { value: "", label: "All actions" },
  { value: "auth", label: "Sign-ins" },
  { value: "settings", label: "Settings and alert policy" },
  { value: "incident", label: "Incident triage" },
  { value: "review", label: "Analyst labels" },
  { value: "drill", label: "Drills" },
  { value: "data", label: "Syncs and uploads" },
  { value: "imagery", label: "Imagery re-checks" },
];

function AuditLogPanel() {
  const { can, notify, user } = useApp();
  const allowed = can("view_audit");
  const [action, setAction] = useState("");
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!allowed) return;
    setBusy(true);
    try {
      setItems((await api.audit({ limit: 200, action: action || undefined })).items);
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(false);
    }
  }, [allowed, action, notify]);

  useEffect(() => {
    load();
  }, [load, user?.username]);

  return (
    <Panel
      title="Audit log"
      subtitle="Every human action - sign-ins, settings and alert-policy changes, incident triage, analyst labels, drills, syncs and uploads - with who did it and when. Entries are never edited."
      actions={
        allowed ? (
          <>
            <select className={cx(inputBase, "w-auto")} value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">
              {AUDIT_FILTERS.map((filter) => (
                <option key={filter.value} value={filter.value}>
                  {filter.label}
                </option>
              ))}
            </select>
            <Button size="sm" icon={RefreshCw} loading={busy} onClick={load}>
              Refresh
            </Button>
          </>
        ) : undefined
      }
      bodyClassName="p-0"
    >
      {!allowed ? (
        <div className="p-4">
          <SignInHint permission="view_audit" action="see the audit log" />
        </div>
      ) : !items ? (
        <Spinner label="Loading the audit log" />
      ) : items.length === 0 ? (
        <div className="p-4 text-[14.5px] text-muted">No entries.</div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full min-w-[760px] text-[14px]">
            <thead className="sticky top-0 bg-sunk text-left text-[12.5px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">When</th>
                <th className="px-2 py-2 font-medium">Who</th>
                <th className="px-2 py-2 font-medium">Action</th>
                <th className="px-4 py-2 font-medium">What</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {items.map((entry) => (
                <tr key={entry.id}>
                  <td className="whitespace-nowrap px-4 py-1.5">{fmtUtc(entry.at)}</td>
                  <td className="px-2 py-1.5 font-medium">{entry.actor}</td>
                  <td className="px-2 py-1.5">
                    <code className="text-[13px]">{entry.action}</code>
                  </td>
                  <td className="px-4 py-1.5 text-ink-2">{entry.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export function SettingsPage(_props: PageProps) {
  const { can, facilities, refresh, notify } = useApp();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [mapKey, setMapKey] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [drillFacility, setDrillFacility] = useState("");
  const [drillKind, setDrillKind] = useState("industrial_excursion");
  const [roles, setRoles] = useState<{ role: string; title: string; permissions: string[] }[]>([]);
  const canSettings = can("modify_settings");

  useEffect(() => {
    api
      .settings()
      .then((d) => {
        setData(d);
        setForm(d.settings);
      })
      .catch((e) => notify("error", errorMessage(e)));
    api.me().then((me: any) => setRoles(me.roles ?? [])).catch(() => undefined);
  }, [notify]);

  const drillFacilities = useMemo(() => [...facilities].sort((a, b) => b.detections - a.detections || a.name.localeCompare(b.name)), [facilities]);
  useEffect(() => {
    if (!drillFacility && drillFacilities.length) setDrillFacility(drillFacilities[0].id);
  }, [drillFacilities, drillFacility]);

  async function save(payload: Record<string, unknown>, label: string) {
    setBusy(label);
    try {
      const result = await api.updateSettings(payload);
      setForm(result.settings);
      setData((current) => (current ? { ...current, settings: result.settings, alert_policy: result.alert_policy } : current));
      notify("success", result.reanalysed ? `Settings saved; all detections were re-analysed under alert policy ${result.alert_policy.version}.` : "Settings saved.");
      if (result.reanalysed) await refresh();
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function run(label: string, action: () => Promise<string>) {
    setBusy(label);
    try {
      notify("success", await action());
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (!form || !data) return <Spinner label="Loading settings" />;
  const policy = data.alert_policy;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-4 md:p-6">
      <SignInHint permission="modify_settings" action="change settings, run drills or send test notifications" />
      {data.static_dataset && <Callout tone="info">This server shows a fixed archive dataset: automatic FIRMS polling and drills are off, whatever the settings below say.</Callout>}

      <Panel
        title="Alert thresholds"
        subtitle={
          <>
            Changing a threshold re-runs the analysis on every stored detection. Alert policy in force: <b className="num text-ink">v{policy.version}</b> (rules {policy.rules_version}, thresholds fingerprint{" "}
            {policy.thresholds_fingerprint}); every alert records the version that raised it.
          </>
        }
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {THRESHOLDS.map((t) => (
            <Field key={t.key} label={`${t.label} (${t.unit})`} hint={t.hint}>
              <input
                className={inputClass}
                type="number"
                min={t.min}
                max={t.max}
                step={t.step}
                value={Number(form[t.key])}
                disabled={!canSettings}
                onChange={(e) => setForm({ ...form, [t.key]: Number(e.target.value) })}
              />
            </Field>
          ))}
        </div>
        <details className="mt-4 text-[14px] text-ink-2">
          <summary className="cursor-pointer text-accent">Reason codes attached to alerts</summary>
          <table className="mt-2 w-full">
            <tbody className="divide-y divide-line">
              {Object.entries(policy.reason_codes).map(([code, description]) => (
                <tr key={code}>
                  <td className="py-1 pr-3">
                    <code className="text-[13px]">{code}</code>
                  </td>
                  <td className="py-1 pr-3 font-medium text-ink">{REASON_CODE_LABELS[code] ?? code}</td>
                  <td className="py-1">{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
        <div className="mt-4 flex justify-end">
          <Button
            variant="primary"
            icon={Save}
            disabled={!canSettings}
            loading={busy === "thresholds"}
            onClick={() => save(Object.fromEntries(THRESHOLDS.map((t) => [t.key, form[t.key]])), "thresholds")}
          >
            Save thresholds
          </Button>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Automatic FIRMS polling" subtitle={data.next_scheduled_sync ? `Next scheduled sync ${fmtUtc(data.next_scheduled_sync)}` : "The scheduler is not running in this process."}>
          <div className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-[14.5px]">
              <input type="checkbox" checked={form.satellite_auto_polling} disabled={!canSettings} onChange={(e) => setForm({ ...form, satellite_auto_polling: e.target.checked })} />
              Poll NASA FIRMS automatically
            </label>
            <Field label="Interval (minutes)" hint="FIRMS near-real-time data typically arrives within 3 hours of an overpass.">
              <input className={inputClass} type="number" min={15} max={1440} value={form.auto_sync_interval_mins} disabled={!canSettings} onChange={(e) => setForm({ ...form, auto_sync_interval_mins: Number(e.target.value) })} />
            </Field>
            <div className="flex justify-end">
              <Button icon={Save} disabled={!canSettings} loading={busy === "polling"} onClick={() => save({ satellite_auto_polling: form.satellite_auto_polling, auto_sync_interval_mins: form.auto_sync_interval_mins }, "polling")}>
                Save polling
              </Button>
            </div>
          </div>
        </Panel>

        <Panel title="NASA FIRMS MAP_KEY" subtitle="Optional. Enables the FIRMS area API for up to 10-day ranges. Get a free key at firms.modaps.eosdis.nasa.gov/api/map_key.">
          <div className="flex flex-col gap-3">
            <div className="text-[14.5px] text-ink-2">
              Status:{" "}
              {form.firms_api_key_configured ? <b className="text-good">key stored</b> : data.environment_map_key_configured ? <b className="text-good">key set in environment</b> : <b className="text-muted">no key - the public feed is used</b>}
              . Keys are never sent back to the browser.
            </div>
            <Field label="New MAP_KEY">
              <input className={inputClass} type="password" autoComplete="off" value={mapKey} disabled={!canSettings} onChange={(e) => setMapKey(e.target.value)} placeholder="32-character key" />
            </Field>
            <div className="flex justify-end gap-2">
              <Button
                icon={KeyRound}
                disabled={!canSettings || (!form.firms_api_key_configured && !data.environment_map_key_configured)}
                loading={busy === "check"}
                onClick={() => run("check", async () => {
                  const r = await api.checkFirmsKey();
                  if (!r.valid) throw new Error(r.error ?? "MAP_KEY is not valid");
                  return `MAP_KEY is valid: ${JSON.stringify(r.status)}`;
                })}
              >
                Check key
              </Button>
              <Button variant="primary" icon={Save} disabled={!canSettings || !mapKey.trim()} loading={busy === "key"} onClick={async () => { await save({ firms_api_key: mapKey.trim() }, "key"); setMapKey(""); }}>
                Save key
              </Button>
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Incident notifications" subtitle="New and re-opened incidents are sent automatically to a webhook - for example a Slack or Microsoft Teams incoming webhook, or an SMS / email relay. Every message carries the reason codes and alert policy, and every delivery is logged in the incident history.">
          <div className="flex flex-col gap-3">
            <Field label="Webhook URL">
              <input className={inputClass} type="url" placeholder="https://your-endpoint.example/hooks/thermal" value={form.webhook_url} disabled={!canSettings} onChange={(e) => setForm({ ...form, webhook_url: e.target.value })} />
            </Field>
            <label className="flex items-center gap-2 text-[14.5px]">
              <input type="checkbox" checked={form.notify_incidents} disabled={!canSettings} onChange={(e) => setForm({ ...form, notify_incidents: e.target.checked })} />
              Send new and re-opened incidents automatically
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Minimum severity">
                <select className={inputClass} value={form.notify_min_severity} disabled={!canSettings} onChange={(e) => setForm({ ...form, notify_min_severity: e.target.value as Settings["notify_min_severity"] })}>
                  <option value="HIGH">High and critical</option>
                  <option value="CRITICAL">Critical only</option>
                </select>
              </Field>
              <Field label="Dashboard address for links" hint="Optional; messages link to the incident at this address.">
                <input className={inputClass} type="url" placeholder="https://sentinel.example.in" value={form.dashboard_url} disabled={!canSettings} onChange={(e) => setForm({ ...form, dashboard_url: e.target.value })} />
              </Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                icon={Save}
                disabled={!canSettings}
                loading={busy === "webhook"}
                onClick={() => save({ webhook_url: form.webhook_url, notify_incidents: form.notify_incidents, notify_min_severity: form.notify_min_severity, dashboard_url: form.dashboard_url }, "webhook")}
              >
                Save notifications
              </Button>
              <Button
                icon={Send}
                disabled={!can("send_test_alert") || !form.webhook_url}
                loading={busy === "test"}
                onClick={() => run("test", async () => {
                  const r = await api.testAlert();
                  if (!r.delivered) throw new Error(r.error ?? `Webhook answered HTTP ${r.http_status}`);
                  return `Test notification delivered (HTTP ${r.http_status}).`;
                })}
              >
                Send test notification
              </Button>
            </div>
          </div>
        </Panel>

        <Panel title="Drills" subtitle="Inject clearly labelled simulated detections to rehearse the alert workflow. Drill data never mixes silently with real data.">
          <div className="flex flex-col gap-3">
            <Callout tone="info">Drill detections are stored with data source "drill", their incidents are marked DRILL, and one click removes them (with any analyst labels on them).</Callout>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Scenario">
                <select className={inputClass} value={drillKind} onChange={(e) => setDrillKind(e.target.value)} disabled={!can("run_drills")}>
                  <option value="industrial_excursion">FRP excursion at a facility (6 normal days, then a spike)</option>
                  <option value="wildfire_near_facility">Vegetation fire advancing towards a facility</option>
                </select>
              </Field>
              <Field label="Facility">
                <select className={inputClass} value={drillFacility} onChange={(e) => setDrillFacility(e.target.value)} disabled={!can("run_drills")}>
                  {drillFacilities.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="danger" icon={Trash2} disabled={!can("run_drills")} loading={busy === "purge"} onClick={() => run("purge", async () => {
                const r = await api.purgeDrills();
                await refresh();
                return `Removed ${r.detections_removed} drill detections and ${r.incidents_removed} drill incidents.`;
              })}>
                Remove drill data
              </Button>
              <Button variant="primary" icon={FlaskConical} disabled={!can("run_drills") || !drillFacility || data.static_dataset} loading={busy === "drill"} onClick={() => run("drill", async () => {
                const r = await api.runDrill(drillKind, drillFacility);
                await refresh();
                return `Drill injected: ${r.records_inserted} simulated detections. Check Incidents.`;
              })}>
                Run drill
              </Button>
            </div>
          </div>
        </Panel>
      </div>

      <AuditLogPanel />

      <Panel title="Roles" bodyClassName="p-0">
        <table className="w-full text-[14px]">
          <tbody className="divide-y divide-line">
            {roles.map((r) => (
              <tr key={r.role}>
                <td className="w-48 px-4 py-2 font-medium">{r.title}</td>
                <td className="px-4 py-2 text-ink-2">{r.permissions.map((p) => p.replace(/_/g, " ")).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

import { useState, type ReactNode } from "react";
import {
  BrainCircuit,
  CalendarRange,
  ClipboardCheck,
  Database,
  Factory,
  FileText,
  LayoutDashboard,
  LogIn,
  LogOut,
  Map as MapIcon,
  MessageSquare,
  Radar,
  RefreshCw,
  Settings,
  Siren,
  type LucideIcon,
} from "lucide-react";
import { api } from "../lib/api";
import { fmtWindow, timeAgo } from "../lib/format";
import { errorMessage, useApp } from "../lib/store";
import { Logo, LogoMark } from "./Logo";
import { Button, Callout, buttonClass, cx } from "./ui";

// Settings is in the top bar, not in these groups.
const NAV_GROUPS: { label: string; items: { page: string; label: string; icon: LucideIcon }[] }[] = [
  {
    label: "Monitor",
    items: [
      { page: "overview", label: "Overview", icon: LayoutDashboard },
      { page: "map", label: "Map", icon: MapIcon },
      { page: "incidents", label: "Incidents", icon: Siren },
      { page: "review", label: "Review queue", icon: ClipboardCheck },
    ],
  },
  {
    label: "Analyse",
    items: [
      { page: "sources", label: "Persistent sources", icon: Radar },
      { page: "facilities", label: "Facilities", icon: Factory },
      { page: "model", label: "Model & what-if", icon: BrainCircuit },
    ],
  },
  {
    label: "Report",
    items: [
      { page: "briefing", label: "Briefing", icon: FileText },
      { page: "data", label: "Data & uploads", icon: Database },
    ],
  },
];

const NAV = NAV_GROUPS.flatMap((group) => group.items);

const OPEN_STATUSES = ["OPEN", "ACKNOWLEDGED", "INVESTIGATING"];

export function Layout({ page, title, children }: { page: string; title: string; children: ReactNode }) {
  const { health, summary, incidents, user, can, setSignInOpen, signOut, refresh, notify, setAssistantOpen, error } = useApp();
  const [syncing, setSyncing] = useState(false);
  const openIncidents = incidents.filter((i) => OPEN_STATUSES.includes(i.status)).length;
  const toReview = summary?.funnel?.review_locations ?? 0;
  const staticDataset = Boolean(health?.dataset?.static);
  const observation = summary?.window ?? health?.observation_window;

  function badge(target: string, compact = false) {
    const count = target === "incidents" ? openIncidents : target === "review" ? toReview : 0;
    if (!count) return null;
    return (
      <span
        className={cx(
          "num rounded-full font-semibold",
          target === "incidents" ? "bg-rose-500 text-white" : "bg-amber-400 text-amber-950",
          compact ? "px-1.5 text-[12px]" : "px-2 py-0.5 text-[12.5px]",
        )}
      >
        {count}
      </span>
    );
  }

  async function syncNow() {
    if (!can("sync_feed")) {
      setSignInOpen(true);
      return;
    }
    setSyncing(true);
    try {
      const result = await api.sync({ mode: "auto", window: "24h", day_range: 2 });
      notify("success", result.message);
      await refresh();
    } catch (e) {
      notify("error", errorMessage(e));
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="flex h-full">
      <aside className="no-print hidden w-[264px] shrink-0 flex-col bg-brand md:flex">
        <a href="#/overview" className="block px-5 pb-6 pt-6" aria-label="GeoThermal Sentinel overview">
          <Logo tone="dark" />
        </a>
        <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label="Pages">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-5">
              <div className="px-3 pb-2 text-[11.5px] font-semibold uppercase tracking-[0.14em] text-slate-500">{group.label}</div>
              {group.items.map(({ page: target, label, icon: Icon }) => {
                const active = page === target;
                return (
                  <a
                    key={target}
                    href={`#/${target}`}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "group relative mb-1 flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition-colors",
                      active ? "bg-white/10 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white",
                    )}
                  >
                    {active && <span className="absolute inset-y-2 left-0 w-1 rounded-full bg-flame" aria-hidden />}
                    <Icon size={19} aria-hidden className={active ? "text-flame" : "text-slate-400 group-hover:text-slate-200"} />
                    <span className="flex-1">{label}</span>
                    {badge(target)}
                  </a>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="border-t border-white/10 px-5 py-4 text-[12.5px] leading-relaxed text-slate-400">
          <div className="mb-0.5 font-semibold text-slate-300">Data sources</div>
          NASA FIRMS · OpenStreetMap · ESA WorldCover · Copernicus Sentinel-2 · Open-Meteo
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-panel px-4 py-3 md:px-6">
          <a href="#/overview" className="shrink-0 md:hidden" aria-label="GeoThermal Sentinel overview">
            <LogoMark size={36} />
          </a>
          <h1 className="font-display text-[22px] font-bold leading-tight tracking-tight text-ink">{title}</h1>
          <span className="hidden items-center gap-2 rounded-full border border-sky-100 bg-sky-50 px-3 py-1 text-[13.5px] text-sky-900 lg:inline-flex">
            <CalendarRange size={15} aria-hidden className="text-sky-600" />
            <span className="font-medium">
              {staticDataset ? "Archive window" : "FIRMS window"}: {fmtWindow(observation)}
            </span>
            {health?.last_ingestion && !staticDataset && (
              <span className="text-sky-800/70">· updated {timeAgo(health.last_ingestion.finished_at ?? health.last_ingestion.started_at)}</span>
            )}
          </span>
          {staticDataset && (
            <span className="hidden rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-[13px] font-semibold text-amber-900 sm:inline" title={health?.dataset?.label ?? undefined}>
              Archive dataset · not live
            </span>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Button
              icon={RefreshCw}
              loading={syncing}
              onClick={syncNow}
              disabled={staticDataset}
              title={staticDataset ? "This server shows a fixed archive dataset; FIRMS sync is off" : "Fetch the latest 24 h of NASA FIRMS detections"}
            >
              <span className="hidden sm:inline">Sync FIRMS</span>
            </Button>
            <Button icon={MessageSquare} variant="ghost" onClick={() => setAssistantOpen(true)} title="Ask the query assistant">
              <span className="hidden sm:inline">Ask</span>
            </Button>
            <a href="#/settings" title="Settings" aria-current={page === "settings" ? "page" : undefined} className={buttonClass(page === "settings" ? "primary" : "secondary")}>
              <Settings size={17} aria-hidden />
              <span className="hidden sm:inline">Settings</span>
            </a>
            {user ? (
              <div className="flex items-center gap-2">
                <span className="hidden items-center gap-2 rounded-full border border-line bg-slate-50 py-1 pl-1 pr-3 text-[13.5px] sm:inline-flex">
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-accent text-[12.5px] font-bold uppercase text-white">{user.username.slice(0, 1)}</span>
                  <span>
                    <b className="text-ink">{user.username}</b> <span className="text-muted">· {user.title}</span>
                  </span>
                </span>
                <Button variant="ghost" icon={LogOut} onClick={signOut} title="Sign out">
                  <span className="hidden sm:inline">Sign out</span>
                </Button>
              </div>
            ) : (
              <Button variant="primary" icon={LogIn} onClick={() => setSignInOpen(true)}>
                Sign in
              </Button>
            )}
          </div>
        </header>
        <nav className="no-print flex gap-1.5 overflow-x-auto border-b border-line bg-panel px-3 py-2 md:hidden" aria-label="Pages">
          {NAV.map(({ page: target, label, icon: Icon }) => (
            <a
              key={target}
              href={`#/${target}`}
              aria-current={page === target ? "page" : undefined}
              className={cx(
                "flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[14px] font-medium",
                page === target ? "bg-accent text-white" : "bg-sunk text-ink-2 hover:bg-slate-200",
              )}
            >
              <Icon size={15} aria-hidden />
              {label}
              {badge(target, true)}
            </a>
          ))}
        </nav>

        {(error || health?.status === "degraded") && (
          <div className="no-print flex flex-col gap-3 px-4 pt-4 md:px-6">
            {error && (
              <Callout tone="error" title={health ? "Data may be out of date" : "Backend not reachable"}>
                {error}
              </Callout>
            )}
            {health?.status === "degraded" && (
              <Callout tone="warn" title="System needs attention">
                {health.problems.join("; ")}
              </Callout>
            )}
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

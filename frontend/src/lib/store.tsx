import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, getToken, setToken } from "./api";
import type { DetectionSummary, Facility, Health, Incident, Summary, ThermalSource, User } from "./types";

export type ToastTone = "info" | "success" | "error";
export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface AppState {
  health: Health | null;
  summary: Summary | null;
  detections: DetectionSummary[];
  sources: ThermalSource[];
  facilities: Facility[];
  incidents: Incident[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  refreshIncidents: () => Promise<void>;

  user: User | null;
  demoPasswords: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
  can: (permission: string) => boolean;
  signInOpen: boolean;
  setSignInOpen: (open: boolean) => void;

  selectedDetectionId: string | null;
  openDetection: (id: string | null) => void;
  assistantOpen: boolean;
  setAssistantOpen: (open: boolean) => void;

  toasts: Toast[];
  notify: (tone: ToastTone, message: string) => void;
  dismissToast: (id: number) => void;
}

const AppContext = createContext<AppState | null>(null);

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

// Changes whenever the server has ingested new detections, re-run the analysis or recorded an analyst review.
function dataVersion(health: Health): string {
  return [JSON.stringify(health.last_ingestion), health.analysis?.finished_at, health.detections, health.last_review_at].join("|");
}

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [detections, setDetections] = useState<DetectionSummary[]>([]);
  const [sources, setSources] = useState<ThermalSource[]>([]);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [user, setUser] = useState<User | null>(null);
  const [demoPasswords, setDemoPasswords] = useState(false);
  const [signInOpen, setSignInOpen] = useState(false);
  const [selectedDetectionId, setSelectedDetectionId] = useState<string | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  const notify = useCallback((tone: ToastTone, message: string) => {
    const id = ++toastId.current;
    setToasts((current) => [...current, { id, tone, message }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), tone === "error" ? 9000 : 5000);
  }, []);
  const dismissToast = useCallback((id: number) => setToasts((current) => current.filter((t) => t.id !== id)), []);

  const refreshIncidents = useCallback(async () => {
    try {
      setIncidents((await api.incidents()).items);
    } catch (e) {
      notify("error", errorMessage(e));
    }
  }, [notify]);

  const loadedVersion = useRef<string | null>(null);

  const load = useCallback(async (silent: boolean) => {
    if (!silent) setLoading(true);
    const results = await Promise.allSettled([api.health(), api.summary(), api.detections(), api.sources(), api.facilities(), api.incidents()]);
    const [h, s, d, src, f, inc] = results;
    if (h.status === "fulfilled") {
      setHealth(h.value);
      loadedVersion.current = dataVersion(h.value);
    }
    if (s.status === "fulfilled") setSummary(s.value);
    if (d.status === "fulfilled") setDetections(d.value.items);
    if (src.status === "fulfilled") setSources(src.value.items);
    if (f.status === "fulfilled") setFacilities(f.value.items);
    if (inc.status === "fulfilled") setIncidents(inc.value.items);
    const firstFailure = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    setError(firstFailure ? errorMessage(firstFailure.reason) : null);
    if (!silent) setLoading(false);
  }, []);
  const refresh = useCallback(() => load(false), [load]);

  useEffect(() => {
    refresh();
    api
      .me()
      .then((me) => {
        setUser(me.user);
        setDemoPasswords(me.demo_passwords_active);
      })
      .catch(() => undefined);
    // Keep an open dashboard current without a reload: scheduled FIRMS syncs, re-analysis after threshold changes and
    // incident triage by other users appear within a minute, and all data reloads once the API is reachable again.
    let apiWasDown = false;
    const poll = async () => {
      try {
        const latest = await api.health();
        if (apiWasDown || dataVersion(latest) !== loadedVersion.current) {
          await load(true);
        } else {
          setHealth(latest);
          setIncidents((await api.incidents()).items);
        }
        apiWasDown = false;
      } catch {
        apiWasDown = true;
        setError("The API server is not reachable - showing the data loaded last.");
      }
    };
    const timer = window.setInterval(poll, 60000);
    const onVisible = () => {
      if (document.visibilityState === "visible") poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh, load]);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await api.login(username, password);
    setToken(result.access_token);
    setUser(result.user);
    setSignInOpen(false);
    notify("success", `Signed in as ${result.user.title.toLowerCase()} (${result.user.username})`);
  }, [notify]);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
    notify("info", "Signed out");
  }, [notify]);

  const can = useCallback((permission: string) => Boolean(user && getToken() && user.permissions.includes(permission)), [user]);

  const value = useMemo<AppState>(() => ({
    health, summary, detections, sources, facilities, incidents, loading, error, refresh, refreshIncidents,
    user, demoPasswords, signIn, signOut, can, signInOpen, setSignInOpen,
    selectedDetectionId, openDetection: setSelectedDetectionId, assistantOpen, setAssistantOpen,
    toasts, notify, dismissToast,
  }), [health, summary, detections, sources, facilities, incidents, loading, error, refresh, refreshIncidents, user, demoPasswords, signIn, signOut, can, signInOpen, selectedDetectionId, assistantOpen, toasts, notify, dismissToast]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used inside AppDataProvider");
  return context;
}

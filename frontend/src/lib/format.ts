const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function parseUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const iso = /Z$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function two(n: number) {
  return String(n).padStart(2, "0");
}

/** "13 Sep 2026, 20:06 UTC" - FIRMS acquisition times are UTC. */
export function fmtUtc(value: string | null | undefined, withYear = true): string {
  const d = parseUtc(value);
  if (!d) return "—";
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}${withYear ? ` ${d.getUTCFullYear()}` : ""}, ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} UTC`;
}

/** The same instant in Indian Standard Time (UTC+05:30). */
export function fmtIst(value: string | null | undefined): string {
  const d = parseUtc(value);
  if (!d) return "—";
  const ist = new Date(d.getTime() + 5.5 * 3600 * 1000);
  return `${ist.getUTCDate()} ${MONTHS[ist.getUTCMonth()]}, ${two(ist.getUTCHours())}:${two(ist.getUTCMinutes())} IST`;
}

export function fmtDay(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${y ? "" : ""}`;
}

export function fmtWindow(window: { start: string; end: string; days: number } | null | undefined): string {
  if (!window) return "no data yet";
  return `${fmtDay(window.start)} – ${fmtDay(window.end)} ${window.end.slice(0, 4)} (${window.days} days)`;
}

export function timeAgo(value: string | null | undefined): string {
  const d = parseUtc(value);
  if (!d) return "—";
  const minutes = Math.round((Date.now() - d.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function fmtInt(value: number | null | undefined): string {
  return value == null ? "—" : Math.round(value).toLocaleString("en-IN");
}

export function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPct(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtCoord(lat: number, lon: number): string {
  return `${lat.toFixed(4)}°N, ${lon.toFixed(4)}°E`;
}

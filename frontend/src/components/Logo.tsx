import { useId } from "react";
import { cx } from "./ui";

/** The GeoThermal Sentinel mark: a heat source on an orbit ring, as a satellite sees it. Gradient ids are unique per
 * copy, so a copy inside a hidden element (the sidebar on phones) never breaks the colours of another copy. */
export function LogoMark({ size = 36, className }: { size?: number; className?: string }) {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={cx("shrink-0", className)} role="img" aria-label="GeoThermal Sentinel logo">
      <defs>
        <linearGradient id={`${id}-tile`} x1="8" y1="4" x2="56" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#1e40af" />
          <stop offset="1" stopColor="#0b1d3a" />
        </linearGradient>
        <linearGradient id={`${id}-flame`} x1="32" y1="47" x2="32" y2="9" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#ea580c" />
          <stop offset="0.55" stopColor="#f97316" />
          <stop offset="1" stopColor="#fbbf24" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="15" fill={`url(#${id}-tile)`} />
      <path d="M11 45a21 6.5 0 0 1 42 0" fill="none" stroke="#60a5fa" strokeWidth="2.6" strokeLinecap="round" opacity="0.55" />
      <path
        d="M32 9c1.6 7.4 11.5 12 11.5 24.3C43.5 40.4 38.4 46 32 46s-11.5-5.6-11.5-12.4c0-5.6 3.2-9.3 6-12.4.6 3.6 2.5 6.1 5 7.1C30 23.6 29.6 15.6 32 9z"
        fill={`url(#${id}-flame)`}
      />
      <path d="M32 29.5c1.2 3.4 5 5 5 9.2 0 3.3-2.3 5.6-5 5.6s-5-2.3-5-5.3c0-2.7 1.8-4.3 3.1-6 .4 1.4 1.1 2.2 2.1 2.5-.6-2-.7-4 .1-6z" fill="#fff7ed" opacity="0.9" />
      <path d="M11 45a21 6.5 0 0 0 42 0" fill="none" stroke="#93c5fd" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="51.4" cy="42.4" r="2.8" fill="#dbeafe" />
    </svg>
  );
}

/** Mark and wordmark. "dark" is for the navy sidebar, "light" for white surfaces such as the printed briefing. */
export function Logo({ tone = "dark", size = 42, subtitle = "Fire intelligence for India" }: { tone?: "dark" | "light"; size?: number; subtitle?: string | null }) {
  return (
    <div className="flex items-center gap-3">
      <LogoMark size={size} />
      <div className="min-w-0 leading-tight">
        <div className={cx("font-display text-[18px] font-bold tracking-tight", tone === "dark" ? "text-white" : "text-ink")}>GeoThermal Sentinel</div>
        {subtitle && <div className={cx("mt-0.5 text-[12.5px] font-medium", tone === "dark" ? "text-slate-400" : "text-muted")}>{subtitle}</div>}
      </div>
    </div>
  );
}

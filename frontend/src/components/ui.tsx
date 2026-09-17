import { useEffect, type ButtonHTMLAttributes, type ComponentType, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Eye, Info, Loader2, X } from "lucide-react";
import {
  CATEGORY_META,
  CLASS_META,
  INCIDENT_STATUS_META,
  SEVERITY_META,
  type Category,
  type ClassCode,
  type IncidentStatus,
  type Severity,
} from "../lib/taxonomy";

type IconType = ComponentType<{ size?: number; className?: string }>;

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function escapeHtml(text: string | null | undefined): string {
  return (text ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch] as string);
}

/** Light tinted surfaces for the cards that matter most; "neutral" is a plain white card. */
export type Tone = "neutral" | "slate" | "sky" | "indigo" | "violet" | "emerald" | "rose" | "amber";

const TONE_SURFACE: Record<Tone, string> = {
  neutral: "border-line bg-panel",
  slate: "border-slate-200 bg-slate-50",
  sky: "border-sky-100 bg-sky-50",
  indigo: "border-indigo-100 bg-indigo-50",
  violet: "border-violet-100 bg-violet-50",
  emerald: "border-emerald-100 bg-emerald-50",
  rose: "border-rose-100 bg-rose-50",
  amber: "border-amber-100 bg-amber-50",
};

const TONE_ICON: Record<Tone, string> = {
  neutral: "bg-sunk text-ink-2",
  slate: "bg-slate-200/70 text-slate-700",
  sky: "bg-sky-100 text-sky-700",
  indigo: "bg-indigo-100 text-indigo-700",
  violet: "bg-violet-100 text-violet-700",
  emerald: "bg-emerald-100 text-emerald-700",
  rose: "bg-rose-100 text-rose-700",
  amber: "bg-amber-100 text-amber-800",
};

// Padding passed by a caller replaces the default padding: two padding utilities in one class list would conflict.
function hasPadding(className?: string) {
  return /(^|\s)p[xytrbl]?-/.test(className ?? "");
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  tone = "neutral",
  icon: Icon,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  tone?: Tone;
  icon?: IconType;
}) {
  return (
    <section className={cx("min-w-0 overflow-hidden rounded-2xl border shadow-card", TONE_SURFACE[tone], className)}>
      {(title || actions) && (
        <header className={cx("flex flex-wrap items-start justify-between gap-3 border-b px-5 pb-3.5 pt-4", tone === "neutral" ? "border-line" : "border-black/5")}>
          <div className="flex min-w-0 items-start gap-3">
            {Icon && (
              <span className={cx("grid h-9 w-9 shrink-0 place-items-center rounded-xl", TONE_ICON[tone])}>
                <Icon size={18} />
              </span>
            )}
            <div className="min-w-0">
              {title && <h2 className="font-display text-[17px] font-semibold leading-snug tracking-tight text-ink">{title}</h2>}
              {subtitle && <p className="mt-0.5 max-w-[80ch] text-[14px] leading-snug text-muted">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx(!hasPadding(bodyClassName) && "p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  color,
  tone = "neutral",
  icon: Icon,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  color?: string;
  tone?: Tone;
  icon?: IconType;
}) {
  return (
    <div className={cx("flex min-w-0 flex-col gap-2 rounded-2xl border px-5 py-4 shadow-card", TONE_SURFACE[tone])}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">{label}</span>
        {Icon && (
          <span className={cx("grid h-9 w-9 shrink-0 place-items-center rounded-xl", TONE_ICON[tone])}>
            <Icon size={18} />
          </span>
        )}
      </div>
      <span className="num font-display text-[32px] font-bold leading-none tracking-tight text-ink" style={color ? { color } : undefined}>
        {value}
      </span>
      {hint && <span className="text-[14px] leading-snug text-ink-2">{hint}</span>}
    </div>
  );
}

export function Dot({ color, size = 10, ring }: { color: string; size?: number; ring?: string }) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-full"
      style={{ width: size, height: size, background: color, boxShadow: ring ? `0 0 0 2px ${ring}` : undefined }}
    />
  );
}

export function ClassBadge({ code, compact = false }: { code: ClassCode; compact?: boolean }) {
  const meta = CLASS_META[code];
  if (!meta) return <span className="text-muted">{code}</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-[14px] text-ink">
      <Dot color={meta.color} />
      {compact ? meta.short : meta.label}
    </span>
  );
}

export function CategoryBadge({ category, confidence }: { category: Category; confidence?: number }) {
  const meta = CATEGORY_META[category];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[13px] font-semibold"
      style={{ borderColor: meta.color, color: meta.color }}
    >
      {meta.short}
      {confidence !== undefined && <span className="num font-medium">{confidence.toFixed(0)}%</span>}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[13px] font-semibold", meta.bg, meta.text)}>
      {severity !== "NORMAL" && <AlertTriangle size={13} aria-hidden />}
      {meta.label}
    </span>
  );
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  const meta = INCIDENT_STATUS_META[status];
  return <span className={cx("inline-flex rounded-full px-2.5 py-0.5 text-[13px] font-semibold", meta.bg, meta.text)}>{meta.label}</span>;
}

export function VerifyBadge({ title }: { title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-1 rounded-full border border-warn/40 bg-warn-soft px-2.5 py-0.5 text-[13px] font-semibold text-warn">
      <Eye size={13} aria-hidden />
      Needs verification
    </span>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "border border-accent bg-accent text-white shadow-sm hover:border-accent-strong hover:bg-accent-strong",
  secondary: "border border-line bg-panel text-ink shadow-sm hover:border-line-strong hover:bg-sunk",
  ghost: "border border-transparent bg-transparent text-ink-2 hover:bg-sunk hover:text-ink",
  danger: "border border-crit/30 bg-panel text-crit hover:bg-crit-soft",
};

/** Button styling for elements that are not <button>, such as the Settings link in the top bar. */
export function buttonClass(variant: ButtonVariant = "secondary", size: "sm" | "md" = "md", className?: string, iconOnly = false) {
  const sizing =
    size === "sm"
      ? iconOnly
        ? "h-8 w-8 rounded-lg"
        : "h-8 gap-1.5 rounded-lg px-3 text-[13.5px]"
      : iconOnly
        ? "h-10 w-10 rounded-xl"
        : "h-10 gap-2 rounded-xl px-4 text-[14.5px]";
  return cx(
    "inline-flex shrink-0 items-center justify-center whitespace-nowrap font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
    sizing,
    BUTTON_VARIANTS[variant],
    className,
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  icon: Icon,
  loading = false,
  children,
  className,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  icon?: IconType;
  loading?: boolean;
}) {
  const iconSize = size === "sm" ? 15 : 17;
  return (
    <button {...props} disabled={disabled || loading} className={buttonClass(variant, size, className, !children)}>
      {loading ? <Loader2 size={iconSize} className="animate-spin" /> : Icon ? <Icon size={iconSize} /> : null}
      {children}
    </button>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5 p-8 text-[15px] text-muted" role="status">
      <Loader2 size={18} className="animate-spin text-accent" />
      {label}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-1 rounded-xl border border-dashed border-line-strong bg-slate-50 px-5 py-6">
      <span className="text-[15px] font-semibold text-ink">{title}</span>
      {children && <span className="text-[14px] text-muted">{children}</span>}
    </div>
  );
}

export function Callout({ tone = "info", title, children, className }: { tone?: "info" | "warn" | "error" | "success"; title?: ReactNode; children?: ReactNode; className?: string }) {
  const styles = {
    info: { box: "border-sky-200 bg-sky-50 text-ink", icon: Info, iconClass: "text-sky-600" },
    warn: { box: "border-amber-200 bg-amber-50 text-ink", icon: AlertTriangle, iconClass: "text-amber-600" },
    error: { box: "border-rose-200 bg-rose-50 text-ink", icon: AlertTriangle, iconClass: "text-rose-600" },
    success: { box: "border-emerald-200 bg-emerald-50 text-ink", icon: CheckCircle2, iconClass: "text-emerald-600" },
  }[tone];
  const Icon = styles.icon;
  return (
    <div className={cx("flex gap-3 rounded-xl border px-4 py-3 text-[14.5px]", styles.box, className)}>
      <Icon size={18} className={cx("mt-0.5 shrink-0", styles.iconClass)} aria-hidden />
      <div className="min-w-0 leading-relaxed">
        {title && <div className="font-semibold">{title}</div>}
        {children}
      </div>
    </div>
  );
}

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = "max-w-2xl",
  footer,
  leading,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  width?: string;
  footer?: ReactNode;
  leading?: ReactNode;
}) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[3000] flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 backdrop-blur-sm sm:p-10" onMouseDown={onClose}>
      <div role="dialog" aria-modal className={cx("w-full rounded-2xl border border-line bg-panel shadow-float", width)} onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="flex min-w-0 items-center gap-3">
            {leading}
            <div className="min-w-0">
              <h2 className="font-display text-[20px] font-semibold leading-tight tracking-tight">{title}</h2>
              {subtitle && <p className="mt-1 text-[14px] text-muted">{subtitle}</p>}
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-sunk hover:text-ink" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, subtitle, children }: { open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode }) {
  useEscape(open, onClose);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[2500] flex justify-end bg-slate-900/30 backdrop-blur-[1px]" onMouseDown={onClose}>
      <aside
        role="dialog"
        aria-modal
        className="flex h-full w-full max-w-[680px] flex-col border-l border-line bg-panel shadow-float"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">
            <div className="font-display text-[19px] font-semibold leading-tight tracking-tight">{title}</div>
            {subtitle && <div className="mt-1 text-[14px] text-muted">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted hover:bg-sunk hover:text-ink" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </aside>
    </div>
  );
}

/** Input styling without a width; add a width class (w-auto, w-48, flex-1 ...) where it is used. */
export const inputBase =
  "rounded-lg border border-line bg-panel px-3 py-2 text-[14.5px] text-ink shadow-sm placeholder:text-muted/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:cursor-not-allowed disabled:bg-sunk disabled:text-muted";

/** Full-width input, for form fields. */
export const inputClass = `${inputBase} w-full`;

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("flex min-w-0 flex-col gap-1.5", className)}>
      <span className="text-[13.5px] font-semibold text-ink-2">{label}</span>
      {children}
      {hint && <span className="text-[13px] leading-snug text-muted">{hint}</span>}
    </label>
  );
}

export function Meter({ value, color = "#2453c9", className }: { value: number; color?: string; className?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={cx("h-2 w-full overflow-hidden rounded-full bg-sunk", className)}>
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export function KeyValues({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cx("grid grid-cols-[minmax(140px,auto)_1fr] gap-x-5 gap-y-2 text-[14.5px]", className)}>
      {rows.map(([label, value], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{label}</dt>
          <dd className="num min-w-0 break-words text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionHeading({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-2.5 mt-6 flex items-baseline justify-between gap-3 first:mt-0">
      <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] text-muted">{children}</h3>
      {hint && <span className="text-[13px] text-muted">{hint}</span>}
    </div>
  );
}

/** Alert reason codes as readable chips; the machine-readable code and its description are in the tooltip. */
export function ReasonCodeChips({ codes, descriptions, labels }: { codes?: string[] | null; descriptions?: Record<string, string>; labels: Record<string, string> }) {
  if (!codes?.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {codes.map((code) => (
        <span key={code} title={`${code}${descriptions?.[code] ? `: ${descriptions[code]}` : ""}`} className="rounded-full border border-line bg-slate-50 px-2.5 py-0.5 text-[13px] text-ink-2">
          {labels[code] ?? code}
        </span>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return (
    <div className="inline-flex max-w-full flex-wrap rounded-xl border border-line bg-sunk p-1" role="radiogroup">
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cx(
            "rounded-lg px-3 py-1.5 text-[14px] font-medium transition-colors",
            value === option.value ? "bg-panel text-ink shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A card whose body opens on request: secondary detail that should not crowd the page. */
export function Disclosure({
  title,
  subtitle,
  children,
  defaultOpen = false,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  return (
    <details className={cx("group min-w-0 overflow-hidden rounded-2xl border border-line bg-panel shadow-card", className)} open={defaultOpen}>
      <summary className="flex items-center justify-between gap-4 px-5 py-4 hover:bg-slate-50">
        <div className="min-w-0">
          <div className="font-display text-[17px] font-semibold tracking-tight text-ink">{title}</div>
          {subtitle && <div className="mt-0.5 text-[14px] text-muted">{subtitle}</div>}
        </div>
        <ChevronDown size={20} className="shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="border-t border-line p-5">{children}</div>
    </details>
  );
}

import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDay, fmtNum, fmtPct } from "../lib/format";
import { CATEGORY_META, CLASS_META, LANDCOVER_LABELS, type ClassCode } from "../lib/taxonomy";
import type { Contribution } from "../lib/types";
import { Dot, cx } from "./ui";

const AXIS = { stroke: "#64748b", fontSize: 12.5 };
const GRID = "#e8edf3";
const tooltipStyle = { borderRadius: 12, border: "1px solid #e2e8f0", fontSize: 13, boxShadow: "0 8px 24px rgb(15 23 42 / 0.12)" };

export function DailyCategoryChart({ data, height = 230 }: { data: { date: string; industrial: number; vegetation: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap="22%">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDay} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} labelFormatter={(label) => fmtDay(String(label))} cursor={{ fill: "#f1f5f9" }} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 13 }} />
        <Bar dataKey="industrial" name={CATEGORY_META.industrial.short} stackId="a" fill={CATEGORY_META.industrial.color} stroke="#fff" strokeWidth={1} />
        <Bar dataKey="vegetation" name={CATEGORY_META.vegetation.short} stackId="a" fill={CATEGORY_META.vegetation.color} stroke="#fff" strokeWidth={1} radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function HourlyChart({ data, height = 200 }: { data: { hour_utc: number; industrial: number; vegetation: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }} barCategoryGap="12%">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="hour_utc" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} interval={2} tickFormatter={(h) => `${String(h).padStart(2, "0")}h`} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} labelFormatter={(h) => `${String(h).padStart(2, "0")}:00 UTC (${String((Number(h) + 5) % 24).padStart(2, "0")}:30 IST)`} cursor={{ fill: "#f1f5f9" }} />
        <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 13 }} />
        <Bar dataKey="industrial" name={CATEGORY_META.industrial.short} stackId="a" fill={CATEGORY_META.industrial.color} />
        <Bar dataKey="vegetation" name={CATEGORY_META.vegetation.short} stackId="a" fill={CATEGORY_META.vegetation.color} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ClassBars({ classes, onSelect }: { classes: { code: ClassCode; detections: number; persistent_sources: number }[]; onSelect?: (code: ClassCode) => void }) {
  const total = classes.reduce((sum, c) => sum + c.detections, 0) || 1;
  const max = Math.max(...classes.map((c) => c.detections), 1);
  return (
    <div className="flex flex-col gap-2.5">
      {classes.map((c) => {
        const meta = CLASS_META[c.code];
        return (
          <button key={c.code} onClick={() => onSelect?.(c.code)} className={cx("group flex flex-col gap-1 text-left", onSelect && "cursor-pointer")}>
            <div className="flex items-center justify-between gap-2 text-[14px]">
              <span className="flex items-center gap-1.5 text-ink group-hover:underline">
                <Dot color={meta.color} />
                {meta.short}
              </span>
              <span className="num text-ink-2">
                {c.detections.toLocaleString("en-IN")} <span className="text-muted">({fmtPct(c.detections / total)})</span>
              </span>
            </div>
            <div className="h-2 w-full rounded-sm bg-sunk">
              <div className="h-full rounded-sm" style={{ width: `${(c.detections / max) * 100}%`, background: meta.color }} />
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function FrpSeriesChart({
  series,
  baselineMedian,
  threshold,
  height = 240,
}: {
  series: { date: string; max_frp: number | null; detections: number }[];
  baselineMedian?: number | null;
  threshold?: number | null;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series} margin={{ top: 12, right: 16, bottom: 0, left: -8 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tickFormatter={fmtDay} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} unit=" MW" width={64} />
        <Tooltip
          contentStyle={tooltipStyle}
          labelFormatter={(label) => fmtDay(String(label))}
          formatter={(value: any, _name: any, item: any) => [value == null ? "no detection" : `${fmtNum(Number(value))} MW (${item?.payload?.detections} det.)`, "Max FRP"]}
        />
        {baselineMedian != null && <ReferenceLine y={baselineMedian} stroke="#15803d" strokeDasharray="4 3" label={{ value: "baseline median", fill: "#15803d", fontSize: 12.5, position: "insideTopLeft" }} />}
        {threshold != null && <ReferenceLine y={threshold} stroke="#c0262d" strokeDasharray="4 3" label={{ value: "alert threshold", fill: "#c0262d", fontSize: 12.5, position: "insideTopLeft" }} />}
        <Line type="linear" dataKey="max_frp" stroke="#2453c9" strokeWidth={2} dot={{ r: 3.5, fill: "#2453c9", strokeWidth: 0 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ProbabilityBars({ probabilities, highlight }: { probabilities: Record<string, number>; highlight?: string }) {
  const entries = Object.entries(probabilities).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex flex-col gap-1.5">
      {entries.map(([code, p]) => {
        const meta = CLASS_META[code as ClassCode];
        return (
          <div key={code} className="grid grid-cols-[170px_1fr_52px] items-center gap-2 text-[14px]">
            <span className={cx("flex items-center gap-1.5 truncate", code === highlight ? "font-semibold text-ink" : "text-ink-2")}>
              <Dot color={meta?.color ?? "#999"} size={8} />
              {meta?.short ?? code}
            </span>
            <div className="h-2 rounded-sm bg-sunk">
              <div className="h-full rounded-sm" style={{ width: `${p * 100}%`, background: meta?.color ?? "#999" }} />
            </div>
            <span className="num text-right text-ink-2">{(p * 100).toFixed(1)}%</span>
          </div>
        );
      })}
    </div>
  );
}

export function LandcoverBar({ fractions }: { fractions: Record<string, number> }) {
  const entries = Object.entries(fractions).filter(([, v]) => v > 0.005).sort((a, b) => b[1] - a[1]);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-3.5 w-full overflow-hidden rounded-sm">
        {entries.map(([key, value]) => (
          <div key={key} title={`${LANDCOVER_LABELS[key]?.label ?? key}: ${fmtPct(value)}`} style={{ width: `${value * 100}%`, background: LANDCOVER_LABELS[key]?.color ?? "#ccc" }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[13.5px] text-ink-2">
        {entries.map(([key, value]) => (
          <span key={key} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: LANDCOVER_LABELS[key]?.color ?? "#ccc" }} />
            {LANDCOVER_LABELS[key]?.label ?? key} <span className="num text-muted">{fmtPct(value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function ContributionList({ items }: { items: Contribution[] }) {
  const max = Math.max(...items.map((i) => Math.abs(i.contribution)), 0.001);
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((item) => (
        <div key={item.feature} className="grid grid-cols-[1fr_120px] items-center gap-3 text-[14px]">
          <div className="min-w-0">
            <div className="truncate text-ink">{item.description}</div>
            <div className="num text-[13px] text-muted">value {item.value === null ? "not available" : fmtNum(item.value, 2)}</div>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="relative h-2 flex-1 rounded-sm bg-sunk">
              <div
                className="absolute top-0 h-full rounded-sm"
                style={{ width: `${(Math.abs(item.contribution) / max) * 50}%`, left: item.contribution >= 0 ? "50%" : undefined, right: item.contribution < 0 ? "50%" : undefined, background: item.contribution >= 0 ? "#15803d" : "#c0262d" }}
              />
              <div className="absolute left-1/2 top-[-2px] h-3 w-px bg-muted/50" />
            </div>
            <span className={cx("num w-10 text-right text-[13px]", item.contribution >= 0 ? "text-good" : "text-crit")}>
              {item.contribution >= 0 ? "+" : ""}
              {item.contribution.toFixed(2)}
            </span>
          </div>
        </div>
      ))}
      <div className="text-[12.5px] text-muted">Green supports the reported class, red argues against it (TreeSHAP log-odds contributions).</div>
    </div>
  );
}

export function ConfusionMatrix({ labels, matrix, labelFor }: { labels: string[]; matrix: number[][]; labelFor?: (label: string) => string }) {
  const name = labelFor ?? ((l: string) => l);
  return (
    <div className="overflow-x-auto">
      <table className="num border-collapse text-[13.5px]">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left font-normal text-muted">true ↓ / predicted →</th>
            {labels.map((l) => (
              <th key={l} className="max-w-[92px] px-2 py-1 text-left align-bottom font-medium text-ink-2">
                {name(l)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => {
            const total = row.reduce((a, b) => a + b, 0) || 1;
            return (
              <tr key={labels[i]}>
                <th className="whitespace-nowrap px-2 py-1 text-left font-medium text-ink-2">{name(labels[i])}</th>
                {row.map((value, j) => {
                  const share = value / total;
                  return (
                    <td
                      key={j}
                      title={`${value} of ${total} (${fmtPct(share, 1)})`}
                      className={cx("border border-panel px-2 py-1 text-right", i === j ? "font-semibold" : "")}
                      style={{ background: `rgba(31, 79, 191, ${Math.min(0.85, share * 0.9)})`, color: share > 0.5 ? "#fff" : "#0f172a" }}
                    >
                      {fmtPct(share, share < 0.1 && share > 0 ? 1 : 0)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-1 text-[12.5px] text-muted">Each row shows how detections of that true class were classified (row-normalised).</div>
    </div>
  );
}

import type { ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AlertTriangle,
  LoaderCircle,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { useI18n } from "./i18n";

export function Page({
  eyebrow,
  title,
  description,
  children,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="console-page mx-auto max-w-[1640px] px-3 py-4 md:px-5">
      <div className="page-heading mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-muted" />
            <span className="page-eyebrow text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
              {eyebrow}
            </span>
          </div>
          <h2 className="text-xl font-semibold tracking-[-0.02em] text-ink">
            {title}
          </h2>
          <p className="mt-0.5 max-w-3xl text-xs text-muted">{description}</p>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Panel({
  title,
  subtitle,
  children,
  className = "",
  action,
  titleClassName = "text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted",
  subtitleClassName = "text-[10.5px] text-faint",
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
  titleClassName?: string;
  subtitleClassName?: string;
}) {
  return (
    <section className={`rounded-card border border-line bg-structure p-[3px] shadow-card ${className}`}>
      <div className="rounded-inner border border-line bg-surface overflow-hidden flex flex-col h-full">
        <header className="panel-header flex min-h-9 items-center justify-between border-b border-line px-3.5 py-2">
          <div>
            <h3 className={`panel-title ${titleClassName}`}>{title}</h3>
            {subtitle && (
              <p className={`panel-subtitle mt-0.5 ${subtitleClassName}`}>{subtitle}</p>
            )}
          </div>
          {action}
        </header>
        <div className="flex-1 min-w-0">
          {children}
        </div>
      </div>
    </section>
  );
}

export function Sparkline({
  data,
  color = "var(--series-1)",
  height = 24,
}: {
  data: Array<{ value: number }> | number[];
  color?: string;
  height?: number;
}) {
  const points = data.map((d) => {
    const value = typeof d === "number" ? d : Number(d?.value ?? 0);
    return Number.isFinite(value) ? value : 0;
  });
  if (!points.length) {
    return <div className="h-px w-full bg-border" />;
  }
  const maxPoints = 48;
  const sampled = points.length <= maxPoints
    ? points
    : Array.from({ length: maxPoints }, (_, index) => points[Math.round(index * (points.length - 1) / (maxPoints - 1))]);
  const chartData = sampled.map((value, index) => ({ index, value }));

  return (
    <div style={{ height }} className="w-full overflow-hidden">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            activeDot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function InteractiveMetricCard({
  label,
  value,
  detail,
  subDetail,
  data,
  color,
  selected,
  onSelect,
  valueClass = "text-ink",
}: {
  label: string;
  value: string;
  detail: string;
  subDetail?: string;
  data: Array<{ timestamp_ms?: number; value: number }>;
  color: string;
  selected: boolean;
  onSelect: () => void;
  valueClass?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`min-w-0 cursor-pointer text-left transition-colors rounded-inner border p-2.5 shadow-card ${
        selected
          ? "border-accent ring-1 ring-accent bg-accent-soft"
          : "border-line bg-surface hover:bg-hover"
      } focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[11px] font-semibold uppercase tracking-[.08em] text-muted">{label}</span>
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      </div>
      <div className={`mt-1 font-mono text-[20px] font-semibold leading-none tabular-nums num ${valueClass}`}>{value}</div>
      <div className="mt-1 flex items-center justify-between gap-1 text-[10.5px]">
        <span className="truncate text-muted" title={detail}>{detail}</span>
        {subDetail && <span className="shrink-0 font-mono text-faint num">{subDetail}</span>}
      </div>
      <div className="mt-1.5 h-6">
        {data.length ? <Sparkline data={data} color={color} height={24} /> : <div className="h-px bg-border" />}
      </div>
    </button>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  subDetail,
  tone = "normal",
  accent,
  delta,
  sparkline,
  sparklineColor,
}: {
  label: string;
  value: string;
  detail: string;
  subDetail?: string;
  tone?: "normal" | "bad" | "good";
  accent?: "sky" | "emerald" | "violet" | "indigo" | "amber" | "rose" | "cyan" | "purple";
  delta?: number;
  sparkline?: Array<{ value: number }> | number[];
  sparklineColor?: string;
}) {
  const toneClasses = {
    normal: "text-ink",
    good: "text-good",
    bad: "text-bad",
  };

  const strokeColor =
    sparklineColor ||
    (accent ? "var(--accent)" : undefined) ||
    (tone === "bad" ? "var(--bad)" : tone === "good" ? "var(--good)" : "var(--accent)");

  return (
    <div className="min-w-0 rounded-inner border border-line bg-surface p-2.5 shadow-card transition-all duration-150 hover:border-line-strong">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
          {label}
        </span>
        {sparkline && (
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: strokeColor }} />
        )}
      </div>
      
      <div className={`mt-1 font-mono text-[20px] font-semibold leading-none tracking-[-0.02em] tabular-nums num ${toneClasses[tone]}`}>
        {value}
      </div>
      
      <div className="mt-1.5 flex min-h-4 items-center justify-between gap-1 text-[10.5px] text-muted">
        <div className="flex min-w-0 items-center gap-1">
          {delta != null && !isNaN(Number(delta)) && (
            <span className={`inline-flex items-center gap-0.5 font-mono font-medium num ${Number(delta) >= 0 ? "text-bad" : "text-good"}`}>
              {Number(delta) >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {Math.abs(Number(delta)).toFixed(1)}%
            </span>
          )}
          <span className="truncate">{detail}</span>
        </div>
        {subDetail && <span className="shrink-0 font-mono text-faint num">{subDetail}</span>}
      </div>

      {sparkline && sparkline.length > 0 && (
        <div className="mt-1.5 h-6">
          <Sparkline data={sparkline} color={strokeColor} height={24} />
        </div>
      )}
    </div>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="rounded-inner border border-line bg-surface grid min-h-48 place-items-center p-8 text-sm text-muted">
      <div className="flex flex-col items-center gap-3">
        <LoaderCircle className="animate-spin text-accent" size={22} />
        <span className="text-xs font-medium tracking-wide">{t("Aggregating real-time telemetry…")}</span>
      </div>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  const { t } = useI18n();
  return (
    <div className="rounded-inner border border-bad-bd bg-bad-bg flex min-h-40 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-bad">
      <div className="grid h-8 w-8 place-items-center rounded-full border border-bad/30 bg-bad-bg text-bad">
        <AlertTriangle size={18} />
      </div>
      <div className="max-w-md">
        <div className="font-semibold text-ink">{t("Telemetry Unavailable")}</div>
        <div className="mt-1 text-xs text-muted">{message}</div>
      </div>
    </div>
  );
}

export const n = (value: number | null | undefined, digits = 1) =>
  value == null || isNaN(Number(value))
    ? "0"
    : new Intl.NumberFormat("en-US", {
        notation: Number(value) >= 100_000 ? "compact" : "standard",
        maximumFractionDigits: digits,
      }).format(Number(value));

export const pct = (value: number | null | undefined) => {
  const v = Number(value || 0);
  return `${(v * 100).toFixed(v < 0.01 && v > 0 ? 2 : 1)}%`;
};

export const age = (ms: number | null) =>
  ms
    ? new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(
        -Math.max(0, Math.round((Date.now() - ms) / 60000)),
        "minute",
      )
    : "No data";

export const chartTooltip = {
  contentStyle: {
    backgroundColor: "var(--surface)",
    border: "1px solid var(--border-strong)",
    borderRadius: "var(--radius-ctl)",
    boxShadow: "var(--shadow-pop)",
    fontSize: "12px",
    padding: "8px 12px",
    color: "var(--text)",
  },
  labelStyle: { color: "var(--text)", fontWeight: 600, marginBottom: "4px" },
  itemStyle: { color: "var(--text)", padding: "2px 0" },
};

/** Reduce rendered line points while keeping each bucket's real min/max samples. */
export function minMaxDownsample<T extends object>(
  data: T[],
  valueKey: keyof T,
  maxPoints = 450,
): Array<T & { __sourceIndex: number }> {
  const indexed = data.map((point, index) => ({ ...point, __sourceIndex: index }));
  if (data.length <= maxPoints || data.length <= 2) return indexed;

  const interiorCount = data.length - 2;
  const groupCount = Math.max(1, Math.floor((maxPoints - 2) / 2));
  const selected = new Set<number>([0, data.length - 1]);
  for (let group = 0; group < groupCount; group += 1) {
    const start = 1 + Math.floor(group * interiorCount / groupCount);
    const end = 1 + Math.floor((group + 1) * interiorCount / groupCount);
    if (end <= start) continue;
    let minimumIndex = start;
    let maximumIndex = start;
    for (let index = start + 1; index < end; index += 1) {
      const value = Number((data[index] as unknown as Record<string, unknown>)[String(valueKey)]);
      if (!Number.isFinite(value)) continue;
      const minimum = Number((data[minimumIndex] as unknown as Record<string, unknown>)[String(valueKey)]);
      const maximum = Number((data[maximumIndex] as unknown as Record<string, unknown>)[String(valueKey)]);
      if (!Number.isFinite(minimum) || value < minimum) minimumIndex = index;
      if (!Number.isFinite(maximum) || value > maximum) maximumIndex = index;
    }
    selected.add(minimumIndex);
    selected.add(maximumIndex);
  }
  return [...selected].sort((left, right) => left - right).map((index) => indexed[index]);
}

export function TpsLineChart({
  data,
  label = "TPS",
  heightClassName = "h-44",
}: {
  data: Array<{ timestamp_ms: number; tps: number; expected_tps?: number | null }>;
  label?: string;
  heightClassName?: string;
}) {
  const { t } = useI18n();
  if (!data.length) {
    return <div className={`grid ${heightClassName} place-items-center text-xs text-muted`}>{t("No telemetry points in the selected window")}</div>;
  }
  const nowMs = Date.now();
  const completedData = data.filter((p) => p.timestamp_ms + 60_000 <= nowMs);
  const latest = completedData.length > 0 ? completedData[completedData.length - 1] : data[data.length - 1];
  const renderData = minMaxDownsample(completedData.length > 0 ? completedData : data, "tps");
  return (
    <div className={`tps-chart ${heightClassName} px-2 pb-2 pt-1`}>
      <ResponsiveContainer>
        <LineChart data={renderData} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={42} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(value) => new Date(Number(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} axisLine={{ stroke: "var(--border)" }} tickLine={false} />
          <YAxis width={42} tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(value) => Number(value).toLocaleString()} />
          <Tooltip {...chartTooltip} labelFormatter={(value) => new Date(Number(value)).toLocaleString()} formatter={(value: unknown) => [`${n(Number(value), 2)} TPS`, label]} />
          <Line type="linear" dataKey="tps" name={label} stroke="var(--series-1)" strokeWidth={1.5} dot={false} activeDot={{ r: 3, fill: "var(--surface)", stroke: "var(--series-1)" }} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <div className="pointer-events-none -mt-5 pr-2 text-right text-[10.5px] text-muted num">{n(latest.tps, 2)} TPS</div>
    </div>
  );
}

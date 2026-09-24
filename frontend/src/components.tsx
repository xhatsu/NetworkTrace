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
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Info,
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
      <div className="page-heading mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-[#2a2d30] pb-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
            <span className="page-eyebrow text-[10px] font-semibold uppercase tracking-[0.12em] text-[#5794f2]">
              {eyebrow}
            </span>
          </div>
          <h2 className="text-xl font-semibold tracking-[-0.02em] text-[#d8d9da]">
            {title}
          </h2>
          <p className="mt-0.5 max-w-3xl text-xs text-[#a7a9ab]">{description}</p>
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
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <section className={`panel overflow-hidden ${className}`}>
      <header className="panel-header flex min-h-9 items-center justify-between border-b border-[#2a2d30] px-3 py-2">
        <div>
          <h3 className="panel-title text-[11px] font-semibold uppercase tracking-[0.06em] text-[#d8d9da]">{title}</h3>
          {subtitle && (
            <p className="panel-subtitle mt-0.5 text-[10px] text-[#7b7d80]">{subtitle}</p>
          )}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

const accentColorMap: Record<string, string> = {
  sky: "#5794f2",
  emerald: "#73bf69",
  violet: "#b877d9",
  indigo: "#5794f2",
  amber: "#ff9830",
  rose: "#f2495c",
  cyan: "#56b9a8",
  purple: "#b877d9",
};

export function Sparkline({
  data,
  color = "#5794f2",
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
    return <div className="h-px w-full bg-[#303236]" />;
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
  valueClass = "text-[#d8d9da]",
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
    <button type="button" aria-pressed={selected} onClick={onSelect} className="metric-panel min-w-0 cursor-pointer p-2.5 text-left transition-colors hover:bg-[#181b1f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#5794f2]" style={{ borderColor: selected ? color : undefined }}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[10px] font-semibold uppercase tracking-[.08em] text-[#a7a9ab]">{label}</span>
        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      </div>
      <div className={`mt-1 font-mono text-[22px] font-semibold leading-none tabular-nums ${valueClass}`}>{value}</div>
      <div className="mt-1 flex items-center justify-between gap-1 text-[9.5px]">
        <span className="truncate text-[#7b7d80]" title={detail}>{detail}</span>
        {subDetail && <span className="shrink-0 font-mono text-[#a7a9ab]">{subDetail}</span>}
      </div>
      <div className="mt-1.5 h-6">
        {data.length ? <Sparkline data={data} color={color} height={24} /> : <div className="h-px bg-[#303236]" />}
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
    normal: "text-[#d8d9da]",
    good: "text-[#73bf69]",
    bad: "text-[#f2495c]",
  };

  const borderAccent = {
    normal: "hover:border-[#34373b]",
    good: "hover:border-[#73bf69]",
    bad: "hover:border-[#f2495c]",
  };

  const topBorderClasses = {
    sky: "border-t-2 border-t-blue-400",
    emerald: "border-t-2 border-t-green-400",
    violet: "border-t-2 border-t-purple-400",
    indigo: "border-t-2 border-t-blue-400",
    amber: "border-t-2 border-t-orange-400",
    rose: "border-t-2 border-t-red-400",
    cyan: "border-t-2 border-t-blue-400",
    purple: "border-t-2 border-t-purple-400",
  };

  const cardTopBorder = accent ? topBorderClasses[accent] : "";
  const strokeColor =
    sparklineColor ||
    (accent ? accentColorMap[accent] : undefined) ||
    (tone === "bad" ? "#f2495c" : tone === "good" ? "#73bf69" : "#5794f2");

  return (
    <div className={`metric-panel group relative overflow-hidden p-2.5 transition-all duration-150 ${cardTopBorder} ${borderAccent[tone]}`}>
      <div className="flex items-center justify-between">
        <span className="metric-label text-[10px] font-semibold uppercase tracking-[0.08em] text-[#a7a9ab]">
          {label}
        </span>
        {sparkline && (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: strokeColor }} />
        )}
      </div>
      
      <div
        className={`metric-value mt-1 font-mono text-[24px] font-semibold leading-none tracking-[-0.04em] tabular-nums ${toneClasses[tone]}`}
      >
        {value}
      </div>
      
      <div className="metric-meta mt-1.5 flex min-h-4 items-center justify-between gap-1 text-[9.5px] text-[#7b7d80]">
        <div className="flex min-w-0 items-center gap-1">
          {delta != null && !isNaN(Number(delta)) && (
            <span className={`inline-flex items-center gap-0.5 font-mono font-medium ${Number(delta) >= 0 ? "text-[#f2495c]" : "text-[#73bf69]"}`}>
              {Number(delta) >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {Math.abs(Number(delta)).toFixed(1)}%
            </span>
          )}
          <span className="truncate">{detail}</span>
        </div>
        {subDetail && <span className="shrink-0 font-mono text-[#a7a9ab]">{subDetail}</span>}
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
    <div className="panel grid min-h-48 place-items-center p-8 text-sm text-[#a7a9ab]">
      <div className="flex flex-col items-center gap-3">
        <LoaderCircle className="animate-spin text-blue-400" size={22} />
        <span className="text-xs font-medium tracking-wide">{t("Aggregating real-time telemetry…")}</span>
      </div>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  const { t } = useI18n();
  return (
    <div className="panel flex min-h-40 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-[#f2495c]">
      <div className="grid h-8 w-8 place-items-center rounded-full border border-red-500/40 bg-red-500/10">
        <AlertTriangle size={18} />
      </div>
      <div className="max-w-md">
        <div className="font-semibold text-[#d8d9da]">{t("Telemetry Unavailable")}</div>
        <div className="mt-1 text-xs text-[#a7a9ab]">{message}</div>
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
    backgroundColor: "#181b1f",
    border: "1px solid #34373b",
    borderRadius: "2px",
    boxShadow: "none",
    fontSize: "12px",
    padding: "8px 12px",
  },
  labelStyle: { color: "#d8d9da", fontWeight: 600, marginBottom: "4px" },
  itemStyle: { color: "#d8d9da", padding: "2px 0" },
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
  data: Array<{ timestamp_ms: number; tps: number }>;
  label?: string;
  heightClassName?: string;
}) {
  const { t } = useI18n();
  if (!data.length) {
    return <div className={`grid ${heightClassName} place-items-center text-xs text-[#7b7d80]`}>{t("No telemetry points in the selected window")}</div>;
  }
  const latest = data[data.length - 1];
  const renderData = minMaxDownsample(data, "tps");
  return (
    <div className={`tps-chart ${heightClassName} px-2 pb-2 pt-1`}>
      <ResponsiveContainer>
        <LineChart data={renderData} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#303236" vertical={false} />
          <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={42} tick={{ fill: "#7b7d80", fontSize: 10 }} tickFormatter={(value) => new Date(Number(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} axisLine={{ stroke: "#2a2d30" }} tickLine={false} />
          <YAxis width={42} tick={{ fill: "#7b7d80", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => Number(value).toLocaleString()} />
          <Tooltip {...chartTooltip} labelFormatter={(value) => new Date(Number(value)).toLocaleString()} formatter={(value: unknown) => [`${n(Number(value), 2)} TPS`, label]} />
          <Line type="linear" dataKey="tps" name={label} stroke="#5794f2" strokeWidth={2} dot={false} activeDot={{ r: 3, fill: "#d8d9da", stroke: "#5794f2" }} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <div className="pointer-events-none -mt-5 pr-2 text-right text-[10px] text-[#7b7d80]">{n(latest.tps, 2)} TPS</div>
    </div>
  );
}

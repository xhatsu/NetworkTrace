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

export function MetricCard({
  label,
  value,
  detail,
  tone = "normal",
  accent,
  delta,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "normal" | "bad" | "good";
  accent?: "sky" | "emerald" | "violet" | "indigo" | "amber" | "rose" | "cyan" | "purple";
  delta?: number;
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

  return (
    <div className={`metric-panel group relative overflow-hidden p-3 transition-all duration-150 ${cardTopBorder} ${borderAccent[tone]}`}>
      <div className="flex items-center justify-between">
        <span className="metric-label text-[10px] font-semibold uppercase tracking-[0.08em] text-[#a7a9ab]">
          {label}
        </span>
      </div>
      
      <div
        className={`metric-value mt-2 font-mono text-[28px] font-semibold leading-none tracking-[-0.04em] tabular-nums ${toneClasses[tone]}`}
      >
        {value}
      </div>
      
      <div className="metric-meta mt-2 flex min-h-4 items-center gap-1.5 text-[10px] text-[#7b7d80]">
        {delta != null && !isNaN(Number(delta)) && (
          <span className={`inline-flex items-center gap-0.5 font-mono font-medium ${Number(delta) >= 0 ? "text-[#f2495c]" : "text-[#73bf69]"}`}>
            {Number(delta) >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {Math.abs(Number(delta)).toFixed(1)}%
          </span>
        )}
        <span className="truncate">{detail}</span>
      </div>
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

export function TpsLineChart({
  data,
  label = "TPS",
}: {
  data: Array<{ timestamp_ms: number; tps: number }>;
  label?: string;
}) {
  const { t } = useI18n();
  if (!data.length) {
    return <div className="grid h-40 place-items-center text-xs text-[#7b7d80]">{t("No telemetry points in the selected window")}</div>;
  }
  const latest = data[data.length - 1];
  return (
    <div className="tps-chart h-44 px-2 pb-2 pt-1">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#303236" vertical={false} />
          <XAxis dataKey="timestamp_ms" type="number" domain={["dataMin", "dataMax"]} minTickGap={42} tick={{ fill: "#7b7d80", fontSize: 10 }} tickFormatter={(value) => new Date(Number(value)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} axisLine={{ stroke: "#2a2d30" }} tickLine={false} />
          <YAxis width={42} tick={{ fill: "#7b7d80", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(value) => Number(value).toLocaleString()} />
          <Tooltip {...chartTooltip} labelFormatter={(value) => new Date(Number(value)).toLocaleString()} formatter={(value: unknown) => [`${n(Number(value), 2)} TPS`, label]} />
          <Line type="monotone" dataKey="tps" name={label} stroke="#5794f2" strokeWidth={2} dot={false} activeDot={{ r: 3, fill: "#d8d9da", stroke: "#5794f2" }} connectNulls />
        </LineChart>
      </ResponsiveContainer>
      <div className="pointer-events-none -mt-5 pr-2 text-right font-mono text-[10px] text-[#a7a9ab]">{n(latest.tps, 2)} TPS</div>
    </div>
  );
}

import type { ReactNode } from "react";
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
    <div className="mx-auto max-w-[1640px] px-4 py-6 md:px-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-[rgba(255,255,255,0.06)] pb-5">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-indigo-500 shadow-[0_0_8px_#6366f1]" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-indigo-400">
              {eyebrow}
            </span>
          </div>
          <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[#f0f3f6]">
            {title}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-[#8b949e]">{description}</p>
        </div>
        {actions && <div className="flex items-center gap-2.5">{actions}</div>}
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
    <section className={`card overflow-hidden bg-[#0e1116] border border-[rgba(255,255,255,0.07)] shadow-panel ${className}`}>
      <header className="flex items-center justify-between border-b border-[rgba(255,255,255,0.06)] bg-[#12151c]/70 px-5 py-3.5 backdrop-blur-sm">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-[0.05em] text-[#e6edf3]">{title}</h3>
          {subtitle && (
            <p className="mt-0.5 text-[11px] text-[#8b949e]">{subtitle}</p>
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
  delta,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "normal" | "bad" | "good";
  delta?: number;
}) {
  const toneClasses = {
    normal: "text-[#f0f3f6]",
    good: "text-[#10b981]",
    bad: "text-[#f43f5e]",
  };

  const borderAccent = {
    normal: "hover:border-[rgba(255,255,255,0.14)]",
    good: "hover:border-emerald-500/40",
    bad: "hover:border-rose-500/40",
  };

  return (
    <div className={`card group relative overflow-hidden bg-[#0e1116] p-4 transition-all duration-200 ${borderAccent[tone]}`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#8b949e]">
          {label}
        </span>
        <div className="h-1.5 w-1.5 rounded-full bg-[rgba(255,255,255,0.15)] group-hover:bg-indigo-400 transition" />
      </div>
      
      <div
        className={`mt-2.5 font-mono text-[22px] font-semibold tracking-[-0.03em] tabular-nums ${toneClasses[tone]}`}
      >
        {value}
      </div>
      
      <div className="mt-2 flex items-center gap-1.5 text-[11px] text-[#8b949e]">
        {delta != null && !isNaN(Number(delta)) && (
          <span className={`inline-flex items-center gap-0.5 font-mono font-medium ${Number(delta) >= 0 ? "text-[#f43f5e]" : "text-[#10b981]"}`}>
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
  return (
    <div className="card grid min-h-64 place-items-center bg-[#0e1116] p-8 text-sm text-[#8b949e]">
      <div className="flex flex-col items-center gap-3">
        <LoaderCircle className="animate-spin text-indigo-400" size={24} />
        <span className="text-xs font-medium tracking-wide">Aggregating real-time telemetry…</span>
      </div>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="card flex min-h-48 flex-col items-center justify-center gap-3 bg-[#0e1116] p-6 text-center text-sm text-[#f43f5e]">
      <div className="grid h-10 w-10 place-items-center rounded-full bg-rose-500/10 border border-rose-500/20">
        <AlertTriangle size={18} />
      </div>
      <div className="max-w-md">
        <div className="font-semibold text-[#f0f3f6]">Telemetry Unavailable</div>
        <div className="mt-1 text-xs text-[#8b949e]">{message}</div>
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
    backgroundColor: "rgba(14, 17, 22, 0.95)",
    backdropFilter: "blur(8px)",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    borderRadius: "8px",
    boxShadow: "0 10px 30px -5px rgba(0, 0, 0, 0.7)",
    fontSize: "12px",
    padding: "8px 12px",
  },
  labelStyle: { color: "#8b949e", fontWeight: 600, marginBottom: "4px" },
  itemStyle: { color: "#f0f3f6", padding: "2px 0" },
};

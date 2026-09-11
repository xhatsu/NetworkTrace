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
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-[rgba(255,255,255,0.12)] pb-5">
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-500 shadow-[0_0_8px_#8b5cf6]" />
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-violet-400">
              {eyebrow}
            </span>
          </div>
          <h2 className="text-2xl font-semibold tracking-[-0.03em] text-[#f5f3fa]">
            {title}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-[#c4bdd9]">{description}</p>
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
    <section className={`card overflow-hidden bg-[#1a172a] border border-[rgba(255,255,255,0.12)] shadow-panel ${className}`}>
      <header className="flex items-center justify-between border-b border-[rgba(255,255,255,0.10)] bg-[#1e1a30]/80 px-5 py-3.5 backdrop-blur-sm">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-[0.05em] text-[#f5f3fa]">{title}</h3>
          {subtitle && (
            <p className="mt-0.5 text-[11px] text-[#c4bdd9]">{subtitle}</p>
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
    normal: "text-[#f5f3fa]",
    good: "text-[#34d399]",
    bad: "text-[#fb7185]",
  };

  const borderAccent = {
    normal: "hover:border-[rgba(255,255,255,0.25)]",
    good: "hover:border-emerald-500/60",
    bad: "hover:border-rose-500/60",
  };

  const topBorderClasses = {
    sky: "border-t-2 border-t-sky-400/80",
    emerald: "border-t-2 border-t-emerald-400/80",
    violet: "border-t-2 border-t-violet-400/80",
    indigo: "border-t-2 border-t-indigo-400/80",
    amber: "border-t-2 border-t-amber-400/80",
    rose: "border-t-2 border-t-rose-400/80",
    cyan: "border-t-2 border-t-cyan-400/80",
    purple: "border-t-2 border-t-purple-400/80",
  };

  const dotClasses = {
    sky: "bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.8)]",
    emerald: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]",
    violet: "bg-violet-400 shadow-[0_0_8px_rgba(167,139,250,0.8)]",
    indigo: "bg-indigo-400 shadow-[0_0_8px_rgba(129,140,248,0.8)]",
    amber: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]",
    rose: "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.8)]",
    cyan: "bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]",
    purple: "bg-purple-400 shadow-[0_0_8px_rgba(192,132,252,0.8)]",
  };

  const cardTopBorder = accent ? topBorderClasses[accent] : "";
  const dotColor = accent ? dotClasses[accent] : "bg-[rgba(255,255,255,0.2)] group-hover:bg-violet-400";

  return (
    <div className={`card group relative overflow-hidden bg-[#1a172a] p-4 transition-all duration-200 ${cardTopBorder} ${borderAccent[tone]}`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[#9e96b8]">
          {label}
        </span>
        <div className={`h-2 w-2 rounded-full transition ${dotColor}`} />
      </div>
      
      <div
        className={`mt-2.5 font-mono text-[22px] font-semibold tracking-[-0.03em] tabular-nums ${toneClasses[tone]}`}
      >
        {value}
      </div>
      
      <div className="mt-2 flex items-center gap-1.5 text-[11px] text-[#c4bdd9]">
        {delta != null && !isNaN(Number(delta)) && (
          <span className={`inline-flex items-center gap-0.5 font-mono font-medium ${Number(delta) >= 0 ? "text-[#fb7185]" : "text-[#34d399]"}`}>
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
    <div className="card grid min-h-64 place-items-center bg-[#1a172a] border border-[rgba(255,255,255,0.12)] p-8 text-sm text-[#c4bdd9]">
      <div className="flex flex-col items-center gap-3">
        <LoaderCircle className="animate-spin text-violet-400" size={24} />
        <span className="text-xs font-medium tracking-wide">Aggregating real-time telemetry…</span>
      </div>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="card flex min-h-48 flex-col items-center justify-center gap-3 bg-[#1a172a] border border-rose-500/30 p-6 text-center text-sm text-[#fb7185]">
      <div className="grid h-10 w-10 place-items-center rounded-full bg-rose-500/15 border border-rose-500/30">
        <AlertTriangle size={18} />
      </div>
      <div className="max-w-md">
        <div className="font-semibold text-[#f5f3fa]">Telemetry Unavailable</div>
        <div className="mt-1 text-xs text-[#c4bdd9]">{message}</div>
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
    backgroundColor: "rgba(26, 23, 42, 0.96)",
    backdropFilter: "blur(8px)",
    border: "1px solid rgba(255, 255, 255, 0.18)",
    borderRadius: "8px",
    boxShadow: "0 10px 30px -5px rgba(0, 0, 0, 0.7)",
    fontSize: "12px",
    padding: "8px 12px",
  },
  labelStyle: { color: "#c4bdd9", fontWeight: 600, marginBottom: "4px" },
  itemStyle: { color: "#f5f3fa", padding: "2px 0" },
};

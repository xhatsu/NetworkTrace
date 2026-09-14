import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowLeft,
  ArrowRight,
  Box,
  CheckCircle2,
  Clock,
  Layers,
  Search,
  Server,
  Workflow,
} from "lucide-react";
import { api, queryString } from "../api";
import {
  ErrorState,
  Loading,
  MetricCard,
  Page,
  Panel,
  chartTooltip,
  n,
  pct,
} from "../components";
import { useFilters } from "../App";
import type { SeriesPoint } from "../types";

type Service = {
  name: string;
  environment: string;
  service_group: string;
  service_module: string;
  first_seen_ms: number;
  last_seen_ms: number;
};

export function ServicesPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [filterQuery, setFilterQuery] = useState("");
  const qs = queryString(filters);

  const query = useQuery({
    queryKey: ["services", qs],
    queryFn: () => api<{ items: Service[] }>(`/api/v1/services?${qs}&limit=500`),
  });
  const filteredItems = (query.data?.items || []).filter((s) => {
    if (!filterQuery) return true;
    const q = filterQuery.toLowerCase();
    return (
      (s.name || "").toLowerCase().includes(q) ||
      (s.service_group || "").toLowerCase().includes(q) ||
      (s.service_module || "").toLowerCase().includes(q) ||
      (s.environment || "").toLowerCase().includes(q)
    );
  });

  return (
    <Page
      eyebrow="Inventory & Catalog"
      title="Service Estate Directory"
      description="Observed service nodes with environment segmentation, functional group ownership, and telemetry freshness."
      actions={
        <div className="relative w-72">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-cyan-400" />
          <input
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="Filter by name, group, module…"
            className="w-full rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] pl-9 pr-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] focus:border-cyan-400 focus:bg-white/[0.08] focus:outline-none"
          />
        </div>
      }
    >
      {query.isLoading ? (
        <Loading />
      ) : (
        <Panel
          title={`${filteredItems.length} of ${query.data?.items.length || 0} Registered Services`}
          subtitle="Click any service to inspect latency tails, operation breakdown, and callers"
        >
          <div className="grid gap-2.5 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredItems.map((s, idx) => {
              const iconColors = [
                "border-sky-500/35 bg-sky-500/15 text-sky-300",
                "border-violet-500/35 bg-violet-500/15 text-violet-300",
                "border-emerald-500/35 bg-emerald-500/15 text-emerald-300",
                "border-amber-500/35 bg-amber-500/15 text-amber-300",
                "border-rose-500/35 bg-rose-500/15 text-rose-300",
                "border-cyan-500/35 bg-cyan-500/15 text-cyan-300",
                "border-indigo-500/35 bg-indigo-500/15 text-indigo-300",
              ];
              const iconStyle = iconColors[idx % iconColors.length];
              const envStyle = s.environment === "production"
                ? "border-emerald-500/35 bg-emerald-500/15 text-emerald-300"
                : "border-amber-500/35 bg-amber-500/15 text-amber-300";

              return (
                <button
                  key={s.name}
                  onClick={() =>
                    nav(
                      `/services/${encodeURIComponent(s.name)}?${queryString(filters)}`,
                    )
                  }
                  className="group relative flex flex-col justify-between rounded-lg border border-[rgba(255,255,255,0.12)] bg-[#1a172a] p-4 text-left transition hover:border-violet-500/50 hover:bg-[#221e38] hover:shadow-panel"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg border ${iconStyle}`}>
                          <Box size={16} />
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-xs font-semibold text-[#f5f3fa] group-hover:text-cyan-300 transition">
                            {s.name}
                          </div>
                          <div className="truncate text-[10px] text-violet-300/80">
                            {s.service_group} · {s.service_module}
                          </div>
                        </div>
                      </div>
                      <ArrowRight size={13} className="text-[#9e96b8] group-hover:text-white transition group-hover:translate-x-0.5" />
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-[rgba(255,255,255,0.08)] pt-3 text-[10px]">
                    <span className={`rounded border px-1.5 py-0.5 font-mono ${envStyle}`}>
                      {s.environment}
                    </span>
                    <span className="text-[#c4bdd9]">
                      Active {new Date(s.last_seen_ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                </button>
              );
            })}
            {filteredItems.length === 0 && (
              <div className="col-span-full py-12 text-center text-xs text-[#c4bdd9]">
                No services match "{filterQuery}".
              </div>
            )}
          </div>
        </Panel>
      )}
    </Page>
  );
}

type Detail = {
  service: Service;
  series: SeriesPoint[];
  operations: {
    name: string;
    requests: number;
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
    slow_rate: number;
    failure_rate: number;
    status_2xx: number;
    status_4xx: number;
    status_5xx: number;
  }[];
  accounts: { username: string; requests: number }[];
  instances: { name: string; operation: string; requests: number; avg_ms: number }[];
  incoming: { name: string; requests: number; evidence: string }[];
  outgoing: { name: string; requests: number; evidence: string }[];
};

export function ServiceDetailPage() {
  const { name = "" } = useParams();
  const { filters } = useFilters();
  const nav = useNavigate();
  const qs = queryString({ ...filters, service: undefined });

  const query = useQuery({
    queryKey: ["service", name, qs],
    queryFn: () =>
      api<Detail>(`/api/v1/services/${encodeURIComponent(name)}?${qs}`),
  });
  const serviceUsers = useQuery({
    queryKey: ["service-users", name, qs],
    queryFn: () => api<{items: Array<{principal_name:string;requests:number;callers:number;operations:number;first_seen:number;last_seen:number;recent_change:number}>}>(`/api/v1/services/${encodeURIComponent(name)}/users?${qs}`),
  });

  if (query.isLoading) {
    return (
      <Page eyebrow="Service Drilldown" title={name} description="Loading service telemetry…">
        <Loading />
      </Page>
    );
  }

  if (query.error) {
    return (
      <Page eyebrow="Service Drilldown" title={name} description="">
        <ErrorState message={query.error.message} />
      </Page>
    );
  }

  const d = query.data!;
  const serviceObj = typeof d.service === "object" && d.service ? d.service : ((d as any).service_meta || {
    name: (d as any).name || name,
    environment: "production",
    service_group: "Core",
    service_module: "Default",
    first_seen_ms: 0,
    last_seen_ms: 0
  });
  const operations = d.operations || [];
  const total = operations.reduce((a, b) => a + (b.requests || 0), 0);
  const p95 = operations.length
    ? Math.max(...operations.map((o) => o.p95_ms || 0))
    : 0;
  const fail =
    operations.reduce((a, b) => a + (b.failure_rate || 0) * (b.requests || 0), 0) /
    Math.max(1, total);
  const incoming = d.incoming || (d as any).callers || [];
  const outgoing = d.outgoing || (d as any).dependencies || [];
  const accounts = d.accounts || ((d as any).principals || []).map((p: any) => ({ username: p.name, requests: p.requests }));
  const instances = d.instances || [];
  const series = d.series || [];

  const durationSec = Math.max(
    1,
    (new Date(filters.end).getTime() - new Date(filters.start).getTime()) / 1000,
  );

  return (
    <Page
      eyebrow="Service Drilldown"
      title={name}
      description={`${serviceObj.service_group || "Core"} / ${serviceObj.service_module || "Default"} · Environment: ${serviceObj.environment || "production"}`}
      actions={
        <button
          className="btn"
          onClick={() => nav(`/services?${qs}`)}
        >
          <ArrowLeft size={13} />
          All Services
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard
          label="Observed Volume"
          value={n(total)}
          detail="Server transactions"
        />
        <MetricCard
          label="Request Rate"
          value={`${n(total / durationSec, 2)}/s`}
          detail="Observed rate in window"
        />
        <MetricCard
          label="Worst Operation p95"
          value={`${n(p95)} ms`}
          detail={`Across ${operations.length} operations`}
          tone={p95 > 500 ? "bad" : "normal"}
        />
        <MetricCard
          label="Failure Rate"
          value={pct(fail)}
          detail={`n=${n(total)} requests`}
          tone={fail > 0.02 ? "bad" : "normal"}
        />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        <Panel
          title="Throughput & p95 Latency Trend"
          subtitle="Observed RPS and merged histogram p95 values"
          className="lg:col-span-8"
        >
          <div className="h-72 p-3">
            <ResponsiveContainer>
              <AreaChart data={series}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis
                  dataKey="timestamp_ms"
                  tickFormatter={(v) =>
                    new Date(v).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  }
                  stroke="#484f58"
                />
                <YAxis stroke="#484f58" />
                <Tooltip {...chartTooltip} />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
                <Area
                  dataKey="p95_ms"
                  name="p95 Latency (ms)"
                  stroke="#f43f5e"
                  fill="#f43f5e"
                  fillOpacity={0.1}
                  strokeWidth={1.5}
                />
                <Area
                  dataKey="rps"
                  name="Observed RPS"
                  stroke="#818cf8"
                  fill="#818cf8"
                  fillOpacity={0.15}
                  strokeWidth={1.5}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel
          title="Dependency Relationships"
          subtitle="Confirmed & inferred directional trace links"
          className="lg:col-span-4"
        >
          <div className="p-4 space-y-4">
            <Relation title="Incoming Callers" items={incoming} />
            <Relation title="Outgoing Dependencies" items={outgoing} />
          </div>
        </Panel>
      </div>

      <Panel
        title="Operation Performance Inventory"
        subtitle="Latency percentiles from merged logarithmic histograms · Status codes breakdown"
        className="mt-4"
      >
        <div className="overflow-auto scrollbar">
          <table className="w-full min-w-[850px]">
            <thead>
              <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01]">
                {[
                  "Operation",
                  "Requests",
                  "p50 Median",
                  "p95 Latency",
                  "p99 Tail",
                  "Slow >1s %",
                  "Status Codes (2xx / 4xx / 5xx)",
                ].map((h) => (
                  <th key={h} className="table-head px-4 py-2.5">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {operations.map((o) => (
                <tr
                  key={o.name}
                  className="border-b border-[rgba(255,255,255,0.04)] transition hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3 text-xs font-medium text-[#f0f3f6]">{o.name}</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#c9d1d9]">{n(o.requests)}</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">{n(o.p50_ms || 0)} ms</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#818cf8]">{n(o.p95_ms || 0)} ms</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#f43f5e]">{n(o.p99_ms || 0)} ms</td>
                  <td className="px-4 font-mono text-xs tabular-nums text-[#8b949e]">{pct(o.slow_rate || 0)}</td>
                  <td className="px-4 font-mono text-xs tabular-nums">
                    <span className="text-emerald-400">{n(o.status_2xx || 0)}</span>
                    <span className="text-[#6e7681]"> / </span>
                    <span className="text-amber-400">{n(o.status_4xx || 0)}</span>
                    <span className="text-[#6e7681]"> / </span>
                    <span className="text-rose-400">{n(o.status_5xx || 0)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel
          title="Account Identity Distribution"
          subtitle="Presented authentication principals on requests to this service"
        >
          <SimpleTable
            rows={accounts.map((a: any) => ({
              name: a.username || a.name || "unknown",
              requests: a.requests || 0,
            }))}
          />
        </Panel>

        <Panel
          title="Instance Load & Distribution"
          subtitle="Traffic balance across recorded nodes"
        >
          <SimpleTable rows={instances} />
        </Panel>
      </div>
      <Panel title="Users" subtitle="Principals observed using this service · click to open User Intelligence" className="mt-4">
        <div className="overflow-auto"><table className="w-full text-xs"><thead><tr>{["Principal","Requests","Callers","Operations","First seen","Last seen","Recent change"].map(h=><th className="table-head px-3 py-2" key={h}>{h}</th>)}</tr></thead><tbody>{(serviceUsers.data?.items||[]).map(u=><tr key={u.principal_name} onClick={()=>nav(`/users/${encodeURIComponent(u.principal_name)}?${qs}`)} className="cursor-pointer border-t border-white/[.05] hover:bg-white/[.03]"><td className="px-3 py-2 font-mono text-indigo-300">{u.principal_name}</td><td className="px-3 font-mono">{n(u.requests,0)}</td><td className="px-3 font-mono">{u.callers}</td><td className="px-3 font-mono">{u.operations}</td><td className="px-3 text-[#8b949e]">{new Date(u.first_seen).toLocaleString()}</td><td className="px-3 text-[#8b949e]">{new Date(u.last_seen).toLocaleString()}</td><td className="px-3">{u.recent_change?<span className="rounded bg-amber-500/10 px-2 py-1 text-amber-400">Changed</span>:"—"}</td></tr>)}</tbody></table></div>
      </Panel>
    </Page>
  );
}

function Relation({
  title,
  items,
}: {
  title: string;
  items?: { name: string; requests: number; evidence: string }[];
}) {
  const safeItems = items || [];
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e] mb-2">
        {title}
      </div>
      {safeItems.length ? (
        <div className="divide-y divide-[rgba(255,255,255,0.04)]">
          {safeItems.slice(0, 6).map((i) => (
            <div
              className="flex items-center justify-between py-2 text-xs"
              key={i.name}
            >
              <span className="font-medium text-[#f0f3f6] truncate max-w-[180px]">{i.name}</span>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${
                    i.evidence === "confirmed"
                      ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                      : "border border-amber-500/30 bg-amber-500/10 text-amber-400"
                  }`}
                >
                  {i.evidence}
                </span>
                <span className="font-mono text-xs tabular-nums text-[#8b949e]">{n(i.requests)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-[rgba(255,255,255,0.08)] p-3 text-center text-[11px] text-[#8b949e]">
          No explicit edge evidence recorded
        </div>
      )}
    </div>
  );
}

function SimpleTable({
  rows,
}: {
  rows?: { name: string; operation?: string; requests: number; avg_ms?: number }[];
}) {
  const safeRows = rows || [];
  return (
    <div className="divide-y divide-[rgba(255,255,255,0.04)]">
      {safeRows.map((r) => (
        <div
          key={`${r.name}:${r.operation || ""}`}
          className="flex items-center justify-between px-4 py-2.5 text-xs hover:bg-white/[0.02]"
        >
          <div className="min-w-0">
            <span className="font-medium text-[#f0f3f6]">{r.name}</span>
            {r.operation && (
              <span className="ml-2 text-[10px] text-[#8b949e]">{r.operation}</span>
            )}
          </div>
          <div className="font-mono text-xs tabular-nums text-[#8b949e]">
            {n(r.requests)}
            {r.avg_ms !== undefined && ` · ${n(r.avg_ms)} ms avg`}
          </div>
        </div>
      ))}
      {!safeRows.length && (
        <div className="p-8 text-center text-xs text-[#8b949e]">No records found.</div>
      )}
    </div>
  );
}

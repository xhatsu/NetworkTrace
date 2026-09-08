import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowLeft,
  KeyRound,
  Search,
  ShieldAlert,
  UserCheck,
  Activity,
  Layers,
  Clock,
  ExternalLink,
  Target,
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

export type PrincipalItem = {
  principal_name: string;
  total_requests: number;
  total_errors: number;
  error_rate: number;
  p95_latency: number;
  target_count: number;
  operation_count: number;
  first_seen_ms: number;
  last_seen_ms: number;
};

export function PrincipalsPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [searchTerm, setSearchTerm] = useState("");

  const q = useQuery({
    queryKey: ["principals"],
    queryFn: () => api<{ items: PrincipalItem[]; count: number }>("/api/v1/principals?limit=200"),
  });

  const filteredItems = (q.data?.items || []).filter((p) => {
    if (!searchTerm) return true;
    return p.principal_name.toLowerCase().includes(searchTerm.toLowerCase());
  });

  return (
    <Page
      eyebrow="Identity Behavioral Observability"
      title="Principal Accounts & Actors"
      description="Authenticated usernames, service identities, and client actors extracted safely from headers/tokens. Passwords discarded in-memory prior to persistence."
      actions={
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2 text-[#8b949e]" size={13} />
            <input
              type="text"
              placeholder="Search principals..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="h-8 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] pl-8 pr-3 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] focus:border-indigo-500/50 focus:outline-none"
            />
          </div>
          <div className="chip font-mono text-[10px] text-emerald-400 border-emerald-500/20">
            <span>In-Memory Sanitized</span>
          </div>
        </div>
      }
    >
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : (
        <Panel
          title={`${filteredItems.length} Principals Tracked`}
          subtitle="Identity caveat: Presented request identity extracted from HTTP headers / bearer tokens. Not mathematical cryptographic proof of identity."
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full min-w-[900px] text-left">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01] text-[11px] font-semibold uppercase tracking-wider text-[#8b949e]">
                  <th className="px-4 py-3">Principal Name</th>
                  <th className="px-4 py-3 text-right">Total Requests</th>
                  <th className="px-4 py-3 text-right">Error Rate</th>
                  <th className="px-4 py-3 text-right">p95 Latency</th>
                  <th className="px-4 py-3 text-right">Target Services</th>
                  <th className="px-4 py-3 text-right">Operations</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(255,255,255,0.04)] text-xs">
                {filteredItems.map((p) => (
                  <tr
                    key={p.principal_name}
                    onClick={() => nav(`/principals/${encodeURIComponent(p.principal_name)}?${queryString(filters)}`)}
                    className="cursor-pointer transition hover:bg-white/[0.03]"
                  >
                    <td className="px-4 py-3 font-medium text-[#f0f3f6]">
                      <div className="flex items-center gap-2">
                        <div className="grid h-7 w-7 place-items-center rounded bg-indigo-500/10 text-indigo-400">
                          <KeyRound size={13} />
                        </div>
                        <span className="font-mono text-indigo-300">{p.principal_name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#c9d1d9]">
                      {n(p.total_requests)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      <span className={p.error_rate > 0.05 ? "text-rose-400 font-semibold" : p.error_rate > 0 ? "text-amber-400" : "text-emerald-400"}>
                        {pct(p.error_rate)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#c9d1d9]">
                      {Number(p.p95_latency || 0).toFixed(1)} ms
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#8b949e]">
                      {p.target_count || 1}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-[#8b949e]">
                      {p.operation_count || 1}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="inline-flex items-center gap-1 text-[11px] text-indigo-400 hover:text-indigo-300">
                        View Profile <ExternalLink size={11} />
                      </span>
                    </td>
                  </tr>
                ))}
                {filteredItems.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-xs text-[#8b949e]">
                      No principals found matching query.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </Page>
  );
}

type PrincipalProfile = {
  principal_name: string;
  targets: Array<{ target_service: string; requests: number; error_rate: number; p95_latency: number }>;
  operations: Array<{ operation: string; requests: number; error_rate: number; p95_latency: number }>;
  callers: Array<{ caller_service: string; requests: number }>;
  hourly_profile: Array<{ hour_of_day: number; requests: number; error_count: number }>;
};

export function PrincipalDetailPage() {
  const { name = "", username = "" } = useParams();
  const principalName = name || username;
  const { filters } = useFilters();
  const nav = useNavigate();

  const q = useQuery({
    queryKey: ["principal", principalName],
    queryFn: () => api<PrincipalProfile>(`/api/v1/principals/${encodeURIComponent(principalName)}`),
  });

  if (q.isLoading) {
    return (
      <Page eyebrow="Principal Profile" title={principalName} description="">
        <Loading />
      </Page>
    );
  }

  if (q.error || !q.data) {
    return (
      <Page eyebrow="Principal Profile" title={principalName} description="">
        <ErrorState message={q.error?.message || "Principal not found"} />
      </Page>
    );
  }

  const p = q.data;
  const targets = p.targets || [];
  const operations = p.operations || [];
  const callers = p.callers || [];
  const hourlyProfile = p.hourly_profile || [];
  const totalRequests = targets.reduce((acc, t) => acc + (t.requests || 0), 0);
  const avgErrorRate = targets.length
    ? targets.reduce((acc, t) => acc + (t.error_rate || 0), 0) / targets.length
    : 0;

  return (
    <Page
      eyebrow="Principal Behavioral Profile"
      title={`Actor: ${principalName}`}
      description="Aggregated behavioral patterns across target services, operations, and hourly activity cycles."
      actions={
        <button className="btn" onClick={() => nav(-1)}>
          <ArrowLeft size={13} />
          Back
        </button>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Observed Requests" value={String(n(totalRequests))} detail="in analytical window" />
        <MetricCard
          label="Target Services"
          value={String(targets.length)}
          detail="invoked downstream"
          tone={targets.length > 5 ? "normal" : "good"}
        />
        <MetricCard
          label="Distinct Operations"
          value={String(operations.length)}
          detail="executed endpoints"
        />
        <MetricCard
          label="Avg Failure Rate"
          value={pct(avgErrorRate)}
          detail="across targets"
          tone={avgErrorRate > 0.05 ? "bad" : "good"}
        />
      </div>

      {/* Hourly distribution chart */}
      {hourlyProfile.length > 0 && (
        <Panel
          title="Hourly Activity Distribution"
          subtitle="Requests by hour of day (00:00 - 23:00 UTC) to identify unexpected off-hours activity."
        >
          <div className="h-44 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={hourlyProfile} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis
                  dataKey="hour_of_day"
                  stroke="#484f58"
                  fontSize={10}
                  tickFormatter={(h) => `${String(h).padStart(2, "0")}:00`}
                />
                <YAxis stroke="#484f58" fontSize={10} />
                <Tooltip {...chartTooltip} />
                <Bar dataKey="requests" name="Requests" fill="#6366f1" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      )}

      {/* Target Services & Operations Grids */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel
          title="Target Services"
          subtitle="Services called by this principal ordered by volume."
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">
                  <th className="pb-2">Service</th>
                  <th className="pb-2 text-right">Requests</th>
                  <th className="pb-2 text-right">Error Rate</th>
                  <th className="pb-2 text-right">p95 Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(255,255,255,0.04)]">
                {targets.map((t) => (
                  <tr
                    key={t.target_service}
                    onClick={() => nav(`/services/${encodeURIComponent(t.target_service)}?${queryString(filters)}`)}
                    className="cursor-pointer hover:bg-white/[0.03]"
                  >
                    <td className="py-2.5 font-mono text-indigo-300 hover:underline">{t.target_service}</td>
                    <td className="py-2.5 text-right font-mono text-[#c9d1d9]">{n(t.requests)}</td>
                    <td className="py-2.5 text-right font-mono">
                      <span className={t.error_rate > 0.05 ? "text-rose-400" : "text-emerald-400"}>
                        {pct(t.error_rate)}
                      </span>
                    </td>
                    <td className="py-2.5 text-right font-mono text-[#8b949e]">{Number(t.p95_latency || 0).toFixed(1)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel
          title="Operations Invoked"
          subtitle="Specific endpoints accessed by this principal."
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">
                  <th className="pb-2">Operation</th>
                  <th className="pb-2 text-right">Requests</th>
                  <th className="pb-2 text-right">Error Rate</th>
                  <th className="pb-2 text-right">p95 Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(255,255,255,0.04)]">
                {operations.map((o) => (
                  <tr key={o.operation} className="hover:bg-white/[0.03]">
                    <td className="py-2.5 font-mono text-[#f0f3f6]">{o.operation}</td>
                    <td className="py-2.5 text-right font-mono text-[#c9d1d9]">{n(o.requests)}</td>
                    <td className="py-2.5 text-right font-mono">
                      <span className={o.error_rate > 0.05 ? "text-rose-400" : "text-emerald-400"}>
                        {pct(o.error_rate)}
                      </span>
                    </td>
                    <td className="py-2.5 text-right font-mono text-[#8b949e]">{Number(o.p95_latency || 0).toFixed(1)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* Originating Caller Services */}
      {callers && callers.length > 0 && (
        <Panel
          title="Originating Caller Services"
          subtitle="Entrypoint services from which this principal initiated requests."
        >
          <div className="flex flex-wrap gap-2">
            {callers.map((c) => (
              <div
                key={c.caller_service}
                className="flex items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] px-3 py-2 text-xs"
              >
                <Workflow size={14} className="text-indigo-400" />
                <span className="font-mono text-[#f0f3f6]">{c.caller_service || "external-client"}</span>
                <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-[#8b949e]">
                  {n(c.requests)} reqs
                </span>
              </div>
            ))}
          </div>
        </Panel>
      )}
    </Page>
  );
}

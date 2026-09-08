import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Search,
  Activity,
  Layers,
  Clock,
  ExternalLink,
  ChevronRight,
  Filter,
  CheckCircle2,
  AlertTriangle,
  FileJson,
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
} from "../components";
import { useFilters } from "../App";

export type TraceSummaryItem = {
  id: number;
  trace_id: string;
  span_id: string;
  parent_span_id?: string;
  service_name: string;
  caller_service?: string;
  target_service?: string;
  principal_name?: string;
  operation: string;
  http_method?: string;
  http_status?: number;
  outcome?: string;
  duration_ms: number;
  duration_us?: number;
  timestamp: number;
  timestamp_ms: number;
  attributes_json?: string;
};

export function TracesPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();

  const [traceIdFilter, setTraceIdFilter] = useState(params.get("trace_id") || "");
  const [serviceFilter, setServiceFilter] = useState(params.get("service") || "");
  const [principalFilter, setPrincipalFilter] = useState(params.get("principal") || "");
  const [statusFilter, setStatusFilter] = useState(params.get("status") || "");

  const queryParams = new URLSearchParams();
  if (traceIdFilter) queryParams.set("trace_id", traceIdFilter);
  if (serviceFilter) queryParams.set("service", serviceFilter);
  if (principalFilter) queryParams.set("principal", principalFilter);
  if (statusFilter) queryParams.set("status", statusFilter);
  queryParams.set("limit", "50");

  const q = useQuery({
    queryKey: ["traces", queryParams.toString()],
    queryFn: () => api<{ items: TraceSummaryItem[]; count: number }>(`/api/v1/traces?${queryParams.toString()}`),
  });

  return (
    <Page
      eyebrow="Transaction Analytics"
      title="Distributed Traces & Spans"
      description="Inspect multi-hop transaction waterfalls across services, operations, and authenticated principals."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2 text-[#8b949e]" size={13} />
            <input
              type="text"
              placeholder="Filter by Trace ID..."
              value={traceIdFilter}
              onChange={(e) => setTraceIdFilter(e.target.value)}
              className="h-8 w-48 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] pl-8 pr-3 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] focus:border-indigo-500/50 focus:outline-none"
            />
          </div>
          <div className="relative">
            <input
              type="text"
              placeholder="Service..."
              value={serviceFilter}
              onChange={(e) => setServiceFilter(e.target.value)}
              className="h-8 w-32 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] px-3 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] focus:border-indigo-500/50 focus:outline-none"
            />
          </div>
          <div className="relative">
            <input
              type="text"
              placeholder="Principal..."
              value={principalFilter}
              onChange={(e) => setPrincipalFilter(e.target.value)}
              className="h-8 w-28 rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.02] px-3 text-xs text-[#f0f3f6] placeholder:text-[#6e7681] focus:border-indigo-500/50 focus:outline-none"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="btn h-8 bg-[rgba(255,255,255,0.02)] text-xs cursor-pointer"
          >
            <option value="" className="bg-[#12151a]">All Statuses</option>
            <option value="error" className="bg-[#12151a]">Errors Only (5xx/Failure)</option>
            <option value="ok" className="bg-[#12151a]">Success (2xx)</option>
          </select>
        </div>
      }
    >
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : (
        <Panel
          title={`${q.data?.items.length || 0} Traces Found`}
          subtitle="Showing latest trace executions. Select a row to explore full parent-child waterfall timing."
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full min-w-[1000px] text-left">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01] text-[11px] font-semibold uppercase tracking-wider text-[#8b949e]">
                  <th className="px-4 py-3">Trace ID</th>
                  <th className="px-4 py-3">Timestamp</th>
                  <th className="px-4 py-3">Service & Operation</th>
                  <th className="px-4 py-3">Principal</th>
                  <th className="px-4 py-3 text-right">Duration</th>
                  <th className="px-4 py-3 text-right">Status</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(255,255,255,0.04)] text-xs">
                {q.data?.items.map((t) => {
                  const isError = (t.http_status && t.http_status >= 400) || t.outcome === "failure";
                  return (
                    <tr
                      key={`${t.trace_id}-${t.span_id || t.id}`}
                      onClick={() => nav(`/traces/${t.trace_id}`)}
                      className="cursor-pointer transition hover:bg-white/[0.03]"
                    >
                      <td className="px-4 py-3 font-mono text-indigo-400">
                        <span className="hover:underline">{t.trace_id.slice(0, 16)}...</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-[#8b949e]">
                        {new Date(t.timestamp_ms).toLocaleTimeString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-emerald-400 font-medium">{t.service_name || t.target_service}</span>
                          <span className="text-[#8b949e]">/</span>
                          <span className="font-mono text-[#f0f3f6]">{t.operation}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-[#8b949e]">
                        {t.principal_name && t.principal_name !== "unknown" ? (
                          <span className="text-indigo-300 font-medium">{t.principal_name}</span>
                        ) : (
                          <span className="text-[#6e7681]">unknown</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-[#c9d1d9]">
                        {t.duration_ms ? `${t.duration_ms.toFixed(1)} ms` : "0.0 ms"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {isError ? (
                          <span className="inline-flex items-center gap-1 rounded bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-400 border border-rose-500/20">
                            {t.http_status || "500"} ERROR
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-400 border border-emerald-500/20">
                            {t.http_status || "200"} OK
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="inline-flex items-center gap-1 text-[11px] text-indigo-400 hover:text-indigo-300">
                          Waterfall <ChevronRight size={12} />
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {(!q.data?.items || q.data.items.length === 0) && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-xs text-[#8b949e]">
                      No traces match current filters.
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

type TraceDetailData = {
  trace_id: string;
  spans: TraceSummaryItem[];
  waterfall: TraceSummaryItem[];
  count: number;
};

export function TraceDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [selectedSpan, setSelectedSpan] = useState<TraceSummaryItem | null>(null);

  const q = useQuery({
    queryKey: ["trace", id],
    queryFn: () => api<TraceDetailData>(`/api/v1/traces/${id}`),
  });

  if (q.isLoading) {
    return (
      <Page eyebrow="Trace Waterfall" title={`Loading ${id}...`} description="">
        <Loading />
      </Page>
    );
  }

  if (q.error || !q.data) {
    return (
      <Page eyebrow="Trace Waterfall" title="Trace Not Found" description="">
        <ErrorState message={q.error?.message || "Trace identifier not found in analytics store."} />
      </Page>
    );
  }

  const spans = q.data.spans || [];
  const minTs = spans.reduce((min, s) => Math.min(min, s.timestamp_ms), Infinity);
  const maxEndTs = spans.reduce((max, s) => Math.max(max, s.timestamp_ms + (s.duration_ms || 0)), -Infinity);
  const totalDuration = Math.max(1, maxEndTs - minTs);

  const uniqueServices = Array.from(new Set(spans.map((s) => s.service_name || s.target_service).filter(Boolean)));
  const hasError = spans.some((s) => (s.http_status && s.http_status >= 400) || s.outcome === "failure");

  return (
    <Page
      eyebrow="Distributed Trace Waterfall"
      title={`Trace: ${id}`}
      description={`Multi-tier distributed execution across ${uniqueServices.length} services with ${spans.length} spans.`}
      actions={
        <div className="flex items-center gap-2">
          <button className="btn" onClick={() => nav(-1)}>
            <ArrowLeft size={13} />
            Back
          </button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Total Spans" value={String(spans.length)} detail="in trace hierarchy" />
        <MetricCard label="Trace Latency" value={`${totalDuration.toFixed(1)} ms`} detail="end-to-end duration" />
        <MetricCard label="Services Involved" value={String(uniqueServices.length)} detail={uniqueServices.slice(0, 3).join(", ")} />
        <MetricCard
          label="Trace Status"
          value={hasError ? "Errors Detected" : "Normal"}
          detail={hasError ? "One or more failed spans" : "All operations succeeded"}
          tone={hasError ? "bad" : "good"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Waterfall diagram */}
        <div className={selectedSpan ? "lg:col-span-2" : "lg:col-span-3"}>
          <Panel
            title="Execution Timeline Waterfall"
            subtitle="Click a span row to inspect runtime attributes, thread info, and request metadata."
          >
            <div className="space-y-1 overflow-auto scrollbar py-2">
              {spans.map((span) => {
                const offsetMs = Math.max(0, span.timestamp_ms - minTs);
                const startPct = (offsetMs / totalDuration) * 100;
                const widthPct = Math.max(1.5, ((span.duration_ms || 1) / totalDuration) * 100);
                const isErr = (span.http_status && span.http_status >= 400) || span.outcome === "failure";
                const isSelected = selectedSpan?.span_id === span.span_id;

                return (
                  <div
                    key={span.span_id || span.id}
                    onClick={() => setSelectedSpan(span)}
                    className={`group flex cursor-pointer items-center gap-3 rounded-lg border p-2 transition ${
                      isSelected
                        ? "border-indigo-500 bg-indigo-500/10"
                        : "border-[rgba(255,255,255,0.04)] bg-white/[0.01] hover:border-[rgba(255,255,255,0.1)] hover:bg-white/[0.03]"
                    }`}
                  >
                    {/* Left: Service & Operation */}
                    <div className="w-56 shrink-0 truncate">
                      <div className="flex items-center gap-1.5 truncate">
                        <span className={`h-2 w-2 rounded-full ${isErr ? "bg-rose-400" : "bg-emerald-400"}`} />
                        <span className="font-mono text-xs font-semibold text-[#f0f3f6] truncate">
                          {span.service_name || span.target_service}
                        </span>
                      </div>
                      <div className="pl-3.5 truncate font-mono text-[10px] text-[#8b949e]">
                        {span.operation}
                      </div>
                    </div>

                    {/* Middle: Timeline bar */}
                    <div className="relative h-6 flex-1 rounded bg-white/[0.02]">
                      <div
                        style={{
                          left: `${startPct}%`,
                          width: `${Math.min(100 - startPct, widthPct)}%`,
                        }}
                        className={`absolute top-1 h-4 rounded text-[10px] font-mono px-1 flex items-center shadow-sm ${
                          isErr
                            ? "bg-rose-500/80 text-white"
                            : "bg-indigo-600/80 text-white"
                        }`}
                      >
                        <span className="truncate">{span.duration_ms ? `${span.duration_ms.toFixed(1)}ms` : "0ms"}</span>
                      </div>
                    </div>

                    {/* Right: Status badge */}
                    <div className="w-20 shrink-0 text-right">
                      <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                        isErr ? "bg-rose-500/20 text-rose-300" : "bg-emerald-500/20 text-emerald-300"
                      }`}>
                        {span.http_status || (span.outcome === "failure" ? "500" : "200")}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>

        {/* Selected Span Details Drawer */}
        {selectedSpan && (
          <div className="lg:col-span-1">
            <Panel
              title="Span Metadata"
              subtitle={`Span ID: ${selectedSpan.span_id || "N/A"}`}
              action={
                <button
                  onClick={() => setSelectedSpan(null)}
                  className="text-xs text-[#8b949e] hover:text-white"
                >
                  Close
                </button>
              }
            >
              <div className="space-y-3 text-xs">
                <div>
                  <span className="text-[10px] font-semibold uppercase text-[#8b949e]">Service</span>
                  <div className="font-mono text-[#f0f3f6] font-medium">{selectedSpan.service_name || selectedSpan.target_service}</div>
                </div>

                <div>
                  <span className="text-[10px] font-semibold uppercase text-[#8b949e]">Operation</span>
                  <div className="font-mono text-[#f0f3f6] break-all">{selectedSpan.operation}</div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-[#8b949e]">Duration</span>
                    <div className="font-mono text-[#c9d1d9]">{selectedSpan.duration_ms?.toFixed(2)} ms</div>
                  </div>
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-[#8b949e]">HTTP Status</span>
                    <div className="font-mono text-[#c9d1d9]">{selectedSpan.http_status || "N/A"}</div>
                  </div>
                </div>

                <div>
                  <span className="text-[10px] font-semibold uppercase text-[#8b949e]">Principal Actor</span>
                  <div className="font-mono text-indigo-300">{selectedSpan.principal_name || "unknown"}</div>
                </div>

                {selectedSpan.caller_service && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-[#8b949e]">Caller Service</span>
                    <div className="font-mono text-[#8b949e]">{selectedSpan.caller_service}</div>
                  </div>
                )}

                {selectedSpan.attributes_json && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-[#8b949e] mb-1 flex items-center gap-1">
                      <FileJson size={12} /> Attributes JSON
                    </span>
                    <pre className="max-h-56 overflow-auto rounded bg-black/40 p-2 font-mono text-[10px] text-[#c9d1d9] border border-[rgba(255,255,255,0.06)]">
                      {JSON.stringify(JSON.parse(selectedSpan.attributes_json), null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </Panel>
          </div>
        )}
      </div>
    </Page>
  );
}

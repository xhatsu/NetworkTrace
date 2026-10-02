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
import { useI18n } from "../i18n";
import { EntityLink } from "../components/EntityLink";

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
  const { t } = useI18n();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();

  const [traceIdFilter, setTraceIdFilter] = useState(params.get("trace_id") || "");
  const [serviceFilter, setServiceFilter] = useState(params.get("service") || "");
  const [principalFilter, setPrincipalFilter] = useState(params.get("principal") || "");
  const [statusFilter, setStatusFilter] = useState(params.get("status") || "");

  const queryParams = new URLSearchParams(queryString(filters));
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
      eyebrow={t("Transaction Analytics")}
      title={t("Distributed Traces & Spans")}
      description={t("Inspect multi-hop transaction waterfalls across services, operations, and authenticated principals.")}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2 text-muted" size={13} />
            <input
              type="text"
              placeholder={t("Filter by Trace ID...")}
              value={traceIdFilter}
              onChange={(e) => setTraceIdFilter(e.target.value)}
              className="h-8 w-48 rounded-lg border border-line bg-surface-2 pl-8 pr-3 text-xs text-ink placeholder:text-muted focus:border-accent/50 focus:outline-none"
            />
          </div>
          <div className="relative">
            <input
              type="text"
              placeholder={`${t("Service")}...`}
              value={serviceFilter}
              onChange={(e) => setServiceFilter(e.target.value)}
              className="h-8 w-32 rounded-lg border border-line bg-surface-2 px-3 text-xs text-ink placeholder:text-muted focus:border-accent/50 focus:outline-none"
            />
          </div>
          <div className="relative">
            <input
              type="text"
              placeholder={`${t("Principal")}...`}
              value={principalFilter}
              onChange={(e) => setPrincipalFilter(e.target.value)}
              className="h-8 w-28 rounded-lg border border-line bg-surface-2 px-3 text-xs text-ink placeholder:text-muted focus:border-accent/50 focus:outline-none"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="btn h-8 bg-surface-2 text-xs cursor-pointer"
          >
            <option value="" className="bg-surface">{t("All Statuses")}</option>
            <option value="error" className="bg-surface">{t("Errors Only (5xx/Failure)")}</option>
            <option value="ok" className="bg-surface">{t("Success (2xx)")}</option>
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
          title={`${q.data?.items.length || 0} ${t("Traces Found")}`}
          subtitle={t("Showing latest trace executions. Select a row to explore full parent-child waterfall timing.")}
        >
          <div className="overflow-auto scrollbar">
            <table className="w-full min-w-[1000px] text-left">
              <thead>
                <tr className="border-b border-[rgba(255,255,255,0.06)] bg-white/[0.01] text-[11px] font-semibold uppercase tracking-wider text-muted">
                  <th className="px-4 py-3">{t("Trace ID")}</th>
                  <th className="px-4 py-3">{t("Timestamp")}</th>
                  <th className="px-4 py-3">{t("Service & Operation")}</th>
                  <th className="px-4 py-3">{t("Principal")}</th>
                  <th className="px-4 py-3 text-right">{t("Duration")}</th>
                  <th className="px-4 py-3 text-right">{t("Status")}</th>
                  <th className="px-4 py-3 text-right">{t("Action")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgba(255,255,255,0.04)] text-xs">
                {q.data?.items.map((item) => {
                  const isError = (item.http_status && item.http_status >= 400) || item.outcome === "failure";
                  return (
                    <tr
                      key={`${item.trace_id}-${item.span_id || item.id}`}
                      onClick={() => nav(`/traces/${item.trace_id}`)}
                      className="cursor-pointer transition hover:bg-white/[0.03]"
                    >
                      <td className="px-4 py-3 font-mono text-entity-user">
                        <span className="hover:underline">{item.trace_id.slice(0, 16)}...</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-muted">
                        {new Date(item.timestamp_ms).toLocaleTimeString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <EntityLink entity={{ kind: "service", name: item.target_service || item.service_name }} className="font-mono font-medium text-good hover:underline">{item.service_name || item.target_service}</EntityLink>
                          <span className="text-muted">/</span>
                          <EntityLink entity={{ kind: "api", service: item.target_service || item.service_name, operation: item.operation }} className="font-mono text-ink hover:underline">{item.operation}</EntityLink>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-muted">
                        {item.principal_name && item.principal_name !== "unknown" ? (
                          <EntityLink entity={{ kind: "user", principal: item.principal_name }} className="font-medium text-entity-user hover:underline">{item.principal_name}</EntityLink>
                        ) : (
                          <span className="text-faint">unknown</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-ink">
                        {item.duration_ms ? `${item.duration_ms.toFixed(1)} ms` : "0.0 ms"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {item.http_status ? (
                          isError ? (
                            <span className="inline-flex items-center gap-1 rounded bg-bad/10 px-2 py-0.5 text-[11px] font-semibold text-bad border border-bad/20">
                              {item.http_status} ERROR
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded bg-good/10 px-2 py-0.5 text-[11px] font-semibold text-good border border-good/20">
                              {item.http_status} OK
                            </span>
                          )
                        ) : isError ? (
                          <span className="inline-flex items-center gap-1 rounded bg-bad/10 px-2 py-0.5 text-[11px] font-semibold text-bad border border-bad/20">
                            ERROR
                          </span>
                        ) : item.outcome === "success" ? (
                          <span className="inline-flex items-center gap-1 rounded bg-good/10 px-2 py-0.5 text-[11px] font-semibold text-good border border-good/20">
                            200 OK
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-surface-2/10 px-2 py-0.5 text-[11px] font-semibold text-muted border border-line/20">
                            N/A
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="inline-flex items-center gap-1 text-[11px] text-entity-user hover:text-accent">
                          {t("Waterfall")} <ChevronRight size={12} />
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {(!q.data?.items || q.data.items.length === 0) && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-xs text-muted">
                      {t("No traces match current filters.")}
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

function formatAttributes(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return `Invalid attributes JSON\n${value}`;
  }
}

export function TraceDetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const nav = useNavigate();
  const [selectedSpan, setSelectedSpan] = useState<TraceSummaryItem | null>(null);

  const q = useQuery({
    queryKey: ["trace", id],
    queryFn: () => api<TraceDetailData>(`/api/v1/traces/${id}`),
  });

  if (q.isLoading) {
    return (
      <Page eyebrow={t("Trace Waterfall")} title={`${t("Loading...")} ${id}`} description="">
        <Loading />
      </Page>
    );
  }

  if (q.error || !q.data) {
    return (
      <Page eyebrow={t("Trace Waterfall")} title={t("Trace Not Found")} description="">
        <ErrorState message={q.error?.message || t("Trace identifier not found in analytics store.")} />
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
      eyebrow={t("Distributed Trace Waterfall")}
      title={`${t("Trace: ")}${id}`}
      description={`${t("Multi-tier distributed execution across")} ${uniqueServices.length} ${t("services with")} ${spans.length} ${t("spans.")}`}
      actions={
        <div className="flex items-center gap-2">
          <button className="btn" onClick={() => nav(-1)}>
            <ArrowLeft size={13} />
            {t("Back")}
          </button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label={t("Total Spans")} value={String(spans.length)} detail={t("in trace hierarchy")} />
        <MetricCard label={t("Trace Latency")} value={`${totalDuration.toFixed(1)} ms`} detail={t("end-to-end duration")} />
        <MetricCard label={t("Services Involved")} value={String(uniqueServices.length)} detail={uniqueServices.slice(0, 3).join(", ")} />
        <MetricCard
          label={t("Trace Status")}
          value={hasError ? t("Errors Detected") : t("Normal")}
          detail={hasError ? t("One or more failed spans") : t("All operations succeeded")}
          tone={hasError ? "bad" : "good"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Waterfall diagram */}
        <div className={selectedSpan ? "lg:col-span-1" : "lg:col-span-2"}>
          <Panel
            title={t("Execution Timeline Waterfall")}
            subtitle={t("Click a span row to inspect runtime attributes, thread info, and request metadata.")}
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
                        ? "border-line bg-accent/10"
                        : "border-[rgba(255,255,255,0.04)] bg-white/[0.01] hover:border-[rgba(255,255,255,0.1)] hover:bg-white/[0.03]"
                    }`}
                  >
                    {/* Left: Service & Operation */}
                    <div className="w-56 shrink-0 truncate">
                      <div className="flex items-center gap-1.5 truncate">
                        <span className={`h-2 w-2 rounded-full ${isErr ? "bg-bad" : "bg-good"}`} />
                        <EntityLink entity={{ kind: "service", name: span.target_service || span.service_name }} className="truncate font-mono text-xs font-semibold text-ink hover:underline">
                          {span.service_name || span.target_service}
                        </EntityLink>
                      </div>
                      <div className="pl-3.5 truncate font-mono text-[10px] text-muted">
                        {span.target_service || span.service_name
                          ? <EntityLink entity={{ kind: "api", service: span.target_service || span.service_name, operation: span.operation }} className="hover:underline">{span.operation}</EntityLink>
                          : span.operation}
                      </div>
                    </div>

                    {/* Middle: Timeline bar */}
                    <div className="relative h-6 flex-1 rounded bg-surface-2">
                      <div
                        style={{
                          left: `${startPct}%`,
                          width: `${Math.min(100 - startPct, widthPct)}%`,
                        }}
                        className={`absolute top-1 h-4 rounded text-[10px] font-mono px-1 flex items-center shadow-sm ${
                          isErr
                            ? "bg-bad/80 text-white"
                            : "bg-accent/80 text-white"
                        }`}
                      >
                        <span className="truncate">{span.duration_ms ? `${span.duration_ms.toFixed(1)}ms` : "0ms"}</span>
                      </div>
                    </div>

                    {/* Right: Status badge */}
                    <div className="w-20 shrink-0 text-right">
                      <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
                        isErr
                          ? "bg-bad/20 text-bad"
                          : (span.http_status || span.outcome === "success")
                          ? "bg-good/20 text-good"
                          : "bg-surface-2/20 text-muted"
                      }`}>
                        {span.http_status || (span.outcome === "failure" ? "500" : span.outcome === "success" ? "200" : "N/A")}
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
              title={t("Span Metadata")}
              subtitle={`Span ID: ${selectedSpan.span_id || "N/A"}`}
              action={
                <button
                  onClick={() => setSelectedSpan(null)}
                  className="text-xs text-muted hover:text-ink"
                >
                  {t("Close")}
                </button>
              }
            >
              <div className="space-y-3 text-xs">
                <div>
                  <span className="text-[10px] font-semibold uppercase text-muted">{t("Service")}</span>
                  <EntityLink entity={{ kind: "service", name: selectedSpan.target_service || selectedSpan.service_name }} className="font-mono font-medium text-ink hover:underline">{selectedSpan.service_name || selectedSpan.target_service}</EntityLink>
                </div>

                <div>
                  <span className="text-[10px] font-semibold uppercase text-muted">{t("Operation")}</span>
                  {(selectedSpan.target_service || selectedSpan.service_name)
                    ? <EntityLink entity={{ kind: "api", service: selectedSpan.target_service || selectedSpan.service_name, operation: selectedSpan.operation }} className="break-all font-mono text-ink hover:underline">{selectedSpan.operation}</EntityLink>
                    : <div className="break-all font-mono text-ink">{selectedSpan.operation}</div>}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-muted">{t("Duration")}</span>
                    <div className="font-mono text-ink">{selectedSpan.duration_ms?.toFixed(2)} ms</div>
                  </div>
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-muted">{t("HTTP Status")}</span>
                    <div className="font-mono text-ink">{selectedSpan.http_status || "N/A"}</div>
                  </div>
                </div>

                <div>
                  <span className="text-[10px] font-semibold uppercase text-muted">{t("Principal Actor")}</span>
                  {selectedSpan.principal_name ? <EntityLink entity={{ kind: "user", principal: selectedSpan.principal_name }} className="font-mono text-entity-user hover:underline">{selectedSpan.principal_name}</EntityLink> : <div className="font-mono text-entity-user">unknown</div>}
                </div>

                {selectedSpan.caller_service && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-muted">{t("Caller Service")}</span>
                    <EntityLink entity={{ kind: "service", name: selectedSpan.caller_service }} className="font-mono text-muted hover:underline">{selectedSpan.caller_service}</EntityLink>
                  </div>
                )}

                {selectedSpan.attributes_json && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase text-muted mb-1 flex items-center gap-1">
                      <FileJson size={12} /> {t("Attributes JSON")}
                    </span>
                    <pre className="max-h-56 overflow-auto rounded bg-black/40 p-2 font-mono text-[10px] text-ink border border-[rgba(255,255,255,0.06)]">
                      {formatAttributes(selectedSpan.attributes_json)}
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

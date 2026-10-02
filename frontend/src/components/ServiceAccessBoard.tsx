import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, Fingerprint, Globe2, KeyRound, ListTree, Server, X } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, n, Panel, pct } from "../components";
import { useI18n } from "../i18n";
import type { Filters } from "../types";
import { AccessExplorer, type ExplorerFilters } from "./AccessExplorer";
import { EntityLink } from "./EntityLink";

type Relationship = {
  principal?: string;
  source_ip: string;
  service: string;
  api: string;
  caller_service?: string;
  request_count?: number;
  error_count?: number;
  error_rate?: number;
  tps?: number;
  p95_latency_ms?: number;
  role_label?: string;
  source_ip_role?: string;
  is_load_balancer?: boolean;
};

type RelationshipPage = { items: Relationship[]; next_cursor?: string | null };

type AccountItem = { username: string; requests: number };

type OperationItem = {
  name: string;
  requests?: number;
  tps?: number;
  error_rate?: number;
  failure_rate?: number;
  p95_ms?: number;
};

function summarize(rows: Relationship[]) {
  const requests = rows.reduce((sum, row) => sum + (row.request_count || 0), 0);
  const errors = rows.reduce((sum, row) => sum + (row.error_count ?? (row.error_rate || 0) * (row.request_count || 0)), 0);
  return {
    requests,
    errorRate: requests ? errors / requests : 0,
    tps: rows.reduce((sum, row) => sum + (row.tps || 0), 0),
    p95: Math.max(0, ...rows.map(row => row.p95_latency_ms || 0)),
  };
}

function group(rows: Relationship[], key: "source_ip" | "api" | "caller_service") {
  const groups = new Map<string, Relationship[]>();
  rows.forEach(row => {
    const name = row[key] || "";
    const list = groups.get(name) || [];
    list.push(row);
    groups.set(name, list);
  });
  return [...groups].map(([name, items]) => ({
    name,
    items,
    ...summarize(items),
  })).sort((a, b) => b.requests - a.requests || a.name.localeCompare(b.name));
}

export function ServiceAccessBoard({
  service,
  accounts = [],
  operations: propOperations = [],
  filters,
}: {
  service: string;
  accounts?: AccountItem[];
  operations?: OperationItem[];
  filters: Filters;
}) {
  const { t } = useI18n();
  const [selectedPrincipal, setSelectedPrincipal] = useState<string | null>(null);
  const [selectedIp, setSelectedIp] = useState<string | null>(null);
  const [selectedOperation, setSelectedOperation] = useState<string | null>(null);
  const [selectedCaller, setSelectedCaller] = useState<string | null>(null);


  const scoped = { ...filters, service, account: undefined, operation: undefined };

  const relationships = useInfiniteQuery({
    queryKey: ["service-access-all", service, filters.start, filters.end],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<RelationshipPage>(
        `/api/v1/topology/services/${encodeURIComponent(service)}/ips?${queryString(scoped, {
          page_size: "500",
          cursor: pageParam || undefined,
        })}`
      ),
    getNextPageParam: (page) => page.next_cursor || undefined,
    enabled: !!service,
  });

  const rows = useMemo(() => {
    return (relationships.data?.pages.flatMap((page) => page.items) || []).filter(
      (row) => row.service === service
    );
  }, [relationships.data, service]);

  // --- Summary & Callers ---
  const selectedRows = useMemo(() => {
    return rows.filter((r) => {
      const pMatch = !selectedPrincipal || r.principal === selectedPrincipal;
      const ipMatch = !selectedIp || r.source_ip === selectedIp;
      const opMatch = !selectedOperation || r.api === selectedOperation;
      const callerMatch = !selectedCaller || r.caller_service === selectedCaller;
      return pMatch && ipMatch && opMatch && callerMatch;
    });
  }, [rows, selectedPrincipal, selectedIp, selectedOperation, selectedCaller]);

  const callers = useMemo(() => group(selectedRows, "caller_service"), [selectedRows]);
  const metrics = useMemo(() => summarize(selectedRows), [selectedRows]);
  const hasSelection = Boolean(selectedPrincipal || selectedIp || selectedOperation || selectedCaller);


  // The learned Sankey and the observed lists share one cross-filter selection.
  const apiPrefix = `${service} → `;
  const flowFilters: ExplorerFilters & { ip?: string } = {
    credential: selectedPrincipal || undefined,
    ip: selectedIp || undefined,
    api: selectedOperation ? apiPrefix + selectedOperation : undefined,
    caller: selectedCaller || undefined,
  };
  const applyFlowFilters = (next: ExplorerFilters & { ip?: string }) => {
    setSelectedPrincipal(next.credential || null);
    setSelectedIp(next.ip || null);
    setSelectedOperation(next.api ? next.api.replace(apiPrefix, "") : null);
    setSelectedCaller(next.caller || null);
  };

  return (
    <Panel
      title={`${t("Access for", "Quyền truy cập của")} ${service}`}
      subtitle={t(
        "Unusual access first, then Caller Service · User · API lists; select any row to see its direct relationships",
        "Truy cập bất thường trước, sau đó là danh sách Caller Service · User · API; chọn một dòng để xem quan hệ trực tiếp"
      )}
    >
      <div data-testid="service-access-flow">
        <AccessExplorer service={service} filters={flowFilters} onFilters={applyFlowFilters} />
      </div>

      {/* Selected Drilldown Summary */}
      {hasSelection ? (
        <div className="border-t border-line p-3" aria-live="polite">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="flex items-center gap-1 font-mono text-entity-service">
              <Server size={14} aria-hidden="true" />
              <span>{service}</span>
            </span>

            {selectedOperation && (
              <>
                <ArrowRight size={13} className="text-muted" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 rounded-ctl bg-surface-2 px-2 py-0.5 font-mono text-entity-api">
                  <Fingerprint size={12} aria-hidden="true" />
                  <EntityLink
                    entity={{ kind: "api", service, operation: selectedOperation }}
                    search={`?${queryString(scoped)}`}
                    className="break-all hover:underline"
                  >
                    {selectedOperation}
                  </EntityLink>
                  <button
                    onClick={() => setSelectedOperation(null)}
                    className="ml-1 text-entity-api hover:text-ink"
                    title={t("Clear API filter")}
                  >
                    <X size={11} />
                  </button>
                </span>
              </>
            )}

            {selectedPrincipal && (
              <>
                <ArrowRight size={13} className="text-muted" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 rounded-ctl bg-surface-2 px-2 py-0.5 font-mono text-entity-user">
                  <KeyRound size={12} aria-hidden="true" />
                  <span>{selectedPrincipal}</span>
                  <button
                    onClick={() => setSelectedPrincipal(null)}
                    className="ml-1 text-entity-user hover:text-ink"
                    title={t("Clear credential filter")}
                  >
                    <X size={11} />
                  </button>
                </span>
              </>
            )}

            {selectedIp && (
              <>
                <ArrowRight size={13} className="text-muted" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 rounded-ctl bg-surface-2 px-2 py-0.5 font-mono text-entity-ip">
                  <Globe2 size={12} aria-hidden="true" />
                  <span>{selectedIp}</span>
                  <button
                    onClick={() => setSelectedIp(null)}
                    className="ml-1 text-muted hover:text-ink"
                    title={t("Clear IP filter")}
                  >
                    <X size={11} />
                  </button>
                </span>
              </>
            )}
          </div>

          <p className="my-2 text-xs text-muted">
            {t(
              "Observed credential and IP are supporting evidence. Open a Trace to confirm the caller chain.",
              "Credential và IP quan sát được là bằng chứng hỗ trợ. Mở Trace để xác nhận chuỗi caller."
            )}
          </p>

          <div className="mb-3 flex flex-wrap gap-4 font-mono text-xs text-muted">
            <span>{n(metrics.requests, 0)} {t("requests")}</span>
            <span>{n(metrics.tps, 2)} TPS</span>
            <span>{pct(metrics.errorRate)} {t("error")}</span>
            <span>{n(metrics.p95, 1)} ms {t("Max bucket P95", "P95 bucket lớn nhất")}</span>
          </div>

          {callers.length > 0 && (
            <div className="divide-y divide-line">
              {callers.map((caller) => (
                <div key={caller.name} className="flex flex-wrap justify-between gap-2 py-2 text-xs">
                  <span className="text-entity-service">
                    {t("Caller Service")}:{" "}
                    {caller.name ? (
                      <EntityLink
                        entity={{ kind: "service", name: caller.name }}
                        search={`?${queryString({ ...scoped, service: undefined })}`}
                        className="break-all hover:underline"
                      >
                        {caller.name}
                      </EntityLink>
                    ) : (
                      t("Caller unavailable", "Caller không khả dụng")
                    )}
                  </span>
                  <span className="font-mono text-muted">{n(caller.requests, 0)} {t("requests")}</span>
                </div>
              ))}
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Link
              className="btn inline-flex items-center gap-1"
              to={`/traces?${queryString(scoped, {
                account: selectedPrincipal || undefined,
                principal: selectedPrincipal || undefined,
                operation: selectedOperation || undefined,
              })}`}
            >
              {t("View related Traces")} <ArrowRight size={13} aria-hidden="true" />
            </Link>
            <span className="text-[11px] text-muted">
              {t(
                "Trace search scoped to selected filters",
                "Tìm Trace theo các bộ lọc đã chọn"
              )}
            </span>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

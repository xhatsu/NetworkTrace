import { useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, Fingerprint, Globe2, KeyRound, RotateCcw, Server, X } from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, n, Panel, pct } from "../components";
import { useI18n } from "../i18n";
import type { Filters } from "../types";
import { AccessBoardColumn } from "./AccessBoardColumn";
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

  const [search, setSearch] = useState("");
  const [ipSearch, setIpSearch] = useState("");
  const [apiSearch, setApiSearch] = useState("");

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

  // --- 1. Credentials calculation ---
  const baseCredentials = useMemo(() => {
    const map = new Map<string, AccountItem>();
    accounts.forEach((acc) => {
      if (acc.username && !["unknown", "-anonymous-", "anonymous"].includes(acc.username)) {
        map.set(acc.username, { username: acc.username, requests: acc.requests || 0 });
      }
    });
    rows.forEach((row) => {
      if (row.principal && !["unknown", "-anonymous-", "anonymous"].includes(row.principal)) {
        const existing = map.get(row.principal);
        if (!existing) {
          map.set(row.principal, { username: row.principal, requests: row.request_count || 0 });
        }
      }
    });
    return [...map.values()].sort((a, b) => b.requests - a.requests || a.username.localeCompare(b.username));
  }, [accounts, rows]);

  const visibleCredentials = useMemo(() => {
    if (!selectedIp && !selectedOperation) {
      return baseCredentials;
    }
    const matchingPrincipals = new Set<string>();
    const principalRequests = new Map<string, number>();

    rows.forEach((r) => {
      const ipMatch = !selectedIp || r.source_ip === selectedIp;
      const opMatch = !selectedOperation || r.api === selectedOperation;
      if (ipMatch && opMatch && r.principal && !["unknown", "-anonymous-", "anonymous"].includes(r.principal)) {
        matchingPrincipals.add(r.principal);
        principalRequests.set(r.principal, (principalRequests.get(r.principal) || 0) + (r.request_count || 0));
      }
    });

    if (rows.length > 0) {
      return baseCredentials
        .filter((c) => matchingPrincipals.has(c.username))
        .map((c) => ({
          ...c,
          requests: principalRequests.get(c.username) ?? c.requests,
        }))
        .sort((a, b) => b.requests - a.requests || a.username.localeCompare(b.username));
    }
    return baseCredentials;
  }, [baseCredentials, rows, selectedIp, selectedOperation]);

  // --- 2. IPs calculation ---
  const baseIps = useMemo(() => {
    return group(rows, "source_ip");
  }, [rows]);

  const visibleIps = useMemo(() => {
    if (!selectedPrincipal && !selectedOperation) {
      return baseIps;
    }
    const matchingRows = rows.filter((r) => {
      const principalMatch = !selectedPrincipal || r.principal === selectedPrincipal;
      const opMatch = !selectedOperation || r.api === selectedOperation;
      return principalMatch && opMatch;
    });
    return group(matchingRows, "source_ip");
  }, [baseIps, rows, selectedPrincipal, selectedOperation]);

  // --- 3. APIs calculation ---
  const baseOperations = useMemo(() => {
    const fromRows = group(rows, "api");
    const map = new Map<string, { name: string; requests: number; tps: number; errorRate: number; p95: number }>();

    propOperations.forEach((op) => {
      if (op.name) {
        map.set(op.name, {
          name: op.name,
          requests: op.requests || 0,
          tps: op.tps || 0,
          errorRate: op.failure_rate ?? op.error_rate ?? 0,
          p95: op.p95_ms || 0,
        });
      }
    });

    fromRows.forEach((item) => {
      const existing = map.get(item.name);
      if (!existing) {
        map.set(item.name, {
          name: item.name,
          requests: item.requests,
          tps: item.tps,
          errorRate: item.errorRate,
          p95: item.p95,
        });
      }
    });

    return [...map.values()].sort((a, b) => b.requests - a.requests || a.name.localeCompare(b.name));
  }, [propOperations, rows]);

  const visibleOperations = useMemo(() => {
    if (!selectedPrincipal && !selectedIp) {
      return baseOperations;
    }
    const matchingRows = rows.filter((r) => {
      const principalMatch = !selectedPrincipal || r.principal === selectedPrincipal;
      const ipMatch = !selectedIp || r.source_ip === selectedIp;
      return principalMatch && ipMatch;
    });

    if (rows.length > 0) {
      return group(matchingRows, "api");
    }
    return baseOperations;
  }, [baseOperations, rows, selectedPrincipal, selectedIp]);

  // --- Summary & Callers ---
  const selectedRows = useMemo(() => {
    return rows.filter((r) => {
      const pMatch = !selectedPrincipal || r.principal === selectedPrincipal;
      const ipMatch = !selectedIp || r.source_ip === selectedIp;
      const opMatch = !selectedOperation || r.api === selectedOperation;
      return pMatch && ipMatch && opMatch;
    });
  }, [rows, selectedPrincipal, selectedIp, selectedOperation]);

  const callers = useMemo(() => group(selectedRows, "caller_service"), [selectedRows]);
  const metrics = useMemo(() => summarize(selectedRows), [selectedRows]);
  const hasSelection = Boolean(selectedPrincipal || selectedIp || selectedOperation);

  const resetAll = () => {
    setSelectedPrincipal(null);
    setSelectedIp(null);
    setSelectedOperation(null);
  };

  const control = (active: boolean, color: string) =>
    `w-full border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#5794f2] ${
      active ? color : "border-[#2a2d30] bg-[#111217] hover:border-[#7b7d80]"
    }`;
  const empty = (text: string) => (
    <div className="px-3 py-8 text-center text-xs text-[#c2c6cc]">{text}</div>
  );

  return (
    <Panel
      title={`${t("Access for", "Quyền truy cập của")} ${service}`}
      subtitle={t(
        "Explore credentials, source IPs, and APIs for this Service (select any to filter)",
        "Khám phá credential, IP nguồn và API của Service này (chọn bất kỳ mục nào để lọc)"
      )}
      titleClassName="text-sm font-semibold uppercase tracking-[0.06em] text-[#f1f3f5]"
      subtitleClassName="text-xs text-[#c2c6cc]"
      action={
        <div className="flex items-center gap-3">
          {hasSelection && (
            <button
              onClick={resetAll}
              className="inline-flex items-center gap-1 text-xs text-[#ff9830] hover:underline"
            >
              <RotateCcw size={12} aria-hidden="true" />
              <span>{t("Reset filters", "Đặt lại bộ lọc")}</span>
            </button>
          )}
          <span className="text-xs text-[#c2c6cc]">
            {rows.length} {t("loaded relationships", "quan hệ đã tải")}
          </span>
        </div>
      }
    >
      <div
        data-testid="service-access-board"
        className="grid gap-2 p-2 md:grid-cols-[minmax(0,25fr)_minmax(0,35fr)_minmax(0,40fr)]"
      >
        {/* Column 1: Credential */}
        <AccessBoardColumn
          step={1}
          title={t("Observed credential", "Credential quan sát được")}
          subtitle={t("Identity evidence on service requests", "Bằng chứng định danh trên request tới Service")}
        >
          <input
            aria-label={t("Find credential", "Tìm credential")}
            placeholder={t("Find credential", "Tìm credential")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="toolbar-control mb-2 h-9 w-full px-2 text-sm"
          />
          <div className="space-y-1">
            {visibleCredentials
              .filter((account) => account.username.toLowerCase().includes(search.toLowerCase()))
              .map((account) => {
                const isActive = selectedPrincipal === account.username;
                return (
                  <button
                    key={account.username}
                    aria-pressed={isActive}
                    onClick={() => setSelectedPrincipal(isActive ? null : account.username)}
                    className={control(isActive, "border-[#b877d9] bg-[#b877d9]/15 shadow-sm")}
                  >
                    <span className="flex items-center justify-between gap-2 text-[#e3c4f1]">
                      <span className="flex items-center gap-2 truncate">
                        <KeyRound size={14} aria-hidden="true" />
                        <span className="truncate font-mono text-sm">{account.username}</span>
                      </span>
                      {isActive && <X size={13} className="shrink-0 text-[#e3c4f1]" />}
                    </span>
                    <span className="mt-1 block text-xs text-[#c2c6cc]">
                      {n(account.requests, 0)} {t("requests")}
                    </span>
                  </button>
                );
              })}
          </div>
          {!visibleCredentials.some((account) =>
            account.username.toLowerCase().includes(search.toLowerCase())
          ) && empty(t("No matching credential evidence", "Không có bằng chứng credential phù hợp"))}
        </AccessBoardColumn>

        {/* Column 2: IP */}
        <AccessBoardColumn
          step={2}
          title={t("Observed IP", "IP quan sát được")}
          subtitle={t("Supporting network evidence", "Bằng chứng mạng hỗ trợ")}
        >
          {relationships.isLoading ? (
            <Loading />
          ) : relationships.isError ? (
            <>
              <ErrorState message={relationships.error.message} />
              <button className="btn" onClick={() => relationships.refetch()}>
                {t("Retry", "Thử lại")}
              </button>
            </>
          ) : (
            <>
              <input
                aria-label={t("Find IP…", "Tìm IP…")}
                placeholder={t("Find IP…", "Tìm IP…")}
                value={ipSearch}
                onChange={(e) => setIpSearch(e.target.value)}
                className="toolbar-control mb-2 h-9 w-full px-2 text-sm"
              />
              <div className="space-y-1">
                {visibleIps
                  .filter((source) => source.name.includes(ipSearch))
                  .map((source) => {
                    const isActive = selectedIp === source.name;
                    return (
                      <button
                        key={source.name}
                        aria-pressed={isActive}
                        onClick={() => setSelectedIp(isActive ? null : source.name)}
                        className={control(isActive, "border-[#c2c6cc] bg-[#a7a9ab]/15 shadow-sm")}
                      >
                        <span className="flex items-center justify-between gap-2 text-[#f1f3f5]">
                          <span className="flex items-center gap-2 truncate">
                            <Globe2 size={14} aria-hidden="true" />
                            <span className="break-all font-mono text-sm">
                              {source.name || t("IP unavailable", "IP không khả dụng")}
                            </span>
                          </span>
                          {isActive && <X size={13} className="shrink-0 text-[#f1f3f5]" />}
                        </span>
                        <span className="mt-1 block text-xs text-[#c2c6cc]">
                          {source.items[0]?.role_label || source.items[0]?.source_ip_role || t("Unknown")} ·{" "}
                          {n(source.requests, 0)} {t("requests")}
                        </span>
                      </button>
                    );
                  })}
              </div>
              {!visibleIps.some((source) => source.name.includes(ipSearch)) &&
                empty(t("No matching IP evidence", "Không có bằng chứng IP phù hợp"))}
            </>
          )}
        </AccessBoardColumn>

        {/* Column 3: API */}
        <AccessBoardColumn
          step={3}
          title="API"
          subtitle={t("Operations on the Service", "API của Service này")}
        >
          <input
            aria-label={t("Find API…", "Tìm API…")}
            placeholder={t("Find API…", "Tìm API…")}
            value={apiSearch}
            onChange={(e) => setApiSearch(e.target.value)}
            className="toolbar-control mb-2 h-9 w-full px-2 text-sm"
          />
          <div className="space-y-1">
            {visibleOperations
              .filter((item) => item.name.toLowerCase().includes(apiSearch.toLowerCase()))
              .map((item) => {
                const isActive = selectedOperation === item.name;
                return (
                  <button
                    key={item.name}
                    aria-pressed={isActive}
                    onClick={() => setSelectedOperation(isActive ? null : item.name)}
                    className={control(isActive, "border-[#56b9a8] bg-[#56b9a8]/15 shadow-sm")}
                  >
                    <span className="flex items-center justify-between gap-2 text-[#9be7d8]">
                      <span className="flex items-center gap-2 truncate">
                        <Fingerprint size={14} aria-hidden="true" />
                        <span className="truncate font-mono text-sm">
                          {item.name || t("Unknown operation", "Operation chưa xác định")}
                        </span>
                      </span>
                      {isActive && <X size={13} className="shrink-0 text-[#9be7d8]" />}
                    </span>
                    <span className="mt-1 block text-xs text-[#c2c6cc]">
                      {n(item.tps ?? 0, 2)} TPS · {n(item.requests ?? 0, 0)} {t("requests")} ·{" "}
                      {pct(item.errorRate ?? 0)} {t("error")}
                    </span>
                  </button>
                );
              })}
          </div>
          {!visibleOperations.some((item) =>
            item.name.toLowerCase().includes(apiSearch.toLowerCase())
          ) && empty(t("No matching API evidence", "Không có bằng chứng API phù hợp"))}
        </AccessBoardColumn>
      </div>

      {relationships.hasNextPage && (
        <div className="border-t border-[#2a2d30] p-2 text-center">
          <button
            className="btn disabled:opacity-40"
            disabled={relationships.isFetchingNextPage}
            onClick={() => relationships.fetchNextPage()}
          >
            {relationships.isFetchingNextPage ? t("Loading…") : t("Load more relationships", "Tải thêm quan hệ")}
          </button>
        </div>
      )}

      {/* Selected Drilldown Summary */}
      {hasSelection ? (
        <div className="border-t border-[#2a2d30] p-3" aria-live="polite">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="flex items-center gap-1 font-mono text-[#a9ccff]">
              <Server size={14} aria-hidden="true" />
              <span>{service}</span>
            </span>

            {selectedOperation && (
              <>
                <ArrowRight size={13} className="text-[#7b7d80]" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 rounded bg-[#56b9a8]/15 px-2 py-0.5 font-mono text-[#9be7d8]">
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
                    className="ml-1 text-[#9be7d8] hover:text-white"
                    title={t("Clear API filter")}
                  >
                    <X size={11} />
                  </button>
                </span>
              </>
            )}

            {selectedPrincipal && (
              <>
                <ArrowRight size={13} className="text-[#7b7d80]" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 rounded bg-[#b877d9]/15 px-2 py-0.5 font-mono text-[#e3c4f1]">
                  <KeyRound size={12} aria-hidden="true" />
                  <span>{selectedPrincipal}</span>
                  <button
                    onClick={() => setSelectedPrincipal(null)}
                    className="ml-1 text-[#e3c4f1] hover:text-white"
                    title={t("Clear credential filter")}
                  >
                    <X size={11} />
                  </button>
                </span>
              </>
            )}

            {selectedIp && (
              <>
                <ArrowRight size={13} className="text-[#7b7d80]" aria-hidden="true" />
                <span className="inline-flex items-center gap-1 rounded bg-[#a7a9ab]/15 px-2 py-0.5 font-mono text-[#f1f3f5]">
                  <Globe2 size={12} aria-hidden="true" />
                  <span>{selectedIp}</span>
                  <button
                    onClick={() => setSelectedIp(null)}
                    className="ml-1 text-[#f1f3f5] hover:text-white"
                    title={t("Clear IP filter")}
                  >
                    <X size={11} />
                  </button>
                </span>
              </>
            )}
          </div>

          <p className="my-2 text-xs text-[#c2c6cc]">
            {t(
              "Observed credential and IP are supporting evidence. Open a Trace to confirm the caller chain.",
              "Credential và IP quan sát được là bằng chứng hỗ trợ. Mở Trace để xác nhận chuỗi caller."
            )}
          </p>

          <div className="mb-3 flex flex-wrap gap-4 font-mono text-xs text-[#c2c6cc]">
            <span>{n(metrics.requests, 0)} {t("requests")}</span>
            <span>{n(metrics.tps, 2)} TPS</span>
            <span>{pct(metrics.errorRate)} {t("error")}</span>
            <span>{n(metrics.p95, 1)} ms {t("Max bucket P95", "P95 bucket lớn nhất")}</span>
          </div>

          {callers.length > 0 && (
            <div className="divide-y divide-[#2a2d30]">
              {callers.map((caller) => (
                <div key={caller.name} className="flex flex-wrap justify-between gap-2 py-2 text-xs">
                  <span className="text-[#a9ccff]">
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
                  <span className="font-mono text-[#c2c6cc]">{n(caller.requests, 0)} {t("requests")}</span>
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
            <span className="text-[11px] text-[#a7a9ab]">
              {t(
                "Trace search scoped to selected filters",
                "Tìm Trace theo các bộ lọc đã chọn"
              )}
            </span>
          </div>
        </div>
      ) : (
        <div className="border-t border-[#2a2d30] px-3 py-2 text-center text-xs text-[#7b7d80]">
          {t(
            "Click any Credential, IP, or API above to cross-filter relationships and view callers.",
            "Chọn bất kỳ Credential, IP hoặc API nào ở trên để lọc chéo quan hệ và xem caller."
          )}
        </div>
      )}
    </Panel>
  );
}

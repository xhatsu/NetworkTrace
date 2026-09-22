import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useNavigate, useOutletContext } from "react-router-dom";
import { ArrowRight, ChevronRight, Globe2, Network, Server, User, X } from "lucide-react";
import { api } from "../../api";
import { ErrorState, Loading } from "../../components";
import { useI18n } from "../../i18n";

type Metrics = {
  tps?: number;
  request_count?: number;
  error_rate?: number;
  p95_latency_ms?: number;
};

type IpItem = {
  source_ip: string;
  service?: string;
  api?: string;
  caller_service?: string;
  source_ip_role?: string;
  role_label?: string;
  attribution_confidence?: string;
  request_count?: number;
  tps?: number;
  error_rate?: number;
  p95_latency_ms?: number;
  first_seen_ms?: number;
  last_seen_ms?: number;
  is_load_balancer?: boolean;
  is_new_ip?: boolean;
};

type IpPage = { items: IpItem[]; next_cursor?: string | null };

type Choice = {
  name: string;
  metrics: Metrics;
  relationCount: number;
};

const QUERY_SUFFIX = "window=7d";

function relationKey(item: IpItem) {
  return [item.source_ip, item.service, item.api, item.caller_service].map((value) => value || "").join("|");
}

function count(value: number | undefined) {
  return Number(value || 0).toLocaleString();
}

function percent(value: number | undefined) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function formatTime(value?: number) {
  return value ? new Date(value).toLocaleString() : "—";
}

function aggregateMetrics(items: IpItem[]): Metrics {
  const requestCount = items.reduce((sum, item) => sum + Number(item.request_count || 0), 0);
  const errorCount = items.reduce((sum, item) => sum + Number(item.request_count || 0) * Number(item.error_rate || 0), 0);
  return {
    request_count: requestCount,
    tps: items.reduce((sum, item) => sum + Number(item.tps || 0), 0),
    error_rate: requestCount ? errorCount / requestCount : 0,
    p95_latency_ms: Math.max(0, ...items.map((item) => Number(item.p95_latency_ms || 0))),
  };
}

function metricText(metrics: Metrics | undefined, t: (key: string, fallback?: string) => string) {
  return `${(metrics?.tps || 0).toFixed(2)} TPS · ${count(metrics?.request_count)} ${t("requests")} · ${percent(metrics?.error_rate)} ${t("errors")}`;
}

function statusClass(item: { isNew: boolean; isLoadBalancer: boolean; metrics?: Metrics; error_rate?: number }) {
  if (item.isNew) return "border-amber-400/60 bg-amber-500/10 text-amber-200";
  if (Number(item.metrics?.error_rate || item.error_rate || 0) >= 0.1) return "border-rose-400/60 bg-rose-500/10 text-rose-200";
  return "border-[#34373b] bg-[#181b1f] text-[#a7a9ab]";
}

export function UserTopologyTab() {
  const { principal } = useOutletContext<{ principal: string; profile: unknown }>();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [selectedIp, setSelectedIp] = useState<string | null>(null);
  const [selectedService, setSelectedService] = useState<string | null>(null);
  const [selectedApi, setSelectedApi] = useState<string | null>(null);
  const [selectedRelation, setSelectedRelation] = useState<string | null>(null);
  const [ipFilter, setIpFilter] = useState("");

  useEffect(() => {
    setSelectedIp(null);
    setSelectedService(null);
    setSelectedApi(null);
    setSelectedRelation(null);
    setIpFilter("");
  }, [principal]);

  const ipsQuery = useInfiniteQuery({
    queryKey: ["principal-topology-ips", principal, "7d"],
    initialPageParam: "",
    queryFn: ({ pageParam }) => api<IpPage>(`/api/v1/topology/principals/${encodeURIComponent(principal)}/ips?${QUERY_SUFFIX}&page_size=500${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`),
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: !!principal,
  });

  const allIpItems = ipsQuery.data?.pages.flatMap((page) => page.items || []) || [];
  const ipSummaries = useMemo(() => {
    const grouped = new Map<string, IpItem[]>();
    allIpItems.forEach((item) => {
      if (!item.source_ip) return;
      grouped.set(item.source_ip, [...(grouped.get(item.source_ip) || []), item]);
    });
    return [...grouped.entries()].map(([sourceIp, items]) => ({
      sourceIp,
      items,
      metrics: aggregateMetrics(items),
      roleLabel: items.find((item) => item.role_label)?.role_label || items[0]?.source_ip_role || t("Unknown source"),
      isLoadBalancer: items.some((item) => item.is_load_balancer),
      isNew: items.some((item) => item.is_new_ip),
    })).sort((left, right) => Number(right.metrics.request_count || 0) - Number(left.metrics.request_count || 0));
  }, [allIpItems, t]);

  const filteredIpSummaries = useMemo(() => {
    const needle = ipFilter.trim().toLowerCase();
    if (!needle) return ipSummaries;
    return ipSummaries.filter((item) => `${item.sourceIp} ${item.roleLabel}`.toLowerCase().includes(needle));
  }, [ipFilter, ipSummaries]);

  const selectedIpItems = useMemo(
    () => allIpItems.filter((item) => item.source_ip === selectedIp),
    [allIpItems, selectedIp],
  );

  const serviceChoices = useMemo<Choice[]>(() => {
    const grouped = new Map<string, IpItem[]>();
    selectedIpItems.forEach((item) => {
      const service = item.service || "";
      if (!service) return;
      grouped.set(service, [...(grouped.get(service) || []), item]);
    });
    return [...grouped.entries()].map(([name, items]) => ({
      name,
      metrics: aggregateMetrics(items),
      relationCount: items.length,
    })).sort((left, right) => Number(right.metrics.request_count || 0) - Number(left.metrics.request_count || 0));
  }, [selectedIpItems]);

  const apiChoices = useMemo<Choice[]>(() => {
    const grouped = new Map<string, IpItem[]>();
    selectedIpItems.filter((item) => item.service === selectedService).forEach((item) => {
      const apiName = item.api || "";
      if (!apiName) return;
      grouped.set(apiName, [...(grouped.get(apiName) || []), item]);
    });
    return [...grouped.entries()].map(([name, items]) => ({
      name,
      metrics: aggregateMetrics(items),
      relationCount: items.length,
    })).sort((left, right) => Number(right.metrics.request_count || 0) - Number(left.metrics.request_count || 0));
  }, [selectedIpItems, selectedService]);

  const relationItems = useMemo(
    () => selectedIpItems.filter((item) => item.service === selectedService && item.api === selectedApi),
    [selectedApi, selectedIpItems, selectedService],
  );
  const selectedRelationItem = relationItems.find((item) => relationKey(item) === selectedRelation) || relationItems[0];
  const totalRelations = allIpItems.length;
  const userServiceCount = new Set(allIpItems.map((item) => item.service).filter(Boolean)).size;
  const apiCount = new Set(allIpItems.map((item) => `${item.service || ""}|${item.api || ""}`)).size;

  function selectIp(sourceIp: string) {
    setSelectedIp(sourceIp);
    setSelectedService(null);
    setSelectedApi(null);
    setSelectedRelation(null);
  }

  function selectService(service: string) {
    setSelectedService(service);
    setSelectedApi(null);
    setSelectedRelation(null);
  }

  function selectApi(apiName: string) {
    setSelectedApi(apiName);
    const firstRelation = selectedIpItems.find((item) => item.service === selectedService && item.api === apiName);
    setSelectedRelation(firstRelation ? relationKey(firstRelation) : null);
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3 border border-[#2a2d30] bg-[#111217] px-4 py-3">
        <div className="flex items-start gap-3">
          <div className="grid h-8 w-8 shrink-0 place-items-center border border-cyan-400/40 bg-cyan-500/10 text-cyan-300"><Network size={17} /></div>
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[.16em] text-cyan-300">{t("Access & Topology")}</div>
            <h2 className="mt-1 text-sm font-semibold text-white">{t("IP → User → Service → API")}</h2>
            <p className="mt-1 max-w-2xl text-xs text-[#a7a9ab]">{t("Start from a source IP, then select the User, Service, and API to inspect the exact relationship.")}</p>
          </div>
        </div>
        <div className="border border-[#34373b] bg-[#181b1f] px-3 py-1.5 text-[11px] font-semibold text-[#a7a9ab]">{t("5-minute buckets · 7-day history")}</div>
      </header>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          [t("Unique IPs"), ipSummaries.length, t("Observed source addresses")],
          [t("Users"), 1, t("User selected by this route")],
          [t("Services"), selectedIp ? serviceChoices.length : userServiceCount, selectedIp ? t("Services for selected IP") : t("Services used by this User")],
          [t("Relations"), totalRelations, t("IP → User → Service → API rows")],
        ].map(([label, value, detail]) => (
          <div key={String(label)} className="border border-[#2a2d30] bg-[#111217] px-3 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-[#7b7d80]">{label}</div>
            <div className="mt-1 font-mono text-xl font-bold tabular-nums text-white">{typeof value === "number" ? count(value) : value}</div>
            <div className="mt-1 text-[10px] text-[#7b7d80]">{detail}</div>
          </div>
        ))}
      </div>

      {ipsQuery.isError ? <ErrorState message={ipsQuery.error instanceof Error ? ipsQuery.error.message : t("Unable to load source IP relationships.")} /> : (
        <div className="grid gap-3 xl:grid-cols-[270px_220px_280px_minmax(0,1fr)]">
          <section className="min-w-0 border border-[#2a2d30] bg-[#111217]">
            <div className="border-b border-[#2a2d30] px-3 py-3">
              <div className="flex items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-xs font-semibold text-white"><Globe2 size={14} className="text-amber-300" />{t("IP list")}</h3><span className="font-mono text-[10px] text-[#7b7d80]">{ipSummaries.length}</span></div>
              <input value={ipFilter} onChange={(event) => setIpFilter(event.target.value)} placeholder={t("Filter IP or role...")} className="mt-3 h-8 w-full border border-[#34373b] bg-[#181b1f] px-2.5 text-xs text-white outline-none placeholder:text-[#7b7d80] focus:border-cyan-400" />
            </div>
            <div className="max-h-[470px] overflow-y-auto">
              {ipsQuery.isLoading ? <Loading /> : filteredIpSummaries.map((item) => (
                <button key={item.sourceIp} type="button" onClick={() => selectIp(item.sourceIp)} className={`w-full border-b border-[#2a2d30] px-3 py-3 text-left transition hover:bg-[#202226] ${selectedIp === item.sourceIp ? "bg-cyan-500/10" : "bg-transparent"}`}>
                  <div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs font-semibold text-white">{item.sourceIp}</span><ChevronRight size={14} className={selectedIp === item.sourceIp ? "text-cyan-300" : "text-[#7b7d80]"} /></div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-[#a7a9ab]"><span className="truncate">{item.roleLabel}</span><span>{item.items.length} {t("relations")}</span></div>
                  <div className="mt-2 flex items-center justify-between gap-2 font-mono text-[10px] text-[#7b7d80]"><span className="truncate">{metricText(item.metrics, t)}</span><span className={`shrink-0 border px-1 py-0.5 ${statusClass(item)}`}>{item.isNew ? t("NEW") : item.isLoadBalancer ? t("LB") : t("Known")}</span></div>
                </button>
              ))}
              {!ipsQuery.isLoading && !filteredIpSummaries.length && <div className="px-3 py-10 text-center text-xs text-[#7b7d80]">{t("No source IP relationships in this window.")}</div>}
              {ipsQuery.hasNextPage && <button type="button" onClick={() => ipsQuery.fetchNextPage()} disabled={ipsQuery.isFetchingNextPage} className="m-3 w-[calc(100%-1.5rem)] border border-[#34373b] bg-[#181b1f] px-3 py-2 text-[11px] font-semibold text-[#a7a9ab] transition hover:bg-[#202226] hover:text-white disabled:cursor-wait disabled:opacity-60">{ipsQuery.isFetchingNextPage ? t("Loading...") : t("Load more IP relations")}</button>}
            </div>
          </section>

          <section className="min-w-0 border border-[#2a2d30] bg-[#111217]">
            <div className="border-b border-[#2a2d30] px-3 py-3"><h3 className="flex items-center gap-2 text-xs font-semibold text-white"><User size={14} className="text-cyan-300" />{t("User")}</h3><div className="mt-1 text-[10px] text-[#7b7d80]">{t("User selected by this route")}</div></div>
            <div className="p-3">
              <div className="border border-cyan-400/40 bg-cyan-500/10 p-3"><div className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">{t("Selected User")}</div><div className="mt-2 break-all font-mono text-sm font-bold text-white">{principal}</div>{selectedIp ? <div className="mt-2 break-all font-mono text-[10px] text-[#a7a9ab]">{t("Source IP")}: {selectedIp}</div> : <div className="mt-2 text-[10px] text-[#a7a9ab]">{t("Select an IP to scope this User.")}</div>}</div>
              <div className="mt-3 space-y-2 text-[10px] text-[#a7a9ab]"><div className="flex justify-between gap-2"><span>{t("Relations")}</span><span className="font-mono text-white">{selectedIp ? selectedIpItems.length : totalRelations}</span></div><div className="flex justify-between gap-2"><span>{t("Services")}</span><span className="font-mono text-white">{selectedIp ? serviceChoices.length : userServiceCount}</span></div><div className="flex justify-between gap-2"><span>{t("IPs")}</span><span className="font-mono text-white">{ipSummaries.length}</span></div></div>
            </div>
          </section>

          <section className="min-w-0 border border-[#2a2d30] bg-[#111217]">
            <div className="border-b border-[#2a2d30] px-3 py-3"><div className="flex items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-xs font-semibold text-white"><Server size={14} className="text-blue-300" />{t("Service")}</h3><span className="font-mono text-[10px] text-[#7b7d80]">{serviceChoices.length}</span></div><div className="mt-1 truncate text-[10px] text-[#7b7d80]">{selectedIp || t("Select an IP first.")}</div></div>
            <div className="max-h-[470px] overflow-y-auto">
              {!selectedIp ? <div className="px-3 py-12 text-center text-xs text-[#7b7d80]">{t("Select the User revealed by an IP to see Services.")}</div> : serviceChoices.map((service) => (
                <button key={service.name} type="button" onClick={() => selectService(service.name)} className={`w-full border-b border-[#2a2d30] px-3 py-3 text-left transition hover:bg-[#202226] ${selectedService === service.name ? "bg-blue-500/10" : "bg-transparent"}`}><div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs font-semibold text-white">{service.name}</span><ChevronRight size={14} className={selectedService === service.name ? "text-blue-300" : "text-[#7b7d80]"} /></div><div className="mt-1 text-[10px] text-[#a7a9ab]">{metricText(service.metrics, t)}</div><div className="mt-1 text-[10px] text-[#7b7d80]">{service.relationCount} {t("relations")}</div></button>
              ))}
              {selectedIp && !serviceChoices.length && <div className="px-3 py-12 text-center text-xs text-[#7b7d80]">{t("No Services found for this IP.")}</div>}
            </div>
          </section>

          <section className="min-w-0 border border-[#2a2d30] bg-[#111217]">
            <div className="border-b border-[#2a2d30] px-3 py-3"><div className="flex items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-xs font-semibold text-white"><Globe2 size={14} className="text-emerald-300" />{t("API")}</h3><span className="font-mono text-[10px] text-[#7b7d80]">{apiChoices.length}</span></div><div className="mt-1 truncate text-[10px] text-[#7b7d80]">{selectedService || t("Select a Service first.")}</div></div>
            <div className="max-h-[470px] overflow-y-auto">
              {!selectedService ? <div className="px-3 py-12 text-center text-xs text-[#7b7d80]">{t("Select a Service to reveal its APIs.")}</div> : apiChoices.map((apiItem) => (
                <button key={apiItem.name} type="button" onClick={() => selectApi(apiItem.name)} className={`w-full border-b border-[#2a2d30] px-3 py-3 text-left transition hover:bg-[#202226] ${selectedApi === apiItem.name ? "bg-emerald-500/10" : "bg-transparent"}`}><div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs font-semibold text-white">{apiItem.name}</span><ChevronRight size={14} className={selectedApi === apiItem.name ? "text-emerald-300" : "text-[#7b7d80]"} /></div><div className="mt-1 text-[10px] text-[#a7a9ab]">{metricText(apiItem.metrics, t)}</div><div className="mt-1 text-[10px] text-[#7b7d80]">{apiItem.relationCount} {t("relations")}</div></button>
              ))}
              {selectedService && !apiChoices.length && <div className="px-3 py-12 text-center text-xs text-[#7b7d80]">{t("No APIs found for this Service and IP.")}</div>}
            </div>
          </section>
        </div>
      )}

      <section className="border border-[#2a2d30] bg-[#111217]">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2a2d30] px-3 py-3"><div><h3 className="text-xs font-semibold text-white">{t("Selected relationship")}</h3><p className="mt-1 text-[10px] text-[#7b7d80]">{t("Select one API to show its exact IP → User → Service → API relation.")}</p></div>{selectedRelationItem && <button type="button" onClick={() => setSelectedRelation(null)} className="inline-flex items-center gap-1 text-[11px] text-[#a7a9ab] hover:text-white"><X size={13} />{t("Clear selection")}</button>}</div>
        {!selectedApi ? <div className="px-4 py-10 text-center text-xs text-[#7b7d80]">{t("Select an API to inspect the relation.")}</div> : (
          <div className="grid gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,360px)]">
            <div className="min-w-0"><div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.14em] text-emerald-300"><Network size={13} />{t("Relations")}</div><div className="space-y-1">{relationItems.map((item) => { const key = relationKey(item); return <button key={key} type="button" onClick={() => setSelectedRelation(key)} className={`flex w-full items-center justify-between gap-3 border px-3 py-2 text-left text-xs transition hover:bg-[#202226] ${selectedRelation === key ? "border-emerald-400/60 bg-emerald-500/10" : "border-[#2a2d30] bg-[#181b1f]"}`}><span className="min-w-0 truncate font-mono text-[#d8d9da]">{item.caller_service || t("Unknown caller")} <span className="text-[#7b7d80]">→</span> {item.source_ip}</span><span className="shrink-0 font-mono text-[10px] text-[#a7a9ab]">{count(item.request_count)} {t("requests")}</span></button>; })}{!relationItems.length && <div className="px-3 py-8 text-xs text-[#7b7d80]">{t("No relation detail for this API.")}</div>}</div></div>
            {selectedRelationItem && <div className="border border-emerald-400/30 bg-emerald-500/[0.04] p-3"><div className="text-[10px] font-bold uppercase tracking-[.14em] text-emerald-300">{t("Relationship detail")}</div><div className="mt-3 space-y-2 text-xs"><div className="grid grid-cols-[90px_1fr] gap-2"><span className="text-[#7b7d80]">{t("Source IP")}</span><span className="break-all font-mono text-white">{selectedRelationItem.source_ip}</span></div><div className="grid grid-cols-[90px_1fr] gap-2"><span className="text-[#7b7d80]">{t("User")}</span><span className="break-all font-mono text-white">{principal}</span></div><div className="grid grid-cols-[90px_1fr] gap-2"><span className="text-[#7b7d80]">{t("Service")}</span><span className="break-all font-mono text-blue-300">{selectedRelationItem.service}</span></div><div className="grid grid-cols-[90px_1fr] gap-2"><span className="text-[#7b7d80]">{t("API")}</span><span className="break-all font-mono text-emerald-300">{selectedRelationItem.api}</span></div><div className="grid grid-cols-[90px_1fr] gap-2"><span className="text-[#7b7d80]">{t("Caller Service")}</span><span className="break-all font-mono text-violet-300">{selectedRelationItem.caller_service || t("Unknown caller")}</span></div><div className="mt-3 grid grid-cols-3 gap-2 border-t border-[#2a2d30] pt-3 text-center"><div><div className="font-mono text-sm font-bold text-white">{count(selectedRelationItem.request_count)}</div><div className="text-[10px] text-[#7b7d80]">{t("Requests")}</div></div><div><div className="font-mono text-sm font-bold text-sky-300">{Number(selectedRelationItem.tps || 0).toFixed(2)}</div><div className="text-[10px] text-[#7b7d80]">TPS</div></div><div><div className="font-mono text-sm font-bold text-violet-300">{Number(selectedRelationItem.p95_latency_ms || 0).toFixed(0)} ms</div><div className="text-[10px] text-[#7b7d80]">P95</div></div></div><div className="grid grid-cols-2 gap-2 pt-1 text-[10px] text-[#7b7d80]"><span>{t("First seen")}: {formatTime(selectedRelationItem.first_seen_ms)}</span><span>{t("Last seen")}: {formatTime(selectedRelationItem.last_seen_ms)}</span></div></div></div>}
          </div>
        )}
      </section>

      {selectedService && <button type="button" onClick={() => navigate(`/services/${encodeURIComponent(selectedService)}`)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-300 hover:text-white">{t("Open service investigation")} <ArrowRight size={13} /></button>}
    </div>
  );
}

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useOutletContext } from "react-router-dom";
import { ArrowRight, ChevronRight, Globe2, Network, Server, User } from "lucide-react";
import { api } from "../../api";
import { useI18n } from "../../i18n";

type Metrics = { tps?: number; request_count?: number; error_rate?: number; p95_latency_ms?: number; change?: { status?: string } };
type TopologyNode = { id: string; name: string; type: "service" | "api"; service?: string; api?: string; metrics?: Metrics };
type Expansion = { nodes: TopologyNode[]; backend: string };
type IpItem = { source_ip: string; source_ip_role?: string; role_label?: string; attribution_confidence?: string; request_count?: number; error_rate?: number; p95_latency_ms?: number; is_load_balancer?: boolean; is_new_ip?: boolean };
type IpPage = { items: IpItem[]; next_cursor?: string | null };

function metricText(metrics?: Metrics) {
  return `${(metrics?.tps || 0).toFixed(2)} TPS · ${(metrics?.request_count || 0).toLocaleString()} requests · ${((metrics?.error_rate || 0) * 100).toFixed(2)}% errors`;
}

export function UserTopologyTab() {
  const { principal } = useOutletContext<{ principal: string; profile: unknown }>();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [selectedService, setSelectedService] = useState<string | null>(null);
  const [selectedApi, setSelectedApi] = useState<string | null>(null);
  const querySuffix = "window=7d";

  useEffect(() => {
    setSelectedService(null);
    setSelectedApi(null);
  }, [principal]);

  const servicesQuery = useQuery({
    queryKey: ["principal-topology-services", principal, "7d"],
    queryFn: () => api<Expansion>(`/api/v1/topology/principals/${encodeURIComponent(principal)}/services?${querySuffix}`),
    enabled: !!principal,
  });
  const apisQuery = useQuery({
    queryKey: ["principal-topology-apis", principal, selectedService, "7d"],
    queryFn: () => api<Expansion>(`/api/v1/topology/principals/${encodeURIComponent(principal)}/services/${encodeURIComponent(selectedService || "")}/apis?${querySuffix}`),
    enabled: !!principal && !!selectedService,
  });
  const ipsQuery = useQuery({
    queryKey: ["principal-topology-ips", principal, selectedService, selectedApi, "7d"],
    queryFn: () => api<IpPage>(`/api/v1/topology/principals/${encodeURIComponent(principal)}/ips?${querySuffix}&service=${encodeURIComponent(selectedService || "")}&api=${encodeURIComponent(selectedApi || "")}&page_size=100`),
    enabled: !!principal && !!selectedService && !!selectedApi,
  });

  const services = servicesQuery.data?.nodes || [];
  const apis = apisQuery.data?.nodes || [];
  const ips = ipsQuery.data?.items || [];
  const loading = servicesQuery.isLoading || apisQuery.isLoading || ipsQuery.isLoading;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#262838] bg-[#141622] px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-cyan-500/15 text-cyan-300"><Network size={17} /></div>
          <div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white">{t("User → Service → API → IP")}</h2>
            <p className="text-[11px] text-[#94a3b8]">{t("Start with identity behavior, then reveal its service, API, and source-IP evidence.")}</p>
          </div>
        </div>
        <div className="rounded-lg border border-[#262838] bg-[#0c0d14] px-3 py-1.5 text-[11px] font-semibold text-[#94a3b8]">{t("5-minute buckets · 7-day history")}</div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[220px_1fr_1fr]">
        <section className="rounded-xl border border-cyan-500/40 bg-[#141622] p-4">
          <div className="mb-3 text-[10px] font-bold uppercase tracking-widest text-cyan-300">{t("User")}</div>
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-cyan-400 text-[#081014]"><User size={20} /></div>
          <div className="mt-3 break-all font-mono text-sm font-bold text-white">{principal}</div>
          <div className="mt-2 text-[11px] text-[#94a3b8]">{services.length} {t("Services")}</div>
        </section>

        <section className="rounded-xl border border-[#262838] bg-[#141622] p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-violet-300"><Server size={14} /> {t("Services")}</div>
            <span className="text-[10px] text-[#64748b]">{services.length}</span>
          </div>
          <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
            {services.map((node) => (
              <button key={node.id} onClick={() => { setSelectedService(node.service || node.name); setSelectedApi(null); }} className={`w-full rounded-lg border p-3 text-left transition ${selectedService === (node.service || node.name) ? "border-violet-400 bg-violet-500/15" : "border-[#262838] bg-[#0f111b] hover:border-violet-500/60"}`}>
                <div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs font-bold text-white">{node.name}</span><ChevronRight size={14} className="shrink-0 text-violet-300" /></div>
                <div className="mt-1 truncate text-[10px] text-[#94a3b8]">{metricText(node.metrics)}</div>
                {node.metrics?.change?.status === "new" && <span className="mt-2 inline-block rounded border border-amber-400/50 bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-bold text-amber-300">NEW</span>}
              </button>
            ))}
            {!servicesQuery.isLoading && services.length === 0 && <div className="py-10 text-center text-xs text-[#64748b]">{t("No service relationships in this window.")}</div>}
          </div>
        </section>

        <section className="rounded-xl border border-[#262838] bg-[#141622] p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-emerald-300"><Globe2 size={14} /> API</div>
            <span className="text-[10px] text-[#64748b]">{apis.length}</span>
          </div>
          {!selectedService ? <div className="grid min-h-40 place-items-center text-center text-xs text-[#64748b]">{t("Select a service to reveal APIs used by this user.")}</div> : (
            <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
              {apis.map((node) => (
                <button key={node.id} onClick={() => setSelectedApi(node.api || node.name)} className={`w-full rounded-lg border p-3 text-left transition ${selectedApi === (node.api || node.name) ? "border-emerald-400 bg-emerald-500/15" : "border-[#262838] bg-[#0f111b] hover:border-emerald-500/60"}`}>
                  <div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs font-bold text-white" title={node.name}>{node.name}</span><ChevronRight size={14} className="shrink-0 text-emerald-300" /></div>
                  <div className="mt-1 truncate text-[10px] text-[#94a3b8]">{metricText(node.metrics)}</div>
                </button>
              ))}
              {!apisQuery.isLoading && apis.length === 0 && <div className="py-10 text-center text-xs text-[#64748b]">{t("No APIs observed for this service.")}</div>}
            </div>
          )}
        </section>
      </div>

      {selectedApi && (
        <section className="rounded-xl border border-amber-500/30 bg-[#141622] p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-amber-300">{t("Source IP evidence")}</div>
              <div className="mt-1 flex items-center gap-1.5 font-mono text-[11px] text-[#94a3b8]"><span>{selectedService}</span><ArrowRight size={12} /><span>{selectedApi}</span></div>
            </div>
            <span className="text-[10px] text-[#64748b]">{t("IPs stay outside the default topology and appear only for the selected API.")}</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-2">
            {ips.map((item) => (
              <div key={`${item.source_ip}:${item.source_ip_role || "unknown"}`} className="rounded-lg border border-[#262838] bg-[#0f111b] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs font-bold text-white">{item.source_ip}</span>
                  <div className="flex gap-1">{item.is_load_balancer && <span className="rounded border border-amber-400/50 bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-bold text-amber-300">LB</span>}{item.is_new_ip && <span className="rounded border border-rose-400/50 bg-rose-500/15 px-1.5 py-0.5 text-[9px] font-bold text-rose-300">NEW</span>}</div>
                </div>
                <div className="mt-1 text-[10px] text-[#94a3b8]">{item.role_label || item.source_ip_role || t("Unknown source")} · {item.attribution_confidence || "low"}</div>
                <div className="mt-2 font-mono text-[10px] text-[#cbd5e1]">{(item.request_count || 0).toLocaleString()} requests · {((item.error_rate || 0) * 100).toFixed(2)}% errors · p95 {(item.p95_latency_ms || 0).toFixed(0)} ms</div>
              </div>
            ))}
            {!ipsQuery.isLoading && ips.length === 0 && <div className="py-8 text-xs text-[#64748b]">{t("No source IP evidence for this API in the selected window.")}</div>}
          </div>
        </section>
      )}

      {loading && <div className="text-center text-xs text-cyan-300">{t("Loading...")}</div>}
      {selectedService && <button onClick={() => navigate(`/services/${encodeURIComponent(selectedService)}`)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-violet-300 hover:text-violet-200">{t("Open service investigation")} <ArrowRight size={13} /></button>}
    </div>
  );
}

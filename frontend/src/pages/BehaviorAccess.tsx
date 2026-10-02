import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Panel } from "../components";
import { useI18n } from "../i18n";
import { AccessFlow, type FlowFilters, type FocusType } from "../components/AccessFlow";
import { AccessMatrix } from "../components/AccessMatrix";

type Entities = { entities: { type: string; name: string; service?: string; api?: string }[] };

// Names for the focus picker come from the already-bounded learned topology snapshot.
export function useLearnedNames() {
  const query = useQuery({
    queryKey: ["learned-topology-names"],
    queryFn: ({ signal }) => api<Entities>("/api/v1/behavior/topology", { signal }),
    staleTime: 60000,
  });
  return useMemo(() => {
    const list = query.data?.entities || [];
    return {
      services: list.filter(e => e.type === "service").map(e => e.name),
      apis: list.filter(e => e.type === "api").map(e => `${e.service} → ${e.api}`),
      credentials: list.filter(e => e.type === "principal").map(e => e.name),
    };
  }, [query.data]);
}

export function AccessFlowTab() {
  const { lang } = useI18n();
  const t = (en: string, vi?: string) => (lang === "vi" && vi ? vi : en);
  const [params, setParams] = useSearchParams();
  const names = useLearnedNames();
  const focusType = (params.get("focus_type") as FocusType) || "service";
  const focus = params.get("focus") || "";
  const [draft, setDraft] = useState(focus);
  const [filters, setFilters] = useState<FlowFilters>({});
  const set = (type: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set("tab", "flow"); next.set("focus_type", type);
    value ? next.set("focus", value) : next.delete("focus");
    setParams(next); setFilters({});
  };
  const options = focusType === "service" ? names.services : focusType === "api" ? names.apis : focusType === "credential" || focusType === "caller" ? (focusType === "caller" ? names.services : names.credentials) : [];
  return (
    <Panel title={t("Focused access flow", "Luồng truy cập theo tiêu điểm")}
      subtitle={t("Learned baseline against current observation for one Service, API, credential, caller or IP", "Baseline đã học so với quan sát hiện tại cho một Service, API, credential, caller hoặc IP")}>
      <form className="flex flex-wrap items-center gap-2 border-b border-line p-2 text-xs" onSubmit={e => { e.preventDefault(); set(focusType, draft.trim()); }}>
        <select className="btn" aria-label={t("Focus type", "Loại tiêu điểm")} value={focusType} onChange={e => { setDraft(""); set(e.target.value, ""); }}>
          <option value="service">Service</option><option value="api">API</option>
          <option value="credential">{t("Credential", "Credential")}</option><option value="caller">Caller Service</option><option value="ip">IP</option>
        </select>
        <input list="access-focus-options" className="toolbar-control h-8 min-w-[220px] flex-1 px-2" aria-label={t("Focus", "Tiêu điểm")} value={draft}
          placeholder={t("Type or pick a name…", "Nhập hoặc chọn tên…")} onChange={e => setDraft(e.target.value)} />
        <datalist id="access-focus-options">{options.slice(0, 500).map(o => <option key={o} value={o} />)}</datalist>
        <button type="submit" className="btn">{t("Show flow", "Hiển thị luồng")}</button>
      </form>
      {focus ? <AccessFlow key={`${focusType}:${focus}`} focusType={focusType} focus={focus} filters={filters} onFilters={setFilters} />
        : <div className="px-3 py-8 text-center text-xs text-muted">{t("Choose a focus to draw its learned flow.", "Chọn một tiêu điểm để vẽ luồng đã học.")}</div>}
    </Panel>
  );
}

export function AccessMatrixTab() {
  const { lang } = useI18n();
  const t = (en: string, vi?: string) => (lang === "vi" && vi ? vi : en);
  const names = useLearnedNames();
  return (
    <Panel title={t("Credential × API access matrix", "Ma trận truy cập credential × API")}
      subtitle={t("Shade is learned or observed TPS; markers show state. Similar access sets are grouped into blocks.", "Độ đậm là TPS đã học hoặc quan sát; ký hiệu là trạng thái. Nhóm quyền truy cập giống nhau thành khối.")}>
      <AccessMatrix services={names.services} />
    </Panel>
  );
}

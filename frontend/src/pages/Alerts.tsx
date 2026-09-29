import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { BellRing, Plus, RefreshCw, Save, Trash2, Webhook, X } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Page, Panel } from "../components";
import { useI18n } from "../i18n";

type Scope = "any" | "service" | "user" | "api";
type Condition = { subject: string; change_types: string[]; service: string; principal: string; operation: string; state: string; metric: string; operator: string; threshold: string };
type Rule = { id?: string; name: string; enabled: boolean; severity: string; condition: Condition; destinations: { type: string; target: string }[]; cooldown_minutes: number; created_at_ms?: number; updated_at_ms?: number };
type Delivery = { delivery_id: string; destination_type: string; destination_target: string; status: string; attempts: number; response_code: number; error: string; change_id?: string | number; change_summary?: string };
type NamedItem = { name?: string; principal_name?: string; username?: string };

const blank: Rule = { name: "", enabled: true, severity: "warning", condition: { subject: "any", change_types: [], service: "", principal: "", operation: "", state: "critical", metric: "", operator: "gt", threshold: "" }, destinations: [{ type: "webhook", target: "" }], cooldown_minutes: 30 };
const types = ["traffic_spike", "traffic_drop", "latency", "error_rate", "unusual_access", "new_service_edge", "new_principal_edge", "unusual_time", "principal_rate_surge", "auth_failure_burst", "new_target", "new_operation"];
const input = "toolbar-control h-9 w-full px-2 text-xs";

function normalizeRule(rule?: Rule): Rule {
  if (!rule) return structuredClone(blank);
  return {
    ...blank,
    ...rule,
    condition: { ...blank.condition, ...(rule.condition || {}), change_types: rule.condition?.change_types || [] },
    destinations: rule.destinations?.length ? rule.destinations : structuredClone(blank.destinations),
  };
}

function scopeFor(rule: Rule): Scope {
  if (rule.condition.operation) return "api";
  if (rule.condition.principal || rule.condition.subject === "user") return "user";
  if (rule.condition.service || rule.condition.subject === "service") return "service";
  return "any";
}

function scopeLabel(rule: Rule, t: (key: string, fallback?: string) => string) {
  const c = rule.condition;
  if (c.operation) return `${c.service || t("Any service", "Mọi Service")} / ${c.operation}`;
  if (c.principal) return c.principal;
  if (c.service) return c.service;
  if (c.subject === "user") return t("All users", "Mọi User");
  if (c.subject === "service") return t("All services", "Mọi Service");
  return t("All changes", "Mọi thay đổi");
}

export function AlertsPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Rule | null>(null);
  const [scope, setScope] = useState<Scope>("any");
  const [selectedService, setSelectedService] = useState("");
  const query = useQuery({ queryKey: ["alerts"], queryFn: () => api<{ items: Rule[] }>("/api/v1/alerts") });
  const services = useQuery({ queryKey: ["alert-scope-services"], queryFn: () => api<{ items: NamedItem[] }>("/api/v1/services?limit=500"), staleTime: 300_000 });
  const users = useQuery({ queryKey: ["alert-scope-users"], queryFn: () => api<{ items: NamedItem[] }>("/api/v1/users?limit=500&include_anonymous=false"), staleTime: 300_000 });
  const apis = useQuery({
    queryKey: ["alert-scope-apis", selectedService],
    queryFn: () => api<{ operations?: NamedItem[] }>(`/api/v1/services/${encodeURIComponent(selectedService)}`),
    enabled: scope === "api" && Boolean(selectedService), staleTime: 300_000,
  });
  const deliveries = useQuery({ queryKey: ["alert-deliveries"], queryFn: () => api<{ items: Delivery[] }>("/api/v1/alerts/deliveries") });
  const retry = useMutation({ mutationFn: () => api("/api/v1/alerts/deliveries/retry", { method: "POST" }), onSuccess: () => deliveries.refetch() });
  const save = useMutation({
    mutationFn: (rule: Rule) => api(`/api/v1/alerts${rule.id ? `/${rule.id}` : ""}`, { method: rule.id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rule) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); setDraft(null); },
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`/api/v1/alerts/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }) });
  const serviceNames = useMemo(() => [...new Set((services.data?.items || []).map(item => item.name).filter((name): name is string => Boolean(name)))].sort(), [services.data]);
  const userNames = useMemo(() => [...new Set((users.data?.items || []).map(item => item.principal_name || item.username || item.name).filter((name): name is string => Boolean(name)))].sort(), [users.data]);
  const apiNames = useMemo(() => [...new Set((apis.data?.operations || []).map(item => item.name).filter((name): name is string => Boolean(name)))].sort(), [apis.data]);

  useEffect(() => {
    if (!draft?.condition.service || scope !== "api") return;
    setSelectedService(draft.condition.service);
  }, [draft?.id, draft?.condition.service, scope]);

  const startNew = () => { setDraft(normalizeRule()); setScope("any"); setSelectedService(""); };
  const startEdit = (source: Rule) => {
    const normalized = normalizeRule(source);
    const selectedScope = scopeFor(normalized);
    setDraft(normalized);
    setScope(selectedScope);
    setSelectedService(selectedScope === "api" ? normalized.condition.service : "");
  };
  const patch = (fn: (rule: Rule) => Rule) => setDraft(current => current ? fn(current) : current);
  const updateScope = (next: Scope) => {
    setScope(next);
    setSelectedService("");
    patch(rule => ({ ...rule, condition: { ...rule.condition, subject: next === "user" ? "user" : next === "service" ? "service" : "any", service: "", principal: "", operation: "" } }));
  };
  const updateCondition = (key: keyof Condition, value: Condition[keyof Condition]) => patch(rule => ({ ...rule, condition: { ...rule.condition, [key]: value } }));
  const savedAt = (value?: number) => value ? new Date(value).toLocaleString() : "—";

  return <Page eyebrow={t("System", "HỆ THỐNG")} title={t("Alert rules", "Cấu hình cảnh báo")} description={t("Choose exactly which changes should notify you, down to User, Service, API, state, and threshold.", "Chọn chính xác thay đổi cần cảnh báo, đến mức User, Service, API, trạng thái và ngưỡng.")} actions={<button className="button-primary inline-flex items-center gap-1.5" onClick={startNew}><Plus size={14}/>{t("New rule", "Tạo rule")}</button>}>
    <div className="grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
      <Panel title={t("Configured rules", "Rule đã cấu hình")} subtitle={t("Review each rule's scope and delivery settings, or edit it in place.", "Xem phạm vi và cách gửi của từng rule hoặc chỉnh sửa trực tiếp.")}>
        <div className="divide-y divide-[#2a2d30]">
          {(query.data?.items || []).map(rule => <article key={rule.id} className="px-3 py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm font-semibold"><BellRing size={14} className={rule.enabled ? "text-[#ff9830]" : "text-[#7b7d80]"}/><span>{rule.name}</span><span className="rounded border border-[#34373b] px-1.5 py-0.5 text-[10px] uppercase text-[#a7a9ab]">{rule.severity}</span><span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${rule.enabled ? "border-[#73bf69]/40 text-[#73bf69]" : "border-[#34373b] text-[#7b7d80]"}`}>{rule.enabled ? t("Enabled", "Đang bật") : t("Disabled", "Đang tắt")}</span></div>
                <div className="mt-1 text-[11px] text-[#a7a9ab]">{t("Scope", "Phạm vi")}: <span className="font-mono text-[#d8d9da]">{scopeLabel(normalizeRule(rule), t)}</span></div>
              </div>
              <div className="flex shrink-0 gap-1"><button className="button-secondary" onClick={() => startEdit(rule)}>{t("Edit", "Sửa")}</button><button aria-label={`${t("Delete", "Xóa")} ${rule.name}`} className="button-secondary text-[#f2495c]" onClick={() => rule.id && remove.mutate(rule.id)}><Trash2 size={13}/></button></div>
            </div>
            <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-[#2a2d30] pt-3 text-[11px] sm:grid-cols-2 xl:grid-cols-3">
              <div><dt className="text-[#7b7d80]">{t("State", "Trạng thái")}</dt><dd className="mt-0.5 text-[#d8d9da]">{normalizeRule(rule).condition.state || "any"}</dd></div>
              <div><dt className="text-[#7b7d80]">{t("Change types", "Loại thay đổi")}</dt><dd className="mt-0.5 break-words text-[#d8d9da]">{rule.condition?.change_types?.join(", ") || t("All changes", "Mọi thay đổi")}</dd></div>
              <div><dt className="text-[#7b7d80]">{t("Threshold", "Ngưỡng")}</dt><dd className="mt-0.5 text-[#d8d9da]">{rule.condition?.metric ? `${rule.condition.metric} ${rule.condition.operator || "gt"} ${rule.condition.threshold || "—"}` : t("No metric threshold", "Không có ngưỡng chỉ số")}</dd></div>
              <div><dt className="text-[#7b7d80]">{t("Cooldown", "Thời gian chờ")}</dt><dd className="mt-0.5 text-[#d8d9da]">{rule.cooldown_minutes} {t("minutes", "phút")}</dd></div>
              <div><dt className="text-[#7b7d80]">{t("Destination", "Nơi nhận")}</dt><dd className="mt-0.5 break-all text-[#d8d9da]">{rule.destinations?.map(destination => `${destination.type}: ${destination.target}`).join(" · ") || "—"}</dd></div>
              <div><dt className="text-[#7b7d80]">{t("Updated", "Cập nhật")}</dt><dd className="mt-0.5 text-[#d8d9da]">{savedAt(rule.updated_at_ms)}</dd></div>
            </dl>
          </article>)}
          {query.isLoading && <div className="p-8 text-center text-xs text-[#7b7d80]">{t("Loading alert rules…", "Đang tải rule cảnh báo…")}</div>}
          {query.isError && <div role="alert" className="p-6 text-center text-xs text-[#f2495c]">{t("Could not load alert rules.", "Không thể tải rule cảnh báo.")}</div>}
          {!query.isLoading && !query.isError && !query.data?.items?.length && <div className="p-8 text-center text-xs text-[#7b7d80]">{t("No alert rules yet.", "Chưa có rule cảnh báo.")}</div>}
        </div>
      </Panel>

      {draft && <Panel title={draft.id ? t("Edit rule", "Sửa rule") : t("New alert rule", "Rule cảnh báo mới")} subtitle={t("Select a User, Service, or API scope. Empty selections apply to all in that scope.", "Chọn phạm vi User, Service hoặc API. Bỏ trống lựa chọn cụ thể để áp dụng cho tất cả trong phạm vi đó.")} action={<button aria-label={t("Close editor", "Đóng trình chỉnh sửa")} className="button-secondary px-2" onClick={() => setDraft(null)}><X size={14}/></button>}>
        <div className="space-y-3 p-3">
          <label className="block text-xs">{t("Rule name", "Tên rule")}<input className={input} value={draft.name} onChange={event => patch(rule => ({ ...rule, name: event.target.value }))}/></label>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs">{t("Severity", "Mức độ")}<select className={input} value={draft.severity} onChange={event => patch(rule => ({ ...rule, severity: event.target.value }))}><option value="info">info</option><option value="warning">warning</option><option value="critical">critical</option></select></label>
            <label className="text-xs">{t("Cooldown (minutes)", "Thời gian chờ (phút)")}<input type="number" min={1} max={10080} className={input} value={draft.cooldown_minutes} onChange={event => patch(rule => ({ ...rule, cooldown_minutes: Number(event.target.value) }))}/></label>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs">{t("Scope", "Phạm vi")}<select className={input} value={scope} onChange={event => updateScope(event.target.value as Scope)}><option value="any">{t("Any change", "Mọi thay đổi")}</option><option value="user">{t("User", "User")}</option><option value="service">{t("Service", "Service")}</option><option value="api">{t("API / Operation", "API / Operation")}</option></select></label>
            <label className="text-xs">{t("Change state", "Trạng thái thay đổi")}<select className={input} value={draft.condition.state || "any"} onChange={event => updateCondition("state", event.target.value)}><option value="any">{t("Any state", "Mọi trạng thái")}</option><option value="watch">Watch</option><option value="needs_attention">Needs attention</option><option value="critical">Critical</option></select></label>
          </div>

          {(scope === "service" || scope === "api") && <label className="block text-xs">{t("Service", "Service")}<select className={input} value={scope === "api" ? selectedService : draft.condition.service} onChange={event => {
            const value = event.target.value;
            setSelectedService(value);
            updateCondition("service", value);
            if (scope === "api") updateCondition("operation", "");
          }}><option value="">{t("All services", "Mọi Service")}</option>{serviceNames.map(name => <option key={name} value={name}>{name}</option>)}{draft.condition.service && !serviceNames.includes(draft.condition.service) && <option value={draft.condition.service}>{draft.condition.service}</option>}</select>{services.isError && <span className="mt-1 block text-[10px] text-[#f2495c]">{t("Service list unavailable; saved scope is preserved.", "Không tải được danh sách Service; phạm vi đã lưu vẫn được giữ.")}</span>}</label>}
          {scope === "user" && <label className="block text-xs">{t("User / account", "User / tài khoản")}<select className={input} value={draft.condition.principal} onChange={event => updateCondition("principal", event.target.value)}><option value="">{t("All users", "Mọi User")}</option>{userNames.map(name => <option key={name} value={name}>{name}</option>)}{draft.condition.principal && !userNames.includes(draft.condition.principal) && <option value={draft.condition.principal}>{draft.condition.principal}</option>}</select>{users.isError && <span className="mt-1 block text-[10px] text-[#f2495c]">{t("User list unavailable; saved scope is preserved.", "Không tải được danh sách User; phạm vi đã lưu vẫn được giữ.")}</span>}</label>}
          {scope === "api" && <label className="block text-xs">{t("API / operation", "API / Operation")}<select className={input} value={draft.condition.operation} disabled={!selectedService} onChange={event => updateCondition("operation", event.target.value)}><option value="">{selectedService ? t("All APIs for this service", "Mọi API của Service này") : t("Select a Service first", "Chọn Service trước")}</option>{apiNames.map(name => <option key={name} value={name}>{name}</option>)}{draft.condition.operation && !apiNames.includes(draft.condition.operation) && <option value={draft.condition.operation}>{draft.condition.operation}</option>}</select>{apis.isLoading && <span className="mt-1 block text-[10px] text-[#7b7d80]">{t("Loading APIs…", "Đang tải API…")}</span>}{apis.isError && <span className="mt-1 block text-[10px] text-[#f2495c]">{t("API list unavailable; saved scope is preserved.", "Không tải được danh sách API; phạm vi đã lưu vẫn được giữ.")}</span>}</label>}
          <label className="block text-xs">{t("Change types", "Loại thay đổi")}<select multiple className="toolbar-control h-24 w-full px-2 text-xs" value={draft.condition.change_types} onChange={event => updateCondition("change_types", Array.from(event.target.selectedOptions).map(option => option.value))}>{types.map(type => <option key={type} value={type}>{type}</option>)}</select><span className="mt-1 block text-[10px] text-[#7b7d80]">{t("Leave none selected to include every change type.", "Bỏ chọn tất cả để áp dụng mọi loại thay đổi.")}</span></label>
          <div className="grid grid-cols-[1fr_76px] gap-2"><label className="text-xs">{t("Metric threshold", "Ngưỡng chỉ số")}<input className={input} placeholder="e.g. error_rate" value={draft.condition.metric} onChange={event => updateCondition("metric", event.target.value)}/></label><label className="text-xs">{t("Value", "Giá trị")}<input className={input} placeholder="> 10" value={draft.condition.threshold} onChange={event => updateCondition("threshold", event.target.value)}/></label></div>
          <label className="block text-xs">{t("Destination", "Nơi nhận")}<div className="mt-1 grid grid-cols-[110px_1fr] gap-2"><select className={input} value={draft.destinations[0]?.type || "webhook"} onChange={event => patch(rule => ({ ...rule, destinations: [{ type: event.target.value, target: rule.destinations[0]?.target || "" }] }))}><option value="webhook">Webhook</option><option value="telegram">Telegram</option></select><div className="relative"><Webhook size={13} className="absolute left-2 top-3 text-[#7b7d80]"/><input className={`${input} pl-7`} placeholder={draft.destinations[0]?.type === "telegram" ? "Telegram chat ID" : "https://alerts.example/webhook"} value={draft.destinations[0]?.target || ""} onChange={event => patch(rule => ({ ...rule, destinations: [{ type: rule.destinations[0]?.type || "webhook", target: event.target.value }] }))}/></div></div></label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.enabled} onChange={event => patch(rule => ({ ...rule, enabled: event.target.checked }))}/>{t("Enabled", "Đang bật")}</label>
          {save.isError && <div role="alert" className="text-xs text-[#f2495c]">{t("Could not save this alert rule.", "Không thể lưu rule cảnh báo này.")}</div>}
          {scope === "api" && (!selectedService || !draft.condition.operation) && <p className="text-[10px] text-[#ff9830]">{t("Choose a Service and API operation to save an API-scoped rule.", "Chọn Service và API operation để lưu rule theo phạm vi API.")}</p>}
          <div className="grid grid-cols-2 gap-2"><button disabled={!draft.name.trim() || save.isPending || (scope === "api" && (!selectedService || !draft.condition.operation))} onClick={() => save.mutate(draft)} className="button-primary inline-flex h-9 items-center justify-center gap-2"><Save size={14}/>{draft.id ? t("Save changes", "Lưu thay đổi") : t("Create alert rule", "Tạo rule cảnh báo")}</button><button disabled={save.isPending} onClick={() => setDraft(null)} className="button-secondary h-9">{t("Cancel", "Hủy")}</button></div>
        </div>
      </Panel>}
    </div>

    <Panel className="mt-4" title={t("Delivery history", "Lịch sử gửi cảnh báo")} action={<button className="button-secondary inline-flex items-center gap-1" onClick={() => retry.mutate()}><RefreshCw size={12}/>{t("Retry pending", "Thử gửi lại")}</button>}>
      <div className="divide-y divide-[#2a2d30]">{(deliveries.data?.items || []).slice(0, 10).map(item => <div key={item.delivery_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[11px]"><div className="min-w-0"><span className="font-mono text-[#a7a9ab]">{item.destination_type} · {item.destination_target}</span>{item.change_summary && <p className="mt-1 truncate text-[#d8d9da]">{item.change_summary}</p>}</div><div className="flex shrink-0 items-center gap-2"><span className={item.status === "delivered" ? "text-[#73bf69]" : item.status === "failed" ? "text-[#f2495c]" : "text-[#ff9830]"}>{item.status} · {item.attempts} {t("attempts", "lần thử")} {item.response_code ? `· HTTP ${item.response_code}` : ""}</span>{item.change_id && <Link to={`/changes/${encodeURIComponent(String(item.change_id))}`} className="button-secondary">{t("View change", "Xem thay đổi")}</Link>}</div></div>)}{!deliveries.data?.items?.length && <div className="p-6 text-center text-xs text-[#7b7d80]">{t("No deliveries yet.", "Chưa có lần gửi nào.")}</div>}</div>
    </Panel>
  </Page>;
}

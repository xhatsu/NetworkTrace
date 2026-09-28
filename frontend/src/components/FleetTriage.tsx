import { useState } from "react";
import { EntityLink } from "./EntityLink";
import { n, Panel } from "../components";
import { useI18n } from "../i18n";

export type FleetService = {
  name: string;
  environment?: string;
  anomaly_status?: string;
  total_requests?: number;
  rps?: number;
  error_rate?: number;
  p95_latency?: number;
};

export function FleetTriage({ services, search }: { services: FleetService[]; search: string }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [sort, setSort] = useState("priority");
  const [page, setPage] = useState(0);
  const anomalyCount = services.filter((service) => service.anomaly_status === "abnormal").length;
  const errorCount = services.filter((service) => Number(service.error_rate) > 0).length;
  const rows = services.filter((service) => service.name.toLowerCase().includes(query.trim().toLowerCase()))
    .filter((service) => scope === "anomalies" ? service.anomaly_status === "abnormal" : scope === "errors" ? Number(service.error_rate) > 0 : true)
    .sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "traffic") return Number(b.rps || 0) - Number(a.rps || 0) || a.name.localeCompare(b.name);
      if (sort === "latency") return Number(b.p95_latency || 0) - Number(a.p95_latency || 0) || a.name.localeCompare(b.name);
      return (sort === "priority" ? Number(b.anomaly_status === "abnormal") - Number(a.anomaly_status === "abnormal") : 0)
        || Number(b.error_rate || 0) - Number(a.error_rate || 0)
        || Number(b.rps || 0) - Number(a.rps || 0) || a.name.localeCompare(b.name);
    });
  const lastPage = Math.max(0, Math.ceil(rows.length / 10) - 1);
  const currentPage = Math.min(page, lastPage);
  const visible = rows.slice(currentPage * 10, currentPage * 10 + 10);
  const metric = (value: number | undefined, digits: number, suffix = "") => value != null && Number.isFinite(value) ? `${n(value, digits)}${suffix}` : "—";

  return <Panel title={t("Service fleet triage", "Ưu tiên xử lý Service")} subtitle={t("Open anomalies first, then error rate and traffic. Metrics cover the selected time window.", "Ưu tiên bất thường đang mở, sau đó tỷ lệ lỗi và lưu lượng. Chỉ số theo khoảng thời gian đã chọn.")}>
    <div className="flex flex-wrap items-center gap-2 border-b border-[#2a2d30] p-3">
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("Service scope", "Phạm vi Service")}>
        {[
          ["all", t("All services", "Tất cả Service"), services.length],
          ["anomalies", t("Open anomalies", "Bất thường đang mở"), anomalyCount],
          ["errors", t("With errors", "Có lỗi"), errorCount],
        ].map(([value, label, count]) => <button key={value} type="button" aria-pressed={scope === value} onClick={() => { setScope(String(value)); setPage(0); }} className={`rounded border px-2.5 py-1.5 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#5794f2] ${scope === value ? "border-[#5794f2] bg-[#5794f2]/10 text-[#5794f2]" : "border-[#34373b] text-[#a7a9ab] hover:text-[#d8d9da]"}`}>{label} <span className="ml-1 font-mono">{count}</span></button>)}
      </div>
      <input aria-label={t("Search fleet services", "Tìm Service trong danh sách")} placeholder={t("Search service…", "Tìm Service…")} value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} className="min-w-0 flex-1 rounded border border-[#34373b] bg-[#181b1f] px-3 py-1.5 text-xs text-[#d8d9da] sm:ml-auto" />
      <select aria-label={t("Sort fleet services", "Sắp xếp Service")} value={sort} onChange={(event) => { setSort(event.target.value); setPage(0); }} className="max-w-full rounded border border-[#34373b] bg-[#181b1f] px-2 py-1.5 text-xs text-[#d8d9da]">
        <option value="priority">{t("Priority: anomaly → errors → TPS", "Ưu tiên: bất thường → lỗi → TPS")}</option>
        <option value="errors">{t("Error rate: highest first", "Tỷ lệ lỗi: cao nhất trước")}</option>
        <option value="traffic">{t("TPS: highest first", "TPS: cao nhất trước")}</option>
        <option value="latency">{t("Max bucket P95: highest first", "P95 bucket lớn nhất: cao nhất trước")}</option>
        <option value="name">{t("Service: A–Z", "Service: A–Z")}</option>
      </select>
    </div>
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-xs">
        <caption className="sr-only">{t("Observed service metrics; no anomaly does not imply healthy or available.", "Chỉ số Service đã quan sát; không có bất thường không đồng nghĩa hoạt động tốt hay sẵn sàng.")}</caption>
        <thead><tr className="border-b border-[#2a2d30]">
          {[t("Service"), t("Signal", "Tín hiệu"), t("Requests"), t("Avg TPS", "TPS TB"), t("Error rate"), t("Max bucket P95", "P95 bucket lớn nhất")].map((label, index) => <th scope="col" key={label} className={`table-head px-3 py-2 ${index > 1 ? "text-right" : ""}`}>{label}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-[#2a2d30]">{visible.map((service) => <tr key={service.name} className="hover:bg-[#181b1f]">
          <td className="max-w-[300px] px-3 py-2.5"><EntityLink entity={{ kind: "service", name: service.name }} search={search} className="block truncate font-semibold text-[#d8d9da] hover:text-[#5794f2]">{service.name}</EntityLink><span className="text-[10px] text-[#a7a9ab]">{service.environment || "—"}</span></td>
          <td className="px-3 py-2"><span className={service.anomaly_status === "abnormal" ? "text-[#ff9830]" : "text-[#a7a9ab]"}>{service.anomaly_status === "abnormal" ? t("Open anomaly", "Bất thường đang mở") : service.total_requests === 0 ? t("No window traffic", "Không có lưu lượng") : service.anomaly_status === "normal" ? t("No open anomaly", "Không có bất thường mở") : t("Unknown", "Chưa xác định")}</span></td>
          <td className="px-3 py-2 text-right font-mono tabular-nums">{metric(service.total_requests, 0)}</td>
          <td className="px-3 py-2 text-right font-mono tabular-nums text-[#5794f2]">{metric(service.rps, 2)}</td>
          <td className={`px-3 py-2 text-right font-mono tabular-nums ${Number(service.error_rate) > 0 ? "text-[#ff9830]" : "text-[#a7a9ab]"}`}>{metric(service.error_rate == null ? undefined : service.error_rate * 100, 2, "%")}</td>
          <td className="px-3 py-2 text-right font-mono tabular-nums">{metric(service.p95_latency, 0, " ms")}</td>
        </tr>)}</tbody>
      </table>
      {!rows.length && <div className="p-8 text-center text-xs text-[#a7a9ab]">{t("No services match these filters.", "Không có Service phù hợp bộ lọc.")}</div>}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#2a2d30] px-3 py-2 text-[11px] text-[#a7a9ab]">
      <span aria-live="polite">{rows.length ? currentPage * 10 + 1 : 0}–{Math.min((currentPage + 1) * 10, rows.length)} / {rows.length} {t("matching services", "Service phù hợp")} · {services.length} {t("loaded · cap 500", "đã tải · giới hạn 500")}</span>
      <div className="flex items-center gap-2"><button className="btn disabled:opacity-40" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t("Previous", "Trước")}</button><span>{currentPage + 1} / {lastPage + 1}</span><button className="btn disabled:opacity-40" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>{t("Next", "Tiếp")}</button></div>
    </div>
  </Panel>;
}

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, queryString } from "../api";
import { chartTooltip, n, Panel } from "../components";
import { EntityLink } from "./EntityLink";
import type { Episode } from "./EpisodePrimitives";
import { useI18n } from "../i18n";
import type { Filters, SeriesPoint } from "../types";

type OperationCount = { value: string; requests: number };
type Metric = "tps" | "p95_ms" | "http_5xx_rate";

const COMPARISON_MS = 60 * 60_000;

function metricForEpisode(episode: Episode): Metric {
  const labels = episode.highlights.map((item) => item.label.toLowerCase()).join(" ");
  const types = (episode.signals || []).map((item) => item.type.toLowerCase()).join(" ");
  if (/latency|p95|duration/.test(labels) || /latency/.test(types)) return "p95_ms";
  if (/error|5xx|failure/.test(labels) || /error_rate/.test(types)) return "http_5xx_rate";
  return "tps";
}

function formatClock(value: number, timezone: string) {
  try {
    return new Intl.DateTimeFormat([], {
      hour: "2-digit", minute: "2-digit", ...(timezone === "local" ? {} : { timeZone: timezone }),
    }).format(new Date(value));
  } catch {
    return new Date(value).toLocaleTimeString();
  }
}

function operationParts(value: string) {
  const separator = value.indexOf("→");
  return separator < 0 ? { service: "", operation: value } : {
    service: value.slice(0, separator), operation: value.slice(separator + 1),
  };
}

export function ChangeVisualEvidence({ episode, filters }: { episode: Episode; filters: Filters }) {
  const { t } = useI18n();
  const pivot = episode.started_at;
  const start = pivot - COMPARISON_MS;
  const end = pivot + COMPARISON_MS;
  const isUser = episode.subject.type === "user";
  const subject = episode.subject.name;
  const service = episode.context.target || (isUser ? undefined : subject);
  const operation = episode.context.operation || undefined;
  const metric = metricForEpisode(episode);
  const metricLabel = metric === "p95_ms" ? "P95 latency" : metric === "http_5xx_rate" ? "HTTP 5xx" : "TPS";
  const observedPath = [episode.context.caller, service, operation].filter(Boolean).join(" → ");
  const commonFilters: Filters = { start: String(start), end: String(end), timezone: filters.timezone, comparison: "none" };
  const graphQuery = useQuery({
    queryKey: ["change-visual-series", episode.id, pivot, subject, service, operation],
    queryFn: () => api<{ items: SeriesPoint[] }>(`/api/v1/dashboard/series?${queryString(commonFilters, {
      account: isUser ? subject : undefined, service, operation,
    })}`),
    staleTime: 60_000,
  });
  const principalPath = `/api/v1/users/${encodeURIComponent(subject)}/operations`;
  const beforeQuery = useQuery({
    queryKey: ["change-access-before", episode.id, pivot, subject],
    queryFn: () => api<{ items: OperationCount[] }>(`${principalPath}?start=${start}&end=${pivot}`),
    enabled: isUser, staleTime: 60_000,
  });
  const afterQuery = useQuery({
    queryKey: ["change-access-after", episode.id, pivot, subject],
    queryFn: () => api<{ items: OperationCount[] }>(`${principalPath}?start=${pivot}&end=${end}`),
    enabled: isUser, staleTime: 60_000,
  });

  const chartPoints = (graphQuery.data?.items || []).map((point) => ({
    ...point,
    observed: metric === "http_5xx_rate" ? Number(point.http_5xx_rate || 0) * 100 : Number(point[metric] || 0),
    baseline: Number(point.baseline_rps ?? 0),
  }));
  const beforePoints = chartPoints.filter((point) => point.timestamp_ms < pivot);
  const afterPoints = chartPoints.filter((point) => point.timestamp_ms >= pivot);
  const formatMetric = (value: number) => metric === "p95_ms" ? `${n(value, 0)} ms` : metric === "http_5xx_rate" ? `${n(value, 1)}%` : `${n(value, 2)} TPS`;
  const mean = (points: typeof chartPoints) => points.length
    ? formatMetric(points.reduce((sum, point) => sum + point.observed, 0) / points.length)
    : t("No observed samples", "Chưa có mẫu quan sát");

  const beforeMap = new Map((beforeQuery.data?.items || []).map((item) => [item.value, Number(item.requests || 0)]));
  const afterMap = new Map((afterQuery.data?.items || []).map((item) => [item.value, Number(item.requests || 0)]));
  const selectedKey = service && operation ? `${service}→${operation}` : "";
  const sortedKeys = [...new Set([...beforeMap.keys(), ...afterMap.keys()])].sort((left, right) =>
    Number(right === selectedKey) - Number(left === selectedKey)
    || ((afterMap.get(right) || 0) - (beforeMap.get(right) || 0)) - ((afterMap.get(left) || 0) - (beforeMap.get(left) || 0)),
  );
  const visibleKeys = sortedKeys.slice(0, 8);
  const maxRequests = Math.max(1, ...visibleKeys.flatMap((key) => [beforeMap.get(key) || 0, afterMap.get(key) || 0]));

  return <div className="mt-4 grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
    <Panel title={t("Change in context", "Biến động quanh thời điểm thay đổi")}
      subtitle={`${metricLabel} · ${t("one hour before and after", "một giờ trước và sau")}`}
      action={<span className="font-mono text-[11px] text-[#a7a9ab]">{filters.timezone}</span>}>
      <div className="grid grid-cols-2 border-b border-[#2a2d30] text-xs">
        <div className="border-r border-[#2a2d30] px-3 py-2"><div className="text-[10px] uppercase text-[#a7a9ab]">{t("Before", "Trước")}</div><div className="mt-1 font-mono text-[#d8d9da]">{mean(beforePoints)}</div></div>
        <div className="px-3 py-2"><div className="text-[10px] uppercase text-[#a7a9ab]">{t("After", "Sau")}</div><div className="mt-1 font-mono text-[#56b9a8]">{mean(afterPoints)}</div></div>
      </div>
      {graphQuery.isLoading ? <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("Loading…", "Đang tải…")}</div>
        : graphQuery.isError ? <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("Metric series unavailable", "Chưa có chuỗi metric")}</div>
          : chartPoints.length ? <div className="h-52 px-2 py-2" role="img" aria-label={`${metricLabel}: ${mean(beforePoints)} ${t("Before", "Trước")}, ${mean(afterPoints)} ${t("After", "Sau")}`}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={chartPoints} margin={{ top: 6, right: 12, bottom: 2, left: 0 }}>
              <CartesianGrid stroke="#303236" vertical={false} />
              <XAxis dataKey="timestamp_ms" type="number" domain={[start, end]} tickFormatter={(value) => formatClock(Number(value), filters.timezone)} tick={{ fill: "#a7a9ab", fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={36} />
              <YAxis width={54} domain={[0, "auto"]} tick={{ fill: "#a7a9ab", fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(value) => metric === "http_5xx_rate" ? `${n(value, 0)}%` : n(value, metric === "tps" ? 1 : 0)} />
              <Tooltip {...chartTooltip} labelFormatter={(value) => formatClock(Number(value), filters.timezone)} formatter={(value: unknown, name: unknown) => [formatMetric(Number(value)), String(name)]} />
              <ReferenceLine x={pivot} stroke="#ff9830" strokeWidth={1.5} strokeDasharray="4 3" label={{ value: t("Change", "Thay đổi"), fill: "#ff9830", fontSize: 10, position: "insideTopRight" }} />
              <Line type="linear" dataKey="observed" name={metricLabel} stroke="#5794f2" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
              {metric === "tps" && <Line type="linear" dataKey="baseline" name="Baseline" stroke="#a7a9ab" strokeDasharray="4 4" dot={false} isAnimationActive={false} />}
            </LineChart></ResponsiveContainer>
          </div> : <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("No metric samples around this change", "Không có mẫu metric quanh thay đổi này")}</div>}
      {chartPoints.length > 0 && <div className="flex flex-wrap items-center gap-3 px-3 pb-2 text-[10px] text-[#a7a9ab]">
        <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-[#5794f2]" />{metricLabel}</span>
        {metric === "tps" && <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-[#a7a9ab]" />Baseline</span>}
        <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-[#ff9830]" />{t("Change started", "Bắt đầu thay đổi")}</span>
      </div>}
      <p className="border-t border-[#2a2d30] px-3 py-2 text-[10px] leading-4 text-[#a7a9ab]">
        {observedPath || subject} · {t("Observed buckets in equal one-hour windows; gaps mean no samples were recorded.", "Các bucket quan sát trong hai khoảng một giờ bằng nhau; khoảng trống nghĩa là không ghi nhận mẫu.")}
      </p>
    </Panel>

    {!isUser && <Panel className="h-full" title={t("Change scope", "Phạm vi thay đổi")}
      subtitle={t("The operational context affected by this change.", "Ngữ cảnh vận hành bị ảnh hưởng bởi thay đổi này.")}
      action={<span className="font-mono text-[11px] text-[#a7a9ab]">{episode.signal_count} {t("signals", "tín hiệu")}</span>}>
      <div className="grid gap-px border-b border-[#2a2d30] bg-[#2a2d30] sm:grid-cols-2">
        {[
          [t("Caller Service", "Caller Service"), episode.context.caller || t("Not recorded", "Không ghi nhận")],
          [t("Target Service", "Target Service"), service || t("Not recorded", "Không ghi nhận")],
          [t("API / Operation", "API / Operation"), operation || t("All operations", "Mọi operation")],
          [t("Subject", "Đối tượng"), subject],
          [t("Source IP", "IP nguồn"), episode.context.source_ip || t("Not available", "Không có")],
          [t("Duration", "Thời lượng"), (() => { const minutes = Math.max(0, Math.round((episode.last_seen_at - episode.started_at) / 60000)); return minutes < 1 ? t("Less than 1 min", "Dưới 1 phút") : minutes < 60 ? `${minutes} min` : `${(minutes / 60).toFixed(1)} h`; })()],
        ].map(([label, value]) => <div key={label} className="bg-[#111217] px-3 py-2.5"><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{label}</div><div className="mt-1 truncate font-mono text-[11px] text-[#d8d9da]">{value}</div></div>)}
      </div>
      <div className="px-3 py-2 text-[10px] leading-4 text-[#a7a9ab]">{t("This identifies where the change was observed. Open a related Trace to confirm the exact request chain.", "Thông tin này xác định nơi thay đổi được quan sát. Mở Trace liên quan để xác nhận chuỗi request chính xác.")}</div>
    </Panel>}
    {isUser && <Panel title={t("Access pattern: before → after", "Mẫu truy cập: trước → sau")}
      subtitle={t("Service → API requests in equal one-hour windows", "Số request theo Service → API trong hai khoảng một giờ bằng nhau")}
      action={<span className="font-mono text-[11px] text-[#a7a9ab]">{visibleKeys.length}/{sortedKeys.length}</span>}>
      <div className="border-b border-[#2a2d30] px-3 py-2 text-[11px] text-[#a7a9ab]">
        {episode.context.caller && <><span>{t("Caller Service")}: </span><EntityLink entity={{ kind: "service", name: episode.context.caller }} className="text-[#5794f2]">{episode.context.caller}</EntityLink><ArrowRight size={12} className="mx-1 inline" /></>}
        {service && <><EntityLink entity={{ kind: "service", name: service }} className="text-[#5794f2]">{service}</EntityLink>{operation && <ArrowRight size={12} className="mx-1 inline" />}</>}
        {operation && service && <EntityLink entity={{ kind: "api", service, operation }} className="break-all text-[#56b9a8]">{operation}</EntityLink>}
        <div className="mt-1">{t("Observed credential", "Credential quan sát")}: <EntityLink entity={{ kind: "user", principal: subject }} className="text-[#b877d9]">{subject}</EntityLink></div>
      </div>
      {beforeQuery.isLoading || afterQuery.isLoading ? <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("Loading…", "Đang tải…")}</div>
        : beforeQuery.isError || afterQuery.isError ? <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("Access comparison unavailable", "Chưa thể so sánh truy cập")}</div>
          : visibleKeys.length ? <div className="max-h-80 overflow-y-auto divide-y divide-[#2a2d30]">
            {visibleKeys.map((key) => {
              const before = beforeMap.get(key) || 0;
              const after = afterMap.get(key) || 0;
              const { service: target, operation: apiName } = operationParts(key);
              return <div key={key} className={`px-3 py-2 ${key === selectedKey ? "bg-[#56b9a8]/10" : ""}`}>
                <div className="flex items-start justify-between gap-2 text-[11px]">
                  <span className="min-w-0 break-all">{target && <><EntityLink entity={{ kind: "service", name: target }} className="text-[#5794f2]">{target}</EntityLink><span className="px-1 text-[#a7a9ab]">→</span></>}{target ? <EntityLink entity={{ kind: "api", service: target, operation: apiName }} className="text-[#56b9a8]">{apiName}</EntityLink> : apiName}</span>
                  {before === 0 && after > 0 && <span className="shrink-0 border border-[#ff9830]/50 px-1.5 py-0.5 text-[10px] text-[#ff9830]">{t("New in window", "Mới trong khoảng")}</span>}
                </div>
                <div className="mt-1 grid grid-cols-[38px_minmax(0,1fr)_40px] items-center gap-2 text-[10px] text-[#a7a9ab]"><span>{t("Before", "Trước")}</span><span className="block h-1.5 bg-[#181b1f]"><span className="block h-full bg-[#7b7d80]" style={{ width: `${before / maxRequests * 100}%` }} /></span><span className="text-right font-mono">{n(before, 0)}</span></div>
                <div className="mt-1 grid grid-cols-[38px_minmax(0,1fr)_40px] items-center gap-2 text-[10px] text-[#a7a9ab]"><span>{t("After", "Sau")}</span><span className="block h-1.5 bg-[#181b1f]"><span className="block h-full bg-[#56b9a8]" style={{ width: `${after / maxRequests * 100}%` }} /></span><span className="text-right font-mono">{n(after, 0)}</span></div>
              </div>;
            })}
          </div> : <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("No operation relationships observed in these windows", "Không có quan hệ API quan sát trong hai khoảng này")}</div>}
      <p className="border-t border-[#2a2d30] px-3 py-2 text-[10px] leading-4 text-[#a7a9ab]">
        {t("New in window means absent from the preceding hour, not first seen ever. Open a related Trace to confirm the exact request chain.", "Mới trong khoảng nghĩa là vắng mặt ở giờ trước đó, không khẳng định đây là lần đầu tiên. Mở Trace liên quan để xác nhận chuỗi request chính xác.")}
      </p>
    </Panel>}
  </div>;
}

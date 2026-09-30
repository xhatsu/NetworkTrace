import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, queryString } from "../api";
import { chartTooltip, n, Panel } from "../components";
import { SemanticAssessmentSummary, type Episode } from "./EpisodePrimitives";
import { useI18n } from "../i18n";
import type { Filters, SeriesPoint } from "../types";

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

export function ChangeVisualEvidence({ episode, filters }: { episode: Episode; filters: Filters }) {
  const { t } = useI18n();
  const pivot = Math.max(episode.started_at, ...(episode.signals || []).map((signal) => signal.detected_at));
  const start = pivot - COMPARISON_MS;
  const end = pivot + COMPARISON_MS;
  const isUser = episode.subject.type === "user";
  const subject = episode.subject.name;
  const service = episode.context.target || (isUser ? undefined : subject);
  const operation = episode.context.operation || undefined;
  const metric = metricForEpisode(episode);
  const detectorHighlight = episode.highlights.find((item) => {
    const label = item.label.toLowerCase();
    return metric === "p95_ms" ? /latency|p95|duration/.test(label)
      : metric === "http_5xx_rate" ? /error|5xx|failure/.test(label)
        : /tps|traffic|request/.test(label);
  });
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
  const chartPoints = (graphQuery.data?.items || []).map((point) => ({
    ...point,
    observed: metric === "http_5xx_rate" ? Number(point.http_5xx_rate || 0) * 100 : Number(point[metric] || 0),
    baseline: Number(point.baseline_rps ?? 0),
  }));
  const beforePoints = chartPoints.filter((point) => point.timestamp_ms >= start && point.timestamp_ms < pivot);
  const afterPoints = chartPoints.filter((point) => point.timestamp_ms >= pivot && point.timestamp_ms < end);
  const formatMetric = (value: number) => metric === "p95_ms" ? `${n(value, 0)} ms` : metric === "http_5xx_rate" ? `${n(value, 1)}%` : `${n(value, 2)} TPS`;
  const mean = (points: typeof chartPoints) => points.length
    ? formatMetric(points.reduce((sum, point) => sum + point.observed, 0) / points.length)
    : t("No observed samples", "Chưa có mẫu quan sát");
  const comparisonBefore = detectorHighlight?.before != null
    ? formatMetric(Number(detectorHighlight.before)) : mean(beforePoints);
  const comparisonAfter = detectorHighlight?.after != null
    ? formatMetric(Number(detectorHighlight.after)) : mean(afterPoints);

  return <div className="mt-4 grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
    <Panel title={t("Change in context", "Biến động quanh thời điểm thay đổi")}
      subtitle={`${metricLabel} · ${t("one hour before and after", "một giờ trước và sau")}`}
      action={<span className="font-mono text-[11px] text-[#a7a9ab]">{filters.timezone}</span>}>
      <div className="grid grid-cols-2 border-b border-[#2a2d30] text-xs">
        <div className="border-r border-[#2a2d30] px-3 py-2"><div className="text-[10px] uppercase text-[#a7a9ab]">{t("Baseline", "Baseline")}</div><div className="mt-1 font-mono text-[#d8d9da]">{comparisonBefore}</div></div>
        <div className="px-3 py-2"><div className="text-[10px] uppercase text-[#a7a9ab]">{t("Observed", "Quan sát được")}</div><div className="mt-1 font-mono text-[#56b9a8]">{comparisonAfter}</div></div>
      </div>
      {graphQuery.isLoading ? <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("Loading…", "Đang tải…")}</div>
        : graphQuery.isError ? <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("Metric series unavailable", "Chưa có chuỗi metric")}</div>
          : chartPoints.length ? <div className="h-52 px-2 py-2" role="img" aria-label={`${metricLabel}: ${comparisonBefore} ${t("Baseline", "Baseline")}, ${comparisonAfter} ${t("Observed", "Quan sát được")}`}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={chartPoints} margin={{ top: 6, right: 12, bottom: 2, left: 0 }}>
              <CartesianGrid stroke="#303236" vertical={false} />
              <XAxis dataKey="timestamp_ms" type="number" domain={[start, end]} tickFormatter={(value) => formatClock(Number(value), filters.timezone)} tick={{ fill: "#a7a9ab", fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={36} />
              <YAxis width={54} domain={[0, "auto"]} tick={{ fill: "#a7a9ab", fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(value) => metric === "http_5xx_rate" ? `${n(value, 0)}%` : n(value, metric === "tps" ? 1 : 0)} />
              <Tooltip {...chartTooltip} labelFormatter={(value) => formatClock(Number(value), filters.timezone)} formatter={(value: unknown, name: unknown) => [formatMetric(Number(value)), String(name)]} />
              <ReferenceLine x={pivot} stroke="#ff9830" strokeWidth={1.5} strokeDasharray="4 3" label={{ value: t("Latest signal", "Tín hiệu mới nhất"), fill: "#ff9830", fontSize: 10, position: "insideTopRight" }} />
              <Line type="linear" dataKey="observed" name={metricLabel} stroke="#5794f2" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
              {metric === "tps" && <Line type="linear" dataKey="baseline" name={t("Expected TPS", "TPS dự kiến")} stroke="#a7a9ab" strokeDasharray="4 4" dot={false} isAnimationActive={false} />}
            </LineChart></ResponsiveContainer>
          </div> : <div className="grid h-48 place-items-center text-xs text-[#a7a9ab]">{t("No metric samples around this change", "Không có mẫu metric quanh thay đổi này")}</div>}
      {chartPoints.length > 0 && <div className="flex flex-wrap items-center gap-3 px-3 pb-2 text-[10px] text-[#a7a9ab]">
        <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-[#5794f2]" />{metricLabel}</span>
        {metric === "tps" && <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-[#a7a9ab]" />{t("Current reference", "Tham chiếu hiện tại")}</span>}
        <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-[#ff9830]" />{t("Latest signal", "Tín hiệu mới nhất")}</span>
      </div>}
      <p className="border-t border-[#2a2d30] px-3 py-2 text-[10px] leading-4 text-[#a7a9ab]">
        {observedPath || subject} · {t("The values above match the saved detector comparison below. The chart shows one-minute buckets around the latest signal; service traffic detection uses five-minute windows.", "Các giá trị phía trên khớp với so sánh detector đã lưu bên dưới. Biểu đồ hiển thị bucket một phút quanh tín hiệu mới nhất; phát hiện lưu lượng Service dùng cửa sổ năm phút.")}
        {metric === "tps" && <> {t("The expected line uses the current learned/historical expectation or a fallback estimate; it is not the baseline saved at detection. TPS and RPS both mean requests per second here.", "Đường tham chiếu dùng Baseline hiện tại hoặc giá trị ước tính thay thế; không phải Baseline đã lưu lúc phát hiện. TPS và RPS ở đây đều là số request mỗi giây.")}</>}
      </p>
    </Panel>

    <SemanticAssessmentSummary episode={episode} full timezone={filters.timezone} />
  </div>;
}

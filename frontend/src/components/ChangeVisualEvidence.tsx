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
  const nowMs = Date.now();
  const rawPivot = Math.max(episode.started_at, ...(episode.signals || []).map((signal) => signal.detected_at));
  const pivot = Math.min(rawPivot || nowMs, nowMs);
  const start = pivot - COMPARISON_MS;
  const end = pivot + COMPARISON_MS;
  const chartEnd = Math.max(pivot + 60_000, Math.min(end, nowMs));
  const isUser = episode.subject.type === "user";
  const subject = episode.subject.name;
  const caller = episode.context.caller || undefined;
  const service = episode.context.target || (isUser ? undefined : subject);
  const operation = episode.context.operation || undefined;
  const metric = metricForEpisode(episode);
  const metricLabel = metric === "p95_ms" ? "P95 latency" : metric === "http_5xx_rate" ? "HTTP 5xx" : "TPS";
  const observedPath = [caller, service, operation].filter(Boolean).join(" → ");
  const commonFilters: Filters = { start: String(start), end: String(end), timezone: filters.timezone, comparison: "none" };
  const graphQuery = useQuery({
    queryKey: ["change-visual-series", episode.id, pivot, subject, service, operation, caller],
    queryFn: () => api<{ items: SeriesPoint[] }>(`/api/v1/dashboard/series?${queryString(commonFilters, {
      account: isUser ? subject : undefined, service, operation, caller,
    })}`),
    staleTime: 60_000,
  });

  const rawItems = graphQuery.data?.items || [];
  const itemsByMinute = new Map<number, SeriesPoint>();
  let fallbackBaseline = 0;
  for (const item of rawItems) {
    const minTs = Math.floor(item.timestamp_ms / 60_000) * 60_000;
    itemsByMinute.set(minTs, item);
    if (Number(item.baseline_rps) > 0 && fallbackBaseline === 0) {
      fallbackBaseline = Number(item.baseline_rps);
    }
  }

  const startMinute = Math.floor(start / 60_000) * 60_000;
  const endMinute = Math.max(startMinute + 60_000, Math.floor(chartEnd / 60_000) * 60_000);

  type ProcessedPoint = {
    timestamp_ms: number;
    observed: number | null;
    baseline: number;
    sample_count: number;
  };

  const chartPoints: ProcessedPoint[] = [];
  for (let m = startMinute; m <= endMinute; m += 60_000) {
    const item = itemsByMinute.get(m);
    let observed: number | null = null;
    let baseline = fallbackBaseline;
    let sampleCount = 0;

    if (item) {
      sampleCount = item.sample_count || 0;
      baseline = Number(item.baseline_rps ?? fallbackBaseline);
      if (metric === "http_5xx_rate") {
        observed = Number(item.http_5xx_rate || 0) * 100;
      } else if (metric === "p95_ms") {
        observed = sampleCount > 0 ? Number(item.p95_ms || 0) : null;
      } else {
        observed = Number(item.tps ?? item.rps ?? 0);
      }
    } else {
      if (metric === "http_5xx_rate") {
        observed = 0;
      } else if (metric === "p95_ms") {
        observed = null;
      } else {
        observed = 0;
      }
    }

    chartPoints.push({
      timestamp_ms: m,
      observed,
      baseline,
      sample_count: sampleCount,
    });
  }

  const beforePoints = chartPoints.filter((point) => point.timestamp_ms >= start && point.timestamp_ms < pivot);
  const afterPoints = chartPoints.filter((point) => point.timestamp_ms >= pivot && point.timestamp_ms <= end);
  const formatMetric = (value: number) =>
    metric === "p95_ms" ? `${n(value, 0)} ms` : metric === "http_5xx_rate" ? `${n(value, 1)}%` : `${n(value, 2)} TPS`;

  const mean = (points: ProcessedPoint[]) => {
    const valid = points.filter((point) => point.observed !== null);
    if (!valid.length) return t("No observed samples", "Chưa có mẫu quan sát");
    const avg = valid.reduce((sum, point) => sum + (point.observed as number), 0) / valid.length;
    return formatMetric(avg);
  };

  const comparisonBefore = mean(beforePoints);
  const comparisonAfter = mean(afterPoints);

  return <div className="mt-4 grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
    <Panel title={t("Change in context", "Biến động quanh thời điểm thay đổi")}
      subtitle={`${metricLabel} · ${t("one hour before and after", "một giờ trước và sau")}`}
      action={<span className="font-mono text-[11px] text-muted">{filters.timezone}</span>}>
      <div className="grid grid-cols-2 border-b border-line text-xs">
        <div className="border-r border-line px-3 py-2 bg-surface-2">
          <div className="text-[10px] uppercase text-muted">{t("1h Before (avg)", "1 giờ trước (TB)")}</div>
          <div className="mt-1 font-mono text-ink num">{comparisonBefore}</div>
        </div>
        <div className="px-3 py-2 bg-surface-2">
          <div className="text-[10px] uppercase text-muted">{t("After Signal (avg)", "Sau tín hiệu (TB)")}</div>
          <div className="mt-1 font-mono text-accent font-semibold num">{comparisonAfter}</div>
        </div>
      </div>
      {graphQuery.isLoading ? <div className="grid h-48 place-items-center text-xs text-muted">{t("Loading…", "Đang tải…")}</div>
        : graphQuery.isError ? <div className="grid h-48 place-items-center text-xs text-bad">{t("Metric series unavailable", "Chưa có chuỗi metric")}</div>
          : chartPoints.length ? <div className="h-52 px-2 py-2" role="img" aria-label={`${metricLabel}: ${comparisonBefore} ${t("1h Before", "1 giờ trước")}, ${comparisonAfter} ${t("After Signal", "Sau tín hiệu")}`}>
            <ResponsiveContainer width="100%" height="100%"><LineChart data={chartPoints} margin={{ top: 6, right: 12, bottom: 2, left: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="timestamp_ms" type="number" domain={[startMinute, endMinute]} tickFormatter={(value) => formatClock(Number(value), filters.timezone)} tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={36} />
              <YAxis width={54} domain={[0, "auto"]} tick={{ fill: "var(--muted)", fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(value) => metric === "http_5xx_rate" ? `${n(value, 0)}%` : n(value, metric === "tps" ? 1 : 0)} />
              <Tooltip {...chartTooltip} labelFormatter={(value) => formatClock(Number(value), filters.timezone)} formatter={(value: unknown, name: unknown) => [value != null ? formatMetric(Number(value)) : t("No requests", "Không có request"), String(name)]} />
              <ReferenceLine x={pivot} stroke="var(--warn)" strokeWidth={1.5} strokeDasharray="4 3" label={{ value: t("Latest signal", "Tín hiệu mới nhất"), fill: "var(--warn)", fontSize: 10, position: "insideTopRight" }} />
              <Line type="linear" dataKey="observed" name={metricLabel} stroke="var(--series-1)" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false} />
              {metric === "tps" && <Line type="linear" dataKey="baseline" name={t("Expected TPS", "TPS dự kiến")} stroke="var(--series-2)" strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />}
            </LineChart></ResponsiveContainer>
          </div> : <div className="grid h-48 place-items-center text-xs text-muted">{t("No metric samples around this change", "Không có mẫu metric quanh thay đổi này")}</div>}
      {chartPoints.length > 0 && <div className="flex flex-wrap items-center gap-3 px-3 pb-2 text-[10px] text-muted">
        <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-accent" />{metricLabel}</span>
        {metric === "tps" && <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-muted" />{t("Current reference", "Tham chiếu hiện tại")}</span>}
        <span className="inline-flex items-center gap-1"><span className="w-4 border-t-2 border-dashed border-warn" />{t("Latest signal", "Tín hiệu mới nhất")}</span>
      </div>}
      <p className="border-t border-line px-3 py-2 text-[10px] leading-4 text-muted">
        {observedPath || subject} · {t("Summary boxes and chart show one-minute buckets over the one-hour window before and after the latest signal; service traffic detection evaluates five-minute windows.", "Các ô tóm tắt và biểu đồ hiển thị bucket một phút trong khoảng một giờ trước và sau tín hiệu mới nhất; phát hiện lưu lượng Service đánh giá cửa sổ năm phút.")}
        {metric === "tps" && <> {t("The expected line uses the current learned/historical expectation or a fallback estimate; it is not the baseline saved at detection. TPS and RPS both mean requests per second here.", "Đường tham chiếu dùng Baseline hiện tại hoặc giá trị ước tính thay thế; không phải Baseline đã lưu lúc phát hiện. TPS và RPS ở đây đều là số request mỗi giây.")}</>}
      </p>
    </Panel>

    <SemanticAssessmentSummary episode={episode} full timezone={filters.timezone} />
  </div>;
}

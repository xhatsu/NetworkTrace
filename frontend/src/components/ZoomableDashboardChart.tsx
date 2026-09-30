import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useI18n } from "../i18n";

echarts.use([LineChart, DataZoomComponent, GridComponent, LegendComponent, ToolboxComponent, TooltipComponent, CanvasRenderer]);

type Point = { timestamp_ms: number; tps?: number; expected_tps?: number; baseline_rps?: number; http_4xx_rate?: number; http_5xx_rate?: number };

export function ZoomableDashboardChart({ data, timezone }: { data: Point[]; timezone: string }) {
  const { t } = useI18n();
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!rootRef.current || !data.length) return;
    const chart = echarts.init(rootRef.current, undefined, { renderer: "canvas" });
    const formatTime = (value: number) => {
      const options: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" };
      if (timezone !== "local") options.timeZone = timezone;
      return new Intl.DateTimeFormat([], options).format(new Date(value));
    };
    const labels = [t("Observed TPS"), t("Expected TPS"), "HTTP 4xx", "HTTP 5xx"];
    chart.setOption({
      animation: false,
      color: ["#5794f2", "#a7a9ab", "#ff9830", "#f2495c"],
      grid: { top: 24, right: 22, bottom: 72, left: 60 },
      legend: { top: 0, textStyle: { color: "#a7a9ab", fontSize: 11 } },
      tooltip: { trigger: "axis", backgroundColor: "#111217", borderColor: "#34373b", textStyle: { color: "#d8d9da", fontSize: 11 }, formatter: (items: Array<{ seriesName: string; value: [number, number] }>) => { const first = items[0]; return [`<strong>${formatTime(first.value[0])}</strong>`, ...items.map(item => `${item.seriesName}: ${item.seriesName.startsWith("HTTP") ? `${(item.value[1] * 100).toFixed(2)}%` : `${item.value[1].toFixed(3)} TPS`}`)].join("<br/>"); } },
      xAxis: { type: "time", axisLine: { lineStyle: { color: "#34373b" } }, axisTick: { show: false }, axisLabel: { color: "#a7a9ab", fontSize: 11, hideOverlap: true, formatter: (value: number) => formatTime(value) }, splitLine: { show: false } },
      yAxis: { type: "value", min: 0, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#a7a9ab", fontSize: 11 }, splitLine: { lineStyle: { color: "#303236" } } },
      dataZoom: [{ type: "inside", xAxisIndex: 0, filterMode: "none", zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: true }, { type: "slider", xAxisIndex: 0, filterMode: "none", height: 22, bottom: 24, borderColor: "#34373b", backgroundColor: "#181b1f", fillerColor: "rgba(87,148,242,.18)", handleStyle: { color: "#5794f2", borderColor: "#5794f2" }, textStyle: { color: "#a7a9ab", fontSize: 10 } }],
      toolbox: { right: 8, top: 0, itemSize: 13, iconStyle: { borderColor: "#a7a9ab" }, feature: { dataZoom: { yAxisIndex: "none", title: { zoom: t("Zoom"), back: t("Reset zoom") } }, restore: { title: t("Restore") } } },
      series: [
        { name: labels[0], type: "line", showSymbol: false, connectNulls: true, lineStyle: { width: 1.5 }, data: data.map(p => [p.timestamp_ms, Number(p.tps || 0)]) },
        { name: labels[1], type: "line", showSymbol: false, connectNulls: true, lineStyle: { width: 1.3, type: "dashed" }, data: data.map(p => [p.timestamp_ms, Number(p.expected_tps ?? p.baseline_rps ?? 0)]) },
        { name: labels[2], type: "line", showSymbol: false, connectNulls: true, lineStyle: { width: 1.3 }, data: data.map(p => [p.timestamp_ms, Number(p.http_4xx_rate || 0)]) },
        { name: labels[3], type: "line", showSymbol: false, connectNulls: true, lineStyle: { width: 1.3 }, data: data.map(p => [p.timestamp_ms, Number(p.http_5xx_rate || 0)]) },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [data, t, timezone]);
  if (!data.length) return <div className="grid h-72 place-items-center text-xs text-[#a7a9ab]">{t("No telemetry points in the selected window")}</div>;
  return <div ref={rootRef} className="h-[360px] w-full p-2" role="img" aria-label={t("Zoomable TPS and HTTP error rate chart", "Biểu đồ TPS và tỷ lệ lỗi HTTP có thể phóng to")} />;
}

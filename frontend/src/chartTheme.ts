import { getThemeTokens, type ThemeMode } from "./theme";

export interface ChartTokens {
  grid: string;
  axisLabel: string;
  axisLine: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  tooltipShadow: string;
  series1: string;
  series2: string;
  series3: string;
  http2xx: string;
  http3xx: string;
  http4xx: string;
  http5xx: string;
  p95: string;
  lineWidth: number;
  areaTop: string;
  areaBottom: string;
}

export function chartTokens(theme?: ThemeMode): ChartTokens {
  const tokens = getThemeTokens(theme);

  return {
    grid: tokens.chart.grid,
    axisLabel: tokens.chart.axisLabel,
    axisLine: tokens.chart.axisLine,
    tooltipBg: tokens.chart.tooltipBg,
    tooltipBorder: tokens.chart.tooltipBorder,
    tooltipText: tokens.chart.tooltipText,
    tooltipShadow: "var(--shadow-pop)",
    series1: tokens.chart.tps,
    series2: tokens.chart.baseline,
    series3: tokens.blue,
    http2xx: tokens.green,
    http3xx: tokens.blue,
    http4xx: tokens.chart.http4xx,
    http5xx: tokens.chart.http5xx,
    p95: tokens.chart.p95,
    lineWidth: 1.5,
    areaTop: tokens.chart.areaTop,
    areaBottom: tokens.chart.areaBottom,
  };
}

export function getChartTooltipStyle(theme: ThemeMode = "dark") {
  const ct = chartTokens(theme);
  return {
    contentStyle: {
      backgroundColor: ct.tooltipBg,
      borderColor: ct.tooltipBorder,
      borderWidth: "1px",
      borderStyle: "solid",
      borderRadius: "8px",
      boxShadow: ct.tooltipShadow,
      fontSize: "12px",
      padding: "8px 12px",
    },
    labelStyle: {
      color: ct.tooltipText,
      fontWeight: 600,
      marginBottom: "4px",
    },
    itemStyle: {
      color: ct.tooltipText,
      padding: "2px 0",
    },
  };
}

export function getChartAxisStyle(theme: ThemeMode = "dark") {
  const ct = chartTokens(theme);
  return {
    tick: {
      fill: ct.axisLabel,
      fontSize: 11,
    },
    axisLine: {
      stroke: ct.axisLine,
    },
  };
}

export function getChartGridStyle(theme: ThemeMode = "dark") {
  const ct = chartTokens(theme);
  return {
    stroke: ct.grid,
  };
}

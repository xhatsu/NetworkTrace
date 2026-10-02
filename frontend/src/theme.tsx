import React, { createContext, useContext, useEffect, useState, useMemo } from "react";

export type ThemeMode = "dark" | "light";

export interface ColorTokens {
  canvas: string;
  sidebar: string;
  structure: string;
  surface: string;
  surfaceRaised: string;
  surfaceMuted: string;
  surfaceSelected: string;
  surfaceHover: string;
  border: string;
  borderStrong: string;
  borderFocus: string;
  divider: string;

  text: string;
  textSecondary: string;
  textMuted: string;
  textSubtle: string;

  accent: string;
  blue: string;
  green: string;
  orange: string;
  red: string;
  yellow: string;
  purple: string;
  teal: string;

  chart: {
    grid: string;
    axisLabel: string;
    axisLine: string;
    tooltipBg: string;
    tooltipBorder: string;
    tooltipText: string;
    tps: string;
    baseline: string;
    http4xx: string;
    http5xx: string;
    p95: string;
    areaTop: string;
    areaBottom: string;
  };

  entity: {
    service: string;
    credential: string;
    api: string;
    ip: string;
    caller: string;
  };
}

export interface ThemeContextValue {
  theme: ThemeMode;
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
}

export const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  toggleTheme: () => {},
  setTheme: () => {},
});

export const useTheme = () => useContext(ThemeContext);

export function initialTheme(): ThemeMode {
  try {
    return window.localStorage.getItem("tracescope-theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(initialTheme);

  const toggleTheme = () => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"));
  };

  const setTheme = (next: ThemeMode) => {
    setThemeState(next);
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.setAttribute("content", readCssVar("--page", ""));
    try {
      window.localStorage.setItem("tracescope-theme", theme);
    } catch {
      // storage unavailable
    }
  }, [theme]);

  const value = useMemo(() => ({ theme, toggleTheme, setTheme }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

const tokenCache: Record<ThemeMode, ColorTokens | null> = {
  ["dark"]: null,
  light: null,
};

function readCssVar(varName: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const val = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  return val || fallback;
}

export function getThemeTokens(theme?: ThemeMode): ColorTokens {
  const currentAttr =
    typeof document !== "undefined"
      ? document.documentElement.getAttribute("data-theme")
      : null;
  const activeTheme: ThemeMode = currentAttr === "light" ? "light" : "dark";
  const targetTheme: ThemeMode = theme || activeTheme;

  // If the target theme is currently active on document, compute fresh tokens and update cache
  if (typeof document !== "undefined" && targetTheme === activeTheme) {
    const page = readCssVar("--page", "var(--page)");
    const bg = readCssVar("--bg", "var(--bg)");
    const structure = readCssVar("--structure", "var(--structure)");
    const frame = readCssVar("--frame", "var(--frame)");
    const surface = readCssVar("--surface", "var(--surface)");
    const surface2 = readCssVar("--surface-2", "var(--surface-2)");
    const border = readCssVar("--border", "var(--border)");
    const borderStrong = readCssVar("--border-strong", "var(--border-strong)");
    const text = readCssVar("--text", "var(--text)");
    const muted = readCssVar("--muted", "var(--muted)");
    const faint = readCssVar("--faint", "var(--faint)");

    const accent = readCssVar("--accent", "var(--accent)");
    const accentSoft = readCssVar("--accent-soft", "var(--accent-soft)");

    const good = readCssVar("--good", "var(--good)");
    const bad = readCssVar("--bad", "var(--bad)");
    const warn = readCssVar("--warn", "var(--warn)");
    const info = readCssVar("--info", "var(--info)");

    const entityService = readCssVar("--entity-service", "var(--entity-service)");
    const entityUser = readCssVar("--entity-user", "var(--entity-user)");
    const entityApi = readCssVar("--entity-api", "var(--entity-api)");
    const entityIp = readCssVar("--entity-ip", "var(--entity-ip)");

    const grid = readCssVar("--grid", "var(--grid)");
    const hover = readCssVar("--hover", "var(--hover)");

    const tokens: ColorTokens = {
      canvas: page,
      sidebar: frame,
      structure,
      surface,
      surfaceRaised: surface2,
      surfaceMuted: surface2,
      surfaceSelected: accentSoft,
      surfaceHover: hover,
      border,
      borderStrong,
      borderFocus: accent,
      divider: border,

      text,
      textSecondary: muted,
      textMuted: muted,
      textSubtle: faint,

      accent,
      blue: info,
      green: good,
      orange: warn,
      red: bad,
      yellow: warn,
      purple: accent,
      teal: entityApi,

      chart: {
        grid,
        axisLabel: muted,
        axisLine: border,
        tooltipBg: surface,
        tooltipBorder: borderStrong,
        tooltipText: text,
        tps: accent,
        baseline: muted,
        http4xx: warn,
        http5xx: bad,
        p95: entityApi,
        areaTop: readCssVar("--chart-area-top", "var(--chart-area-top)"),
        areaBottom: readCssVar("--chart-area-bottom", "var(--chart-area-bottom)"),
      },

      entity: {
        service: entityService,
        credential: entityUser,
        api: entityApi,
        ip: entityIp,
        caller: entityService,
      },
    };
    tokenCache[targetTheme] = tokens;
    return tokens;
  }

  // If cache exists for targetTheme, return it
  if (tokenCache[targetTheme]) {
    return tokenCache[targetTheme]!;
  }

  // Fallback defaults if targetTheme wasn't rendered yet
  return {
    canvas: "var(--page)",
    sidebar: "var(--frame)",
    structure: "var(--structure)",
    surface: "var(--surface)",
    surfaceRaised: "var(--surface-2)",
    surfaceMuted: "var(--surface-2)",
    surfaceSelected: "var(--accent-soft)",
    surfaceHover: "var(--hover)",
    border: "var(--border)",
    borderStrong: "var(--border-strong)",
    borderFocus: "var(--accent)",
    divider: "var(--border)",
    text: "var(--text)",
    textSecondary: "var(--muted)",
    textMuted: "var(--muted)",
    textSubtle: "var(--faint)",
    accent: "var(--accent)",
    blue: "var(--info)",
    green: "var(--good)",
    orange: "var(--warn)",
    red: "var(--bad)",
    yellow: "var(--warn)",
    purple: "var(--accent)",
    teal: "var(--entity-api)",
    chart: {
      grid: "var(--grid)",
      axisLabel: "var(--muted)",
      axisLine: "var(--border)",
      tooltipBg: "var(--surface)",
      tooltipBorder: "var(--border-strong)",
      tooltipText: "var(--text)",
      tps: "var(--accent)",
      baseline: "var(--muted)",
      http4xx: "var(--warn)",
      http5xx: "var(--bad)",
      p95: "var(--entity-api)",
      areaTop: "var(--chart-area-top)",
      areaBottom: "var(--chart-area-bottom)",
    },
    entity: {
      service: "var(--entity-service)",
      credential: "var(--entity-user)",
      api: "var(--entity-api)",
      ip: "var(--entity-ip)",
      caller: "var(--entity-service)",
    },
  };
}

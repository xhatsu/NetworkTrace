import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useFilters } from "../App";
import type { Filters } from "../types";

// Data model of the Users / APIs workspace. Every list comes from one endpoint
// (/api/v1/relationships, the worker's five-minute IP rollup), so the numbers on
// a page agree with each other.

export type Facet = "caller" | "principal" | "service" | "api" | "ip";
export type RelState = "new" | "active" | "silent";

export type RelRow = {
  name: string;
  service?: string;
  requests: number;
  errors: number;
  error_rate: number;
  tps: number;
  p95_ms: number;
  request_bytes: number;
  response_bytes: number;
  first_seen_ms: number | null;
  last_seen_ms: number | null;
  prev_requests: number;
  state: RelState;
  principals: number;
  unknown_requests: number;
  callers: number;
  apis: number;
  services: number;
  ips: number;
  is_load_balancer?: boolean;
  role?: string;
  role_label?: string;
  environment?: string;
  group?: string;
  module?: string;
};

export type FacetResult = { total: number; items: RelRow[]; truncated: boolean };
export type SharedRow = { name: string; unknown: boolean; shared_ips: number; requests: number; last_seen_ms: number | null; sample_ips: string[] };

export type Summary = {
  requests: number; errors: number; error_rate: number; tps: number; p95_ms: number;
  request_bytes: number; response_bytes: number; prev_requests: number;
  unknown_requests: number; unknown_ips: number;
  principals: number; callers: number; apis: number; services: number; ips: number;
  first_seen_ms: number; last_seen_ms: number;
};

export type SeriesPoint = {
  timestamp_ms: number; requests: number; errors: number;
  request_bytes_per_second: number; response_bytes_per_second: number; bandwidth_bytes_per_second: number;
  request_bytes_samples: number; response_bytes_samples: number; bandwidth_available: boolean;
};

export type MetaKey = "environment" | "group" | "module";
export type MetaOption = { value: string; services: number };

export type Relationships = {
  service_meta_options?: Record<MetaKey, MetaOption[]>;
  window: { start_ms: number; end_ms: number; previous_start_ms: number; history_available: boolean };
  summary: Summary;
  series: SeriesPoint[];
  facets: Partial<Record<Facet | "unknown_ip", FacetResult>> & { shared?: { total: number; items: SharedRow[]; truncated: boolean } };
};

export type Scope = { principal?: string; service?: string; api?: string };

/** Multi-select facets: several services or caller services at once. */
export const MULTI_FACETS = ["service", "caller"] as const;
export type MultiFacet = (typeof MULTI_FACETS)[number];
export type Selection = {
  service?: string[];
  caller?: string[];
  principal?: string;
  api?: string;
  api_service?: string;
  ip?: string;
  environment?: string;
  group?: string;
  module?: string;
};

const SINGLE_KEYS = ["principal", "api", "api_service", "ip", "environment", "group", "module"] as const;
const isMulti = (facet: string): facet is MultiFacet => (MULTI_FACETS as readonly string[]).includes(facet);

export const UNKNOWN_PRINCIPALS = new Set(["-anonymous-", "anonymous", "unknown", ""]);

function epochMs(value: string) {
  return isNaN(Number(value)) ? String(Date.parse(value)) : value;
}

/** Only the time window: workspace pages never inherit the global Service/Account filters. */
export function windowParams(filters: Filters) {
  const p = new URLSearchParams();
  p.set("from", epochMs(filters.start));
  p.set("to", epochMs(filters.end));
  return p;
}

/** Search string carried on workspace links (time window + timezone, no selection). */
export function useTimeSearch() {
  const { filters } = useFilters();
  const p = new URLSearchParams();
  p.set("start", filters.start);
  p.set("end", filters.end);
  if (filters.timezone && filters.timezone !== "local") p.set("timezone", filters.timezone);
  return `?${p.toString()}`;
}

export function appendSelection(params: URLSearchParams, selection: Selection) {
  Object.entries(selection).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((item) => params.append(`sel_${key}`, item));
    else if (value) params.set(`sel_${key}`, value);
  });
}

export function useRelationships(scope: Scope, selection: Selection, facets: string[], limit = 200) {
  const { filters } = useFilters();
  const params = windowParams(filters);
  Object.entries(scope).forEach(([key, value]) => value && params.set(key, value));
  appendSelection(params, selection);
  params.set("facets", facets.join(","));
  params.set("limit", String(limit));
  const url = `/api/v1/relationships?${params.toString()}`;
  return useQuery({
    queryKey: ["relationships", url],
    queryFn: () => api<Relationships>(url),
    placeholderData: keepPreviousData,
  });
}

export type FocusTarget = { facet: Facet; name: string; service?: string } | { meta: MetaKey; value: string };

export type SelectionApi = {
  selection: Selection;
  /** Table row click: toggles membership for multi facets, replaces for single ones. */
  toggle: (facet: Facet, row: RelRow | null) => void;
  /** Replace a multi facet's whole value list. */
  setMany: (facet: MultiFacet, values: string[]) => void;
  /** Set one catalog level; clearing a level also clears the levels below it. */
  setMeta: (key: MetaKey, value: string) => void;
  remove: (key: keyof Selection, value?: string) => void;
  /** Add several filters at once (one URL update): rows to focus on and/or catalog levels. */
  focus: (targets: FocusTarget[]) => void;
  /** Clear one multi facet and the catalog levels in a single URL update. */
  reset: (facet: MultiFacet) => void;
  clear: () => void;
};

/** Row selection kept in the URL (sel_*), so back/forward and shared links keep it. */
export function useSelection(): SelectionApi {
  const [params, setParams] = useSearchParams();
  const selection: Selection = {};
  MULTI_FACETS.forEach((key) => {
    const values = params.getAll(`sel_${key}`).filter(Boolean);
    if (values.length) selection[key] = values;
  });
  SINGLE_KEYS.forEach((key) => {
    const value = params.get(`sel_${key}`);
    if (value) selection[key] = value;
  });
  const update = (mutate: (next: URLSearchParams) => void) => setParams((prev) => {
    const next = new URLSearchParams(prev);
    mutate(next);
    return next;
  }, { replace: true });
  const setMany = (facet: MultiFacet, values: string[]) => update((next) => {
    next.delete(`sel_${facet}`);
    [...new Set(values)].forEach((value) => next.append(`sel_${facet}`, value));
  });
  const toggle = (facet: Facet, row: RelRow | null) => {
    if (isMulti(facet)) {
      if (!row) return setMany(facet, []);
      const current = selection[facet] || [];
      return setMany(facet, current.includes(row.name) ? current.filter((value) => value !== row.name) : [...current, row.name]);
    }
    update((next) => {
      const same = row && next.get(`sel_${facet}`) === row.name && (facet !== "api" || next.get("sel_api_service") === row.service);
      next.delete(`sel_${facet}`);
      if (facet === "api") next.delete("sel_api_service");
      if (row && !same) {
        next.set(`sel_${facet}`, row.name);
        if (facet === "api" && row.service) next.set("sel_api_service", row.service);
      }
    });
  };
  const setMeta = (key: MetaKey, value: string) => update((next) => {
    const order: MetaKey[] = ["environment", "group", "module"];
    order.slice(order.indexOf(key)).forEach((level) => next.delete(`sel_${level}`));
    if (value) next.set(`sel_${key}`, value);
  });
  const remove = (key: keyof Selection, value?: string) => update((next) => {
    if (value !== undefined && isMulti(key)) {
      const rest = next.getAll(`sel_${key}`).filter((item) => item !== value);
      next.delete(`sel_${key}`);
      rest.forEach((item) => next.append(`sel_${key}`, item));
      return;
    }
    if (key === "environment" || key === "group" || key === "module") {
      const order: MetaKey[] = ["environment", "group", "module"];
      order.slice(order.indexOf(key)).forEach((level) => next.delete(`sel_${level}`));
      return;
    }
    next.delete(`sel_${key}`);
    if (key === "api") next.delete("sel_api_service");
  });
  const focus = (targets: FocusTarget[]) => update((next) => {
    const levels: MetaKey[] = ["environment", "group", "module"];
    targets.forEach((target) => {
      if ("meta" in target) {
        levels.slice(levels.indexOf(target.meta)).forEach((level) => next.delete(`sel_${level}`));
        next.set(`sel_${target.meta}`, target.value);
      } else if (isMulti(target.facet)) {
        if (!next.getAll(`sel_${target.facet}`).includes(target.name)) next.append(`sel_${target.facet}`, target.name);
      } else {
        next.set(`sel_${target.facet}`, target.name);
        if (target.facet === "api") {
          if (target.service) next.set("sel_api_service", target.service);
          else next.delete("sel_api_service");
        }
      }
    });
  });
  const reset = (facet: MultiFacet) => update((next) => [facet, "environment", "group", "module"].forEach((key) => next.delete(`sel_${key}`)));
  const clear = () => update((next) => [...MULTI_FACETS, ...SINGLE_KEYS].forEach((key) => next.delete(`sel_${key}`)));
  return { selection, toggle, setMany, setMeta, remove, focus, reset, clear };
}

export function isSelected(selection: Selection, facet: Facet, row: RelRow) {
  if (isMulti(facet)) return (selection[facet] || []).includes(row.name);
  return selection[facet] === row.name && (facet !== "api" || !selection.api_service || selection.api_service === row.service);
}

const enc = encodeURIComponent;
export const workspacePath = {
  users: () => "/workspace/users",
  apis: () => "/workspace/apis",
  services: () => "/workspace/services",
  user: (principal: string) => `/workspace/users/${enc(principal)}`,
  api: (service: string, api: string) => `/workspace/apis/${enc(service)}/${enc(api)}`,
  service: (service: string) => `/workspace/services/${enc(service)}`,
};

/** Link carrying the current time window plus an optional starting selection on the target page. */
export function withSelection(search: string, selection: Selection) {
  const p = new URLSearchParams(search.replace(/^\?/, ""));
  appendSelection(p, selection);
  return `?${p.toString()}`;
}

export function tpsDigits(value: number) {
  if (!value) return 0;
  if (value < 0.01) return 4;
  if (value < 1) return 3;
  return 2;
}

export function formatBytes(value: number) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exp = Math.min(units.length - 1, Math.floor(Math.log10(value) / 3));
  return `${(value / 1000 ** exp).toFixed(exp ? 1 : 0)} ${units[exp]}`;
}

export function shortTime(ms: number | null | undefined) {
  return ms ? new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

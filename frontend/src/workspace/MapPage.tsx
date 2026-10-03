import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ExternalLink, Search, X } from "lucide-react";
import { api } from "../api";
import { ErrorState, Loading, Page, n, pct } from "../components";
import { useFilters } from "../App";
import { useI18n } from "../i18n";
import {
  UNKNOWN_PRINCIPALS, windowParams, workspacePath,
  type RelRow, type RelState, type Relationships,
} from "./model";
import { StateBadge, formatTps } from "./parts";

type AnchorKind = "all" | "user" | "unknown" | "service" | "api" | "group";
type ListKind = "users" | "apis" | "services";

type TrailItem = {
  kind: AnchorKind;
  anchor: string;
  service?: string;
  scope_user?: string | null;
};

const ROW_HEIGHT = 36;
const RIBBON = 1.5;
const RIBBON_ON = 2.5;
const TOP_N = 10;

export function compact(value: number) {
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1e4) return `${(value / 1e3).toFixed(1)}K`;
  return n(value, 0);
}

function parseTrail(raw: string | null): TrailItem[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.slice(0, 6);
  } catch {
    // fallback
  }
  return [];
}

export function RelationshipMapPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();

  // Read URL state
  const rawKind = params.get("anchor_kind") as AnchorKind | null;
  const anchorKind: AnchorKind = rawKind || "all";
  const anchor = params.get("anchor") || "";
  const anchorService = params.get("anchor_service") || "";
  const scopeUser = params.get("scope_user") || null;
  const trail = useMemo(() => parseTrail(params.get("trail")), [params.get("trail")]);
  const listKind = (params.get("list") as ListKind) || "users";
  const pinParam = params.getAll("pin").join("\n");
  const pins = useMemo(() => (pinParam ? pinParam.split("\n") : []), [pinParam]);
  const togglePin = (key: string) => updateUrl((next) => {
    const current = next.getAll("pin");
    next.delete("pin");
    (current.includes(key) ? current.filter((k) => k !== key) : [...current, key]).forEach((k) => next.append("pin", k));
  });
  const clearPins = () => updateUrl((next) => next.delete("pin"));

  // Left rail search state
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);
  const [searchHighlightIndex, setSearchHighlightIndex] = useState(0);

  // More in-place filter state
  const [moreOpen, setMoreOpen] = useState<{ L: boolean; R: boolean }>({ L: false, R: false });
  const [moreFilter, setMoreFilter] = useState<{ L: string; R: string }>({ L: "", R: "" });
  const [hovered, setHovered] = useState<string | null>(null);

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
      setSearchHighlightIndex(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Combined URL update helper (React Router drops back-to-back updates)
  const updateUrl = (mutator: (next: URLSearchParams) => void) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      mutator(next);
      return next;
    }, { replace: true });
  };

  // Switch list in rail
  const setListKind = (kind: ListKind) => {
    updateUrl((next) => {
      if (kind === "users") next.delete("list");
      else next.set("list", kind);
    });
  };

  // Move anchor to a new target
  const navigateAnchor = (
    nextKind: AnchorKind,
    nextAnchor: string,
    nextService?: string,
    pushTrail = true,
  ) => {
    const same = (item: TrailItem) => item.kind === nextKind && (nextKind === "all" || item.anchor === nextAnchor)
      && (nextKind !== "api" || (item.service || "") === (nextService || ""));
    if (same({ kind: anchorKind, anchor, service: anchorService || undefined })) return;
    updateUrl((next) => {
      next.delete("pin");
      if (pushTrail) {
        const currentItem: TrailItem = {
          kind: anchorKind,
          anchor,
          service: anchorService || undefined,
          scope_user: scopeUser || undefined,
        };
        let nextTrail = [...trail, currentItem];
        // Going to an anchor already on the path: step back to it instead of growing the path.
        const back = nextTrail.findIndex(same);
        if (back >= 0) nextTrail = nextTrail.slice(0, back);
        nextTrail = nextTrail.slice(-6);
        if (nextTrail.length) next.set("trail", JSON.stringify(nextTrail));
        else next.delete("trail");
      } else {
        // A pick from the list or the search bar starts a new path.
        next.delete("trail");
      }

      // Setting new anchor
      if (nextKind === "all") {
        next.delete("anchor_kind");
        next.delete("anchor");
        next.delete("anchor_service");
      } else {
        next.set("anchor_kind", nextKind);
        next.set("anchor", nextAnchor);
        if (nextKind === "api" && nextService) next.set("anchor_service", nextService);
        else next.delete("anchor_service");
      }

      // User scoping rules:
      // - anchoring on a user clears scope_user
      // - if old anchor was a user, and new anchor is a service/API, set scope_user to that user
      // - from unknown users to a service/API, keep only unknown traffic
      // - an estate, group or user anchor has no user scope
      if (nextKind === "service" || nextKind === "api") {
        if (anchorKind === "user" && anchor) next.set("scope_user", anchor);
        else if (anchorKind === "unknown") next.set("scope_user", "-anonymous-");
      } else {
        next.delete("scope_user");
      }
    });

    setMoreOpen({ L: false, R: false });
    setMoreFilter({ L: "", R: "" });
    setSearchQuery("");
  };

  // Restore breadcrumb item
  const restoreTrail = (index: number) => {
    const item = trail[index];
    if (!item) return;
    const nextTrail = trail.slice(0, index);
    updateUrl((next) => {
      if (nextTrail.length) next.set("trail", JSON.stringify(nextTrail));
      else next.delete("trail");

      if (item.kind === "all") {
        next.delete("anchor_kind");
        next.delete("anchor");
        next.delete("anchor_service");
      } else {
        next.set("anchor_kind", item.kind);
        next.set("anchor", item.anchor);
        if (item.service) next.set("anchor_service", item.service);
        else next.delete("anchor_service");
      }

      if (item.scope_user) next.set("scope_user", item.scope_user);
      else next.delete("scope_user");
      next.delete("pin");
    });
    setMoreOpen({ L: false, R: false });
    setMoreFilter({ L: "", R: "" });
  };

  const removeScopeUser = () => {
    updateUrl((next) => next.delete("scope_user"));
  };

  // 1. Data query for left rail search (when debouncedSearch is present)
  const searchUrl = useMemo(() => {
    if (!debouncedSearch) return null;
    const p = windowParams(filters);
    p.set("q", debouncedSearch);
    p.set("facets", "principal,service,api");
    p.set("limit", "8");
    return `/api/v1/relationships?${p.toString()}`;
  }, [filters, debouncedSearch]);

  const searchQueryResult = useQuery({
    queryKey: ["relationships-search", searchUrl],
    queryFn: () => api<Relationships>(searchUrl!),
    enabled: Boolean(searchUrl),
    placeholderData: keepPreviousData,
  });

  // Extract search results (groups first from service_meta_options.group matching query, then users, services, apis)
  const searchResults = useMemo(() => {
    if (!debouncedSearch || !searchQueryResult.data) return [];
    const qLower = debouncedSearch.toLowerCase();
    const results: Array<{
      kind: AnchorKind;
      name: string;
      service?: string;
      label: string;
    }> = [];

    // Matching groups from meta options
    const groups = searchQueryResult.data.service_meta_options?.group || [];
    groups.forEach((g) => {
      if (g.value && g.value.toLowerCase().includes(qLower)) {
        results.push({ kind: "group", name: g.value, label: `${g.value} (${g.services} svc)` });
      }
    });

    // Users
    (searchQueryResult.data.facets.principal?.items || []).forEach((u) => {
      if (!UNKNOWN_PRINCIPALS.has(u.name)) {
        results.push({ kind: "user", name: u.name, label: u.name });
      }
    });

    // Services
    (searchQueryResult.data.facets.service?.items || []).forEach((s) => {
      results.push({ kind: "service", name: s.name, label: s.name });
    });

    // APIs
    (searchQueryResult.data.facets.api?.items || []).forEach((a) => {
      results.push({ kind: "api", name: a.name, service: a.service, label: a.name });
    });

    return results.slice(0, 8);
  }, [debouncedSearch, searchQueryResult.data]);

  // 2. Data query for the left rail list (Users | APIs | Services)
  const listUrl = useMemo(() => {
    const p = windowParams(filters);
    if (listKind === "users") {
      p.set("facets", "principal");
    } else if (listKind === "apis") {
      p.set("facets", "api");
    } else {
      p.set("facets", "service");
    }
    p.set("limit", "1000");
    return `/api/v1/relationships?${p.toString()}`;
  }, [filters, listKind]);

  const listQueryResult = useQuery({
    queryKey: ["relationships-rail-list", listUrl],
    queryFn: () => api<Relationships>(listUrl),
    placeholderData: keepPreviousData,
  });

  // Filtered and sorted items for the left rail
  const railListItems = useMemo(() => {
    const data = listQueryResult.data;
    if (!data) return [];
    const qLower = debouncedSearch.toLowerCase();

    if (listKind === "users") {
      const items = (data.facets.principal?.items || [])
        .filter((r) => !UNKNOWN_PRINCIPALS.has(r.name) && (!qLower || r.name.toLowerCase().includes(qLower)))
        .sort((a, b) => b.services - a.services || b.requests - a.requests);
      return items.slice(0, 300);
    }
    if (listKind === "apis") {
      const items = (data.facets.api?.items || [])
        .filter((r) => !qLower || r.name.toLowerCase().includes(qLower) || (r.service && r.service.toLowerCase().includes(qLower)))
        .sort((a, b) => b.requests - a.requests);
      return items.slice(0, 300);
    }
    const items = (data.facets.service?.items || [])
      .filter((r) => !qLower || r.name.toLowerCase().includes(qLower) || (r.group && r.group.toLowerCase().includes(qLower)))
      .sort((a, b) => b.requests - a.requests);
    return items.slice(0, 300);
  }, [listQueryResult.data, listKind, debouncedSearch]);

  // 3. Main data for the active anchor
  const scopeIsUnknown = scopeUser ? UNKNOWN_PRINCIPALS.has(scopeUser) : false;
  const mainUrl = useMemo(() => {
    const p = windowParams(filters);
    if (anchorKind === "all") {
      p.set("facets", "caller,service,principal");
    } else if (anchorKind === "user") {
      p.set("principal", anchor);
      p.set("facets", "ip,api,service");
    } else if (anchorKind === "unknown") {
      p.set("principal", "-anonymous-");
      p.set("facets", "ip,api,caller");
    } else if (anchorKind === "service") {
      p.set("service", anchor);
      if (scopeUser) p.set("sel_principal", scopeUser);
      p.set("facets", "principal,api,caller");
    } else if (anchorKind === "api") {
      if (!anchorService) return null;
      p.set("service", anchorService);
      p.set("api", anchor);
      if (scopeUser) p.set("sel_principal", scopeUser);
      p.set("facets", "unknown_ip");
    } else if (anchorKind === "group") {
      p.set("sel_group", anchor);
      p.set("facets", "caller,service,principal");
    }
    p.set("limit", "100");
    return `/api/v1/relationships?${p.toString()}`;
  }, [filters, anchorKind, anchor, anchorService, scopeUser]);

  const mainQuery = useQuery({
    queryKey: ["relationships-main-anchor", mainUrl],
    queryFn: () => api<Relationships>(mainUrl!),
    enabled: Boolean(mainUrl),
    placeholderData: keepPreviousData,
  });

  // API anchor: origin (caller service, or source IP when there is none) -> user pairs.
  const linksUrl = useMemo(() => {
    if (anchorKind !== "api" || !anchorService) return null;
    const p = windowParams(filters);
    p.set("left", "origin");
    p.set("right", "principal");
    p.set("service", anchorService);
    p.set("api", anchor);
    if (scopeUser) p.set("sel_principal", scopeUser);
    return `/api/v1/relationships/links?${p.toString()}`;
  }, [filters, anchorKind, anchor, anchorService, scopeUser]);

  const linksQuery = useQuery({
    queryKey: ["relationships-links", linksUrl],
    queryFn: () => api<LinksResponse>(linksUrl!),
    enabled: Boolean(linksUrl),
    placeholderData: keepPreviousData,
  });

  // Ego anchors: which left row reaches which right row through the centre
  // (IP -> API for a user, user -> API for a service), for the hover path.
  const pairsUrl = useMemo(() => {
    const p = windowParams(filters);
    if (anchorKind === "user" || anchorKind === "unknown") {
      p.set("left", "ip");
      p.set("right", "api");
      p.set("principal", anchorKind === "user" ? anchor : "-anonymous-");
    } else if (anchorKind === "service") {
      p.set("left", "principal");
      p.set("right", "api");
      p.set("service", anchor);
      if (scopeUser) p.set("sel_principal", scopeUser);
    } else {
      return null;
    }
    return `/api/v1/relationships/links?${p.toString()}`;
  }, [filters, anchorKind, anchor, scopeUser]);

  const pairsQuery = useQuery({
    queryKey: ["relationships-pairs", pairsUrl],
    queryFn: () => api<LinksResponse>(pairsUrl!),
    enabled: Boolean(pairsUrl),
    placeholderData: keepPreviousData,
  });

  // Partner keys per row key, from either pair set.
  const partners = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const add = (a: string, b: string) => {
      if (!map.has(a)) map.set(a, new Set());
      map.get(a)!.add(b);
    };
    const keyOf = (kind: string, name: string, service?: string): string =>
      kind === "api" ? rowKey("api", name, service || "") : kind === "unknown" ? rowKey("unknown", "-anonymous-")
        : kind === "user" ? rowKey("user", name) : kind === "ip" ? rowKey("ip", name) : rowKey("service", name);
    const data = anchorKind === "api" ? linksQuery.data : pairsQuery.data;
    (data?.links || []).forEach((l) => {
      if (!l.requests) return;
      const a = keyOf(l.left_kind, l.left, l.left_service);
      const b = keyOf(l.right_kind, l.right, l.right_service);
      add(a, b);
      add(b, a);
    });
    return map;
  }, [anchorKind, linksQuery.data, pairsQuery.data]);

  // Rows on the hovered path: the hovered row and every row it reaches through the centre.
  // Rows on the hovered and pinned paths: each such row and every row it reaches through the centre.
  const related = useMemo(() => {
    const roots = [...pins, ...(hovered ? [hovered] : [])];
    if (!roots.length) return null;
    const set = new Set<string>();
    roots.forEach((key) => { set.add(key); (partners.get(key) || []).forEach((k) => set.add(k)); });
    return set;
  }, [hovered, pins, partners]);

  const unknownLabel = t("Unknown users", "Người dùng chưa xác định");

  // Columns of the active anchor. Ego anchors: left -> centre -> right.
  // API anchor: origins -> users -> centre (the API itself, at the end of the flow).
  const view = useMemo(() => {
    const facets = mainQuery.data?.facets;
    const summary = mainQuery.data?.summary;
    const rows = (items: RelRow[] | undefined, kind: RowKind) => (items || []).map((r) => fromRel(r, kind));
    const users = (items: RelRow[] | undefined) => rows(items, "user").filter((r) => !scopeUser || r.name === scopeUser);
    const unknownRow = (requests: number, prev = 0): MapRow => ({
      key: rowKey("unknown", "-anonymous-"), kind: "unknown", name: "-anonymous-", label: unknownLabel,
      requests, prev_requests: prev, state: "active",
    });
    const chipsOf = (items: RelRow[] | undefined, kind: RowKind) =>
      (items || []).filter((r) => r.requests > 0 && !UNKNOWN_PRINCIPALS.has(r.name)).slice(0, 6).map((r) => fromRel(r, kind));

    let left: Column = { title: "", rows: [] };
    let right: Column = { title: "", rows: [] };
    let flowLinks: FlowLink[] = [];
    let chips: MapRow[] = [];
    let chipsTitle = "";
    let eyebrow = "";
    let title = anchor;
    let link: string | null = null;

    if (anchorKind === "all" || anchorKind === "group") {
      left = { title: t("Called from", "Gọi từ"), rows: rows(facets?.caller?.items, "service") };
      const callersSum = left.rows.reduce((sum, r) => sum + r.requests, 0);
      const noCaller = summary ? Math.max(0, summary.requests - callersSum) : 0;
      if (noCaller > 0) left.rows.push({ key: rowKey("none", ""), kind: "none", name: "", label: t("No caller service", "Không có caller service"), requests: noCaller, prev_requests: 0, state: "active" });
      right = { title: t("Services", "Dịch vụ"), rows: rows(facets?.service?.items, "service") };
      chips = chipsOf(facets?.principal?.items, "user");
      chipsTitle = t("Top users", "User hàng đầu");
      eyebrow = anchorKind === "all" ? t("All traffic", "Toàn bộ lưu lượng") : t("Group", "Nhóm");
      title = anchorKind === "all" ? t("All estate traffic", "Toàn bộ lưu lượng hệ thống") : anchor;
      link = workspacePath.services();
    } else if (anchorKind === "user" || anchorKind === "unknown") {
      left = { title: t("Source IPs", "IP nguồn"), rows: rows(facets?.ip?.items, "ip") };
      right = { title: "APIs", rows: rows(facets?.api?.items, "api") };
      if (anchorKind === "user") {
        chips = chipsOf(facets?.service?.items, "service");
        chipsTitle = t("Services", "Dịch vụ");
        eyebrow = "User";
        link = workspacePath.user(anchor);
      } else {
        chips = chipsOf(facets?.caller?.items, "service");
        chipsTitle = t("Comes through", "Đi qua");
        eyebrow = t("Unknown users", "Người dùng chưa xác định");
        title = unknownLabel;
        link = workspacePath.users();
      }
    } else if (anchorKind === "service") {
      const userRows = users(facets?.principal?.items);
      const unknown = summary?.unknown_requests || 0;
      left = { title: t("Users", "User"), rows: unknown > 0 && (!scopeUser || scopeIsUnknown) ? [unknownRow(unknown), ...userRows] : userRows };
      right = { title: "APIs", rows: rows(facets?.api?.items, "api").map((r) => ({ ...r, sub: undefined })) };
      chips = chipsOf(facets?.caller?.items, "service");
      chipsTitle = t("Called by", "Được gọi bởi");
      eyebrow = "Service";
      link = workspacePath.service(anchor);
    } else if (anchorKind === "api") {
      const data = linksQuery.data;
      const history = Boolean(data?.window.history_available);
      const origins = new Map<string, MapRow>();
      const userMap = new Map<string, MapRow>();
      flowLinks = (data?.links || []).map((l) => {
        const okind: RowKind = l.left_kind === "ip" ? "ip" : "service";
        const ukind: RowKind = l.right_kind === "unknown" ? "unknown" : "user";
        const from = rowKey(okind, l.left);
        const to = rowKey(ukind, l.right);
        const o = origins.get(from) || { key: from, kind: okind, name: l.left, label: l.left, requests: 0, prev_requests: 0, state: "active" as RelState,
          sub: okind === "ip" ? (l.role_label || l.role || "") : undefined, lb: okind === "ip" ? Boolean(l.is_load_balancer) : undefined };
        o.requests += l.requests; o.prev_requests += l.prev_requests; origins.set(from, o);
        const u = userMap.get(to) || { key: to, kind: ukind, name: l.right, label: ukind === "unknown" ? unknownLabel : l.right, requests: 0, prev_requests: 0, state: "active" as RelState };
        u.requests += l.requests; u.prev_requests += l.prev_requests; userMap.set(to, u);
        return { from, to, requests: l.requests, prev_requests: l.prev_requests, state: l.state };
      });
      const withState = (r: MapRow) => ({ ...r, state: aggState(r.requests, r.prev_requests, history) });
      left = { title: t("Comes from", "Đến từ"), rows: [...origins.values()].map(withState), truncated: data?.truncated };
      right = { title: t("Users", "User"), rows: [...userMap.values()].map(withState), truncated: data?.truncated };
      chips = (facets?.unknown_ip?.items || []).filter((r) => r.requests > 0).slice(0, 6).map((r) => fromRel(r, "ip"));
      chipsTitle = t("Unknown users' source IPs", "IP nguồn của user chưa xác định");
      eyebrow = `API · ${anchorService}`;
      link = workspacePath.api(anchorService, anchor);
    }

    const order = (a: MapRow, b: MapRow) => Math.max(b.requests, b.prev_requests) - Math.max(a.requests, a.prev_requests);
    left.rows.sort(order);
    right.rows.sort(order);
    return { left, right, flowLinks, chips, chipsTitle, eyebrow, title, link };
  }, [mainQuery.data, linksQuery.data, anchorKind, anchor, anchorService, scopeUser, scopeIsUnknown, unknownLabel, t]);

  // Keyboard navigation for search dropdown
  const handleSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!searchResults.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSearchHighlightIndex((prev) => Math.min(searchResults.length - 1, prev + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSearchHighlightIndex((prev) => Math.max(0, prev - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const picked = searchResults[searchHighlightIndex];
      if (picked) {
        navigateAnchor(picked.kind, picked.name, picked.service, false);
        setSearchFocused(false);
      }
    } else if (e.key === "Escape") {
      setSearchQuery("");
      setSearchFocused(false);
    }
  };

  const isFlow = anchorKind === "api";
  const { flowLinks } = view;
  // A pinned row filters the other column to the rows on its path.
  const pinFilter = (col: Column, other: Column): Column => {
    const otherKeys = new Set(other.rows.map((r) => r.key));
    const roots = pins.filter((k) => otherKeys.has(k));
    if (!roots.length) return col;
    const keep = new Set(roots.flatMap((k) => [...(partners.get(k) || [])]));
    return { ...col, rows: col.rows.filter((r) => keep.has(r.key) || pins.includes(r.key)), filteredFrom: col.rows.length };
  };
  const left = pinFilter(view.left, view.right);
  const right = pinFilter(view.right, view.left);
  const pinnedRows = [...view.left.rows, ...view.right.rows].filter((r) => pins.includes(r.key));
  const shownLeft = left.rows.slice(0, TOP_N);
  const shownRight = right.rows.slice(0, TOP_N);
  const H = Math.max(260, Math.max(shownLeft.length, shownRight.length) * ROW_HEIGHT);
  const offL = (H - shownLeft.length * ROW_HEIGHT) / 2;
  const offR = (H - shownRight.length * ROW_HEIGHT) / 2;

  const summary = mainQuery.data?.summary;
  const history = Boolean(mainQuery.data?.window.history_available);
  const changePct = summary && summary.prev_requests ? Math.round(((summary.requests - summary.prev_requests) / summary.prev_requests) * 100) : null;
  const loading = (mainQuery.isLoading && Boolean(mainUrl)) || (isFlow && linksQuery.isLoading);
  const error = (mainQuery.error || linksQuery.error || pairsQuery.error) as Error | null;

  const openRow = (row: MapRow) => {
    if (row.kind === "none" || row.kind === "ip") return;
    if (row.kind === "unknown") navigateAnchor("unknown", "-anonymous-");
    else if (row.kind === "user") navigateAnchor("user", row.name);
    else if (row.kind === "service") navigateAnchor("service", row.name);
    else navigateAnchor("api", row.name, row.service || anchorService || anchor);
  };

  const strokeOf = (state: RelState, surge: boolean) =>
    state === "new" ? "var(--accent)" : surge ? "var(--warn)" : state === "silent" ? "var(--bad)" : "var(--border-strong)";

  const renderRow = (row: MapRow) => {
    const clickable = row.kind !== "none" && row.kind !== "ip";
    const pinnable = row.kind !== "none";
    const pinned = pins.includes(row.key);
    return (
      <div
        key={row.key}
        onMouseEnter={() => setHovered(row.key)}
        onMouseLeave={() => setHovered(null)}
        style={{ height: `${ROW_HEIGHT}px` }}
        className={`grid w-full grid-cols-[18px_minmax(0,1fr)] items-center gap-1 rounded px-1 transition-colors hover:bg-hover ${
          related?.has(row.key) ? "bg-hover ring-1 ring-inset ring-[color:var(--path-highlight)]" : ""
        }`}
      >
        <button
          type="button"
          disabled={!pinnable}
          aria-pressed={pinned}
          onClick={() => togglePin(row.key)}
          onFocus={() => setHovered(row.key)}
          onBlur={() => setHovered(null)}
          title={pinned ? t("Unpin", "Bỏ ghim") : t("Pin: keep this path and filter the other column", "Ghim: giữ đường đi này và lọc cột còn lại")}
          aria-label={pinned ? t("Unpin", "Bỏ ghim") : t("Pin", "Ghim")}
          className="flex h-[18px] w-[18px] items-center justify-center rounded-full bg-transparent"
        >
          <span
            className={`rounded-sm ${DOT[row.kind]} ${pinned ? "h-2.5 w-2.5 ring-2 ring-offset-1 ring-offset-[color:var(--surface)] ring-[color:var(--path-highlight)]" : "h-2 w-2"}`}
          />
        </button>
        <button
          type="button"
          aria-disabled={!clickable}
          onClick={() => openRow(row)}
          onFocus={() => setHovered(row.key)}
          onBlur={() => setHovered(null)}
          title={row.kind === "api" ? `${row.name} · ${row.service || ""}` : row.kind === "ip" ? `${row.name}${row.sub ? ` · ${row.sub}` : ""}` : row.label}
          className={`grid h-full min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 bg-transparent px-1 text-left ${clickable ? "" : "cursor-default"}`}
        >
          <div className="min-w-0 leading-tight">
            <div className={`truncate text-xs ${row.kind === "unknown" ? "font-semibold text-warn" : row.kind === "none" ? "text-muted" : "font-mono text-ink"}`}>{row.label}</div>
            {row.sub && <div className="truncate text-[10px] text-faint">{row.sub}</div>}
          </div>
          <span className="text-right font-mono text-xs text-muted">{compact(row.requests)}</span>
          <div className="flex items-center gap-1">
            {row.lb && <span className="rounded-[2px] border border-line px-1 text-[10px] text-muted">LB</span>}
            {isSurge(row) && <span className="rounded-full bg-warn-bg px-1.5 text-[10px] font-semibold text-warn">{t("Surge", "Tăng vọt")}</span>}
            <StateBadge state={row.state} />
          </div>
        </button>
      </div>
    );
  };

  const renderColumn = (col: Column, side: "L" | "R", shown: MapRow[], off: number, hint?: string) => (
    <div className="w-full min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold text-muted" style={{ minHeight: "19px" }}>
        <span className="truncate" title={hint}>{col.title}</span>
        <span className="font-mono text-[11px] text-faint">{col.filteredFrom != null ? `${col.rows.length} / ${col.filteredFrom}` : col.rows.length}{col.truncated ? "+" : ""}</span>
      </div>
      <div className="relative" style={{ height: `${H}px` }}>
        <div className="absolute left-0 right-0" style={{ top: `${off}px` }}>
          {shown.length ? shown.map((row) => renderRow(row)) : <p className="p-2 text-xs text-faint">{t("No items", "Không có mục nào")}</p>}
        </div>
      </div>
      {hint && <p className="mt-1 text-[10px] text-muted">{hint}</p>}
      {col.rows.length > TOP_N && (
        <div className="mt-2">
          <button type="button" onClick={() => setMoreOpen((prev) => ({ ...prev, [side]: !prev[side] }))} className="text-xs font-semibold text-accent hover:underline">
            {moreOpen[side] ? t("Hide", "Ẩn") : `+ ${col.rows.length - TOP_N} ${t("more", "mục khác")}`}
          </button>
          {moreOpen[side] && (
            <div className="mt-1 max-h-56 space-y-1 overflow-y-auto rounded border border-line p-1">
              <input
                type="text"
                aria-label={t("Filter list", "Lọc danh sách")}
                placeholder={t("Filter list...", "Lọc danh sách...")}
                value={moreFilter[side]}
                onChange={(e) => setMoreFilter((prev) => ({ ...prev, [side]: e.target.value }))}
                className="toolbar-control h-7 w-full px-2 text-xs"
              />
              {col.rows
                .slice(TOP_N)
                .filter((r) => !moreFilter[side] || `${r.label} ${r.sub || ""}`.toLowerCase().includes(moreFilter[side].toLowerCase()))
                .slice(0, 100)
                .map((row) => (
                  <button
                    type="button"
                    key={row.key}
                    disabled={row.kind === "none" || row.kind === "ip"}
                    onClick={() => openRow(row)}
                    className="flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-xs enabled:hover:bg-hover"
                  >
                    <span className="min-w-0 truncate font-mono text-ink">{row.label}{row.sub ? <span className="ml-1 text-faint">· {row.sub}</span> : null}</span>
                    <span className="font-mono text-muted">{compact(row.requests)}</span>
                  </button>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );

  // Fan of paths between one column and the centre card.
  const renderFan = (rows: MapRow[], off: number, dir: "in" | "out") => {
    const yc = H / 2;
    return (
      <div className="hidden md:block" style={{ paddingTop: "27px" }}>
        <svg className="block w-full" height={H} viewBox={`0 0 56 ${H}`} preserveAspectRatio="none" aria-hidden="true">
          {rows.map((row, i) => ({ row, i, on: Boolean(related?.has(row.key)) })).sort((a, b) => Number(a.on) - Number(b.on)).map(({ row, i, on }) => {
            const y = off + i * ROW_HEIGHT + ROW_HEIGHT / 2;
            const w = on ? RIBBON_ON : RIBBON;
            return (
              <path
                key={row.key}
                d={dir === "in" ? `M 0,${y} C 28,${y} 28,${yc} 56,${yc}` : `M 0,${yc} C 28,${yc} 28,${y} 56,${y}`}
                fill="none"
                stroke={on ? "var(--path-highlight)" : strokeOf(row.state, isSurge(row))}
                strokeWidth={w}
                strokeOpacity={related && !on ? 0.2 : on ? 1 : 0.75}
                strokeDasharray={row.state === "silent" ? "4 3" : undefined}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
        </svg>
      </div>
    );
  };

  // Origin -> user links of the API flow (only between rows that are on screen).
  const renderPairs = () => {
    const li = new Map(shownLeft.map((r, i) => [r.key, i]));
    const ri = new Map(shownRight.map((r, i) => [r.key, i]));
    const drawn = flowLinks.filter((l) => li.has(l.from) && ri.has(l.to));
    return (
      <div className="hidden md:block" style={{ paddingTop: "27px" }}>
        <svg className="block w-full" height={H} viewBox={`0 0 72 ${H}`} preserveAspectRatio="none" aria-hidden="true">
          {drawn.map((l) => ({ l, on: hovered === l.from || hovered === l.to })).sort((a, b) => Number(a.on) - Number(b.on)).map(({ l, on }) => {
            const y1 = offL + (li.get(l.from) as number) * ROW_HEIGHT + ROW_HEIGHT / 2;
            const y2 = offR + (ri.get(l.to) as number) * ROW_HEIGHT + ROW_HEIGHT / 2;
            const surge = l.prev_requests > 0 && l.requests / l.prev_requests >= 2.5;
            const w = on ? RIBBON_ON : RIBBON;
            return (
              <path
                key={`${l.from}>${l.to}`}
                d={`M 0,${y1} C 36,${y1} 36,${y2} 72,${y2}`}
                fill="none"
                vectorEffect="non-scaling-stroke"
                stroke={on ? "var(--path-highlight)" : strokeOf(l.state, surge)}
                strokeWidth={w}
                strokeOpacity={hovered && !on ? 0.12 : on ? 1 : 0.6}
                strokeDasharray={l.state === "silent" ? "4 3" : undefined}
              />
            );
          })}
        </svg>
      </div>
    );
  };

  const centreCard = (
    <div
      style={{ minHeight: `${Math.min(H, 240)}px`, marginTop: "27px" }}
      className="order-first my-3 flex w-full flex-col justify-between rounded-card border border-line-strong bg-surface-2 p-4 shadow-panel md:order-none md:my-0"
    >
      <div className="space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-accent">{view.eyebrow}</div>
        <h3 className={`break-all text-base font-semibold ${anchorKind === "unknown" ? "text-warn" : "font-mono text-ink"}`}>{view.title}</h3>
        {summary && (
          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 border-t border-line pt-2 text-xs">
            <dt className="text-muted">{t("Requests in window", "Lưu lượng trong kỳ")}</dt>
            <dd className="text-right font-mono font-semibold text-ink">{compact(summary.requests)}</dd>
            <dt className="text-muted">{t("vs previous window", "so với kỳ trước")}</dt>
            <dd className={`text-right font-mono font-semibold ${changePct == null ? (history ? "text-accent" : "text-muted") : changePct < -30 ? "text-bad" : "text-ink"}`}>
              {changePct != null ? `${changePct > 0 ? "+" : ""}${changePct}%` : history ? t("new", "mới") : <span title={t("No data for the previous window yet", "Chưa có dữ liệu kỳ trước")}>—</span>}
            </dd>
            {anchorKind !== "user" && anchorKind !== "unknown" && summary.requests > 0 && (
              <>
                <dt className="text-muted">{t("Unknown users", "User chưa xác định")}</dt>
                <dd className={`text-right font-mono font-semibold ${summary.unknown_requests / summary.requests > 0.4 ? "text-warn" : "text-ink"}`}>
                  {pct(summary.unknown_requests / summary.requests)}
                </dd>
              </>
            )}
            <dt className="text-muted">{view.left.title}</dt>
            <dd className="text-right font-mono font-semibold text-ink">{view.left.rows.length}</dd>
            <dt className="text-muted">{view.right.title}</dt>
            <dd className="text-right font-mono font-semibold text-ink">{view.right.rows.length}</dd>
          </dl>
        )}
        {view.chips.length > 0 && (
          <div className="border-t border-line pt-2">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted">{view.chipsTitle}</div>
            <div className="flex flex-wrap gap-1">
              {view.chips.map((chip) => chip.kind === "ip" ? (
                <span key={chip.key} title={chip.sub} className="max-w-full truncate rounded-full border border-line bg-surface px-2 py-0.5 font-mono text-xs text-muted">{chip.label}</span>
              ) : (
                <button type="button" key={chip.key} onClick={() => openRow(chip)} className="max-w-full truncate rounded-full border border-line bg-surface px-2 py-0.5 text-xs text-ink hover:border-line-strong hover:text-accent">
                  {chip.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {view.link && (
        <div className="mt-3 border-t border-line pt-2">
          <Link to={view.link} className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent hover:underline">
            <span>{t("Open workspace page", "Mở trang workspace")}</span>
            <ExternalLink size={12} />
          </Link>
        </div>
      )}
    </div>
  );

  const pathLabel = isFlow
    ? t("Caller service or source IP → User → API", "Caller service hoặc IP nguồn → User → API")
    : anchorKind === "user" || anchorKind === "unknown"
    ? t("Source IP → User → API", "IP nguồn → User → API")
    : anchorKind === "service"
    ? t("User → Service → API", "User → Service → API")
    : t("Caller service → Service", "Caller service → Service");

  return (
    <Page
      eyebrow={t("Workspace", "Không gian làm việc")}
      title={t("Relationship map", "Bản đồ quan hệ")}
      description={t(
        "Pick a user, service or API and follow its traffic one hop at a time.",
        "Chọn một user, service hoặc API và theo dõi lưu lượng của nó từng bước.",
      )}
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        {/* Left rail */}
        <aside className="w-full shrink-0 space-y-3 rounded-card border border-line bg-surface p-3 lg:w-[260px]">
          {/* Rail Search */}
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2.5 text-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => setSearchFocused(true)}
              onBlur={() => setTimeout(() => setSearchFocused(false), 200)}
              onKeyDown={handleSearchKeyDown}
              placeholder={t("Search estate...", "Tìm kiếm hệ thống...")}
              className="toolbar-control h-8 w-full pl-8 pr-7 text-xs"
              aria-label={t("Search users, APIs, services, and groups", "Tìm user, API, service và nhóm")}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-2 text-muted hover:text-ink"
                aria-label={t("Clear search", "Xóa tìm kiếm")}
              >
                <X size={13} />
              </button>
            )}

            {/* Search Dropdown */}
            {searchFocused && Boolean(debouncedSearch) && (
              <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-md border border-line-strong bg-surface p-1 shadow-pop">
                {searchQueryResult.isLoading ? (
                  <div className="p-2 text-center text-xs text-muted">{t("Searching...", "Đang tìm kiếm...")}</div>
                ) : searchResults.length ? (
                  searchResults.map((item, idx) => (
                    <button
                      type="button"
                      key={`${item.kind}-${item.name}-${idx}`}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        navigateAnchor(item.kind, item.name, item.service, false);
                        setSearchFocused(false);
                      }}
                      className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs ${
                        idx === searchHighlightIndex ? "bg-accent-soft font-semibold text-ink" : "text-ink hover:bg-hover"
                      }`}
                    >
                      <span className="rounded-full border border-line px-1.5 py-0.2 text-[10px] uppercase text-muted">
                        {item.kind}
                      </span>
                      <span className="min-w-0 flex-1 truncate font-mono">{item.name}</span>
                      {item.service && (
                        <span className="truncate text-[10px] text-faint">{item.service}</span>
                      )}
                    </button>
                  ))
                ) : (
                  <div className="p-2 text-center text-xs text-faint">{t("No match", "Không có kết quả")}</div>
                )}
              </div>
            )}
          </div>

          {/* Kind Switcher */}
          <div className="flex rounded-md border border-line bg-surface-2 p-0.5" role="tablist">
            {(["users", "apis", "services"] as const).map((kind) => (
              <button
                type="button"
                key={kind}
                role="tab"
                aria-selected={listKind === kind}
                onClick={() => setListKind(kind)}
                className={`flex-1 rounded py-1 text-center text-xs font-semibold transition-colors ${
                  listKind === kind ? "bg-surface text-ink shadow-panel" : "text-muted hover:text-ink"
                }`}
              >
                {kind === "users" ? t("Users", "User") : kind === "apis" ? "APIs" : t("Services", "Dịch vụ")}
              </button>
            ))}
          </div>

          {/* List items */}
          <div className="max-h-[300px] space-y-0.5 overflow-y-auto lg:max-h-[560px]">
            {/* Fixed entries for Users list */}
            {listKind === "users" && !debouncedSearch && (
              <>
                <button
                  type="button"
                  aria-pressed={anchorKind === "all"}
                  onClick={() => navigateAnchor("all", "", undefined, false)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs transition-colors ${
                    anchorKind === "all" ? "bg-accent-soft font-semibold text-ink" : "text-ink hover:bg-hover"
                  }`}
                >
                  <span className="font-semibold">{t("All traffic", "Toàn bộ lưu lượng")}</span>
                </button>
                <button
                  type="button"
                  aria-pressed={anchorKind === "unknown"}
                  onClick={() => navigateAnchor("unknown", "-anonymous-", undefined, false)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs transition-colors ${
                    anchorKind === "unknown" ? "bg-accent-soft font-semibold text-warn" : "text-warn hover:bg-hover"
                  }`}
                >
                  <span className="font-semibold">{t("Unknown users", "Người dùng chưa xác định")}</span>
                </button>
                <div className="my-1 border-t border-line" />
              </>
            )}

            {listQueryResult.isLoading ? (
              <div className="p-4 text-center text-xs text-muted">{t("Loading...", "Đang tải...")}</div>
            ) : railListItems.length ? (
              railListItems.map((item) => {
                const isItemAnchor =
                  (listKind === "users" && anchorKind === "user" && anchor === item.name) ||
                  (listKind === "services" && anchorKind === "service" && anchor === item.name) ||
                  (listKind === "apis" && anchorKind === "api" && anchor === item.name && anchorService === item.service);

                return (
                  <button
                    type="button"
                    key={`${item.service || ""}:${item.name}`}
                    aria-pressed={isItemAnchor}
                    onClick={() => {
                      if (listKind === "users") navigateAnchor("user", item.name, undefined, false);
                      else if (listKind === "services") navigateAnchor("service", item.name, undefined, false);
                      else navigateAnchor("api", item.name, item.service, false);
                    }}
                    className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs transition-colors ${
                      isItemAnchor ? "bg-accent-soft font-semibold text-ink" : "text-ink hover:bg-hover"
                    }`}
                  >
                    <div className="min-w-0 flex-1 pr-2">
                      <div className="truncate font-mono">{item.name}</div>
                      {listKind === "apis" && item.service && (
                        <div className="truncate text-[10px] text-faint">
                          {item.service}
                          {item.unknown_requests > 0 && item.requests > 0 && (
                            <span className="ml-1 text-warn">
                              · {pct(item.unknown_requests / item.requests)} unk
                            </span>
                          )}
                        </div>
                      )}
                      {listKind === "services" && (item.group || item.module) && (
                        <div className="truncate text-[10px] text-faint">
                          {[item.group, item.module].filter(Boolean).join(" · ")}
                        </div>
                      )}
                    </div>
                    <div className="shrink-0 text-right font-mono text-[11px] text-muted">
                      {listKind === "users" ? `${item.services} svc` : compact(item.requests)}
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="p-3 text-center text-xs text-faint">{t("No matches", "Không tìm thấy")}</div>
            )}
          </div>
          <div className="text-[10px] text-faint">
            {listKind === "users"
              ? t("Sorted by number of services reached", "Sắp xếp theo số service tiếp cận")
              : t("Sorted by total requests", "Sắp xếp theo tổng lượng request")}
          </div>
        </aside>

        {/* Main anchor explorer */}
        <section aria-label={t("Relationship explorer", "Bộ khám phá quan hệ")} data-map-explorer className={`min-w-0 flex-1 rounded-card border border-line bg-surface p-4 transition-opacity ${mainQuery.isFetching || linksQuery.isFetching ? "opacity-75" : "opacity-100"}`}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
            <nav className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs" aria-label="Breadcrumb">
              {trail.map((item, idx) => (
                <span key={`${item.kind}-${item.anchor}-${idx}`} className="flex items-center gap-1.5">
                  <button type="button" onClick={() => restoreTrail(idx)} className="max-w-[16rem] truncate text-muted hover:text-accent hover:underline">
                    {item.kind === "all" ? t("All traffic", "Toàn bộ lưu lượng") : item.kind === "unknown" ? unknownLabel : item.anchor}
                  </button>
                  <span className="text-faint">›</span>
                </span>
              ))}
              <span className="break-all font-mono font-semibold text-ink">{view.title}</span>
            </nav>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-faint">{pathLabel}</span>
              {pinnedRows.map((row) => (
                <span key={row.key} className="inline-flex max-w-[16rem] items-center gap-1.5 rounded-full border border-[color:var(--path-highlight)] px-2.5 py-0.5 text-xs text-ink">
                  <span className="truncate">{t("Pinned", "Đã ghim")}: <strong className="font-mono">{row.label}</strong></span>
                  <button type="button" onClick={() => togglePin(row.key)} className="text-muted hover:text-ink" aria-label={t("Unpin", "Bỏ ghim")}>
                    <X size={12} />
                  </button>
                </span>
              ))}
              {pinnedRows.length > 1 && <button type="button" onClick={clearPins} className="text-xs text-accent hover:underline">{t("Clear pins", "Bỏ ghim tất cả")}</button>}
              {scopeUser && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-0.5 text-xs text-ink">
                  {scopeIsUnknown ? <span>{t("Only unknown users", "Chỉ user chưa xác định")}</span> : <span>{t("Only traffic from", "Chỉ lưu lượng từ")} <strong className="font-mono">{scopeUser}</strong></span>}
                  <button type="button" onClick={removeScopeUser} className="text-muted hover:text-ink" aria-label={t("Show all users", "Hiện tất cả user")}>
                    <X size={12} />
                  </button>
                </span>
              )}
            </div>
          </div>

          {error ? (
            <ErrorState message={error.message} />
          ) : !mainUrl ? (
            <ErrorState message={t("This API link has no service. Pick the API again from the list.", "Liên kết API này thiếu service. Hãy chọn lại API từ danh sách.")} />
          ) : loading ? (
            <Loading />
          ) : (
            <div className="relative">
              {isFlow ? (
                <div className="flex flex-col items-start md:grid md:grid-cols-[minmax(0,1fr)_minmax(40px,80px)_minmax(0,1fr)_48px_minmax(200px,240px)]">
                  {renderColumn(left, "L", shownLeft, offL, t("Caller service, or the source IP when no caller service was recorded", "Caller service, hoặc IP nguồn khi không có caller service"))}
                  {renderPairs()}
                  {renderColumn(right, "R", shownRight, offR)}
                  {renderFan(shownRight, offR, "in")}
                  {centreCard}
                </div>
              ) : (
                <div className="flex flex-col items-start md:grid md:grid-cols-[minmax(0,1fr)_48px_minmax(200px,240px)_48px_minmax(0,1fr)]">
                  {renderColumn(left, "L", shownLeft, offL)}
                  {renderFan(shownLeft, offL, "in")}
                  {centreCard}
                  {renderFan(shownRight, offR, "out")}
                  {renderColumn(right, "R", shownRight, offR)}
                </div>
              )}

              <div className="mt-6 flex flex-wrap items-center gap-4 border-t border-line pt-3 text-xs text-muted">
                <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--path-highlight)" }} />{t("Hovered or pinned path", "Đường đi đang trỏ hoặc đã ghim")}</span>
                <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-accent" />{t("New in this window", "Mới trong kỳ")}</span>
                <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-warn" />{t("Surge (≥ 2.5×)", "Tăng vọt (≥ 2.5×)")}</span>
                <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border border-dashed border-bad" />{t("Silent (dashed)", "Im lặng (nét đứt)")}</span>
                <span className="text-faint">
                  {isFlow
                    ? t("Hover a row to trace its links; click its dot to pin the path. Links to rows under \"more\" are not drawn.", "Di chuột lên một hàng để xem liên kết; nhấp vào chấm để ghim đường đi. Liên kết tới các hàng trong \"mục khác\" không được vẽ.")
                    : t("Hover a row to see its path; click its dot to pin the path and filter the other side; click the name to move the centre there.", "Di chuột lên một hàng để xem đường đi; nhấp vào chấm để ghim và lọc phía còn lại; nhấp vào tên để đặt làm trung tâm.")}
                </span>
              </div>
            </div>
          )}
        </section>
      </div>
    </Page>
  );
}

type RowKind = "user" | "unknown" | "service" | "api" | "ip" | "none";
type MapRow = {
  key: string;
  kind: RowKind;
  name: string;
  label: string;
  sub?: string;
  service?: string;
  requests: number;
  prev_requests: number;
  state: RelState;
  lb?: boolean;
};
type Column = { title: string; rows: MapRow[]; truncated?: boolean; filteredFrom?: number };
type FlowLink = { from: string; to: string; requests: number; prev_requests: number; state: RelState };
type LinksResponse = {
  window: { start_ms: number; end_ms: number; previous_start_ms: number; history_available: boolean };
  links: Array<{
    left_kind: string; left: string; right_kind: string; right: string;
    left_service?: string; right_service?: string;
    requests: number; prev_requests: number; state: RelState;
    is_load_balancer?: boolean; role?: string; role_label?: string;
  }>;
  truncated: boolean;
};

const DOT: Record<RowKind, string> = {
  user: "bg-entity-user",
  unknown: "bg-warn",
  service: "bg-entity-service",
  api: "bg-entity-api",
  ip: "bg-entity-ip",
  none: "bg-faint",
};

function rowKey(kind: RowKind, name: string, service = "") {
  return `${kind}|${service}|${name}`;
}

/** Keep the method and the end of the path, where API names differ. */
export function shortApi(name: string, max = 30) {
  if (name.length <= max) return name;
  const space = name.indexOf(" ");
  const method = space > 0 && space < 8 ? name.slice(0, space + 1) : "";
  const path = name.slice(method.length);
  return `${method}…${path.slice(-(max - method.length - 1))}`;
}

function fromRel(r: RelRow, kind: RowKind): MapRow {
  const sub = kind === "api" ? r.service : kind === "ip" ? (r.role_label || r.role || "") : kind === "service" ? [r.group, r.module].filter(Boolean).join(" · ") : undefined;
  return {
    key: rowKey(kind, r.name, kind === "api" ? r.service || "" : ""),
    kind,
    name: r.name,
    label: kind === "api" ? shortApi(r.name) : r.name,
    sub: sub || undefined,
    service: r.service,
    requests: r.requests,
    prev_requests: r.prev_requests,
    state: r.state,
    lb: kind === "ip" ? Boolean(r.is_load_balancer) : undefined,
  };
}

function aggState(requests: number, previous: number, history: boolean): RelState {
  if (!history) return requests ? "active" : "silent";
  if (requests && !previous) return "new";
  if (!requests && previous) return "silent";
  return "active";
}

function isSurge(row: { requests: number; prev_requests: number }) {
  return row.prev_requests > 0 && row.requests / row.prev_requests >= 2.5;
}

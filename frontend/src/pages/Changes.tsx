import { changeTypes, changeTypeLabel } from "../components/EpisodePrimitives";
import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, ArrowRight, BrainCircuit, ExternalLink, KeyRound, Search, X } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, queryString } from "../api";
import { useFilters } from "../App";
import { canMarkEpisodeExpected, decideEpisode } from "../episodeActions";
import { ErrorState, Loading, Page, Panel, n, pct } from "../components";
import {
  EpisodeBaselineNote,
  EpisodeEvidence,
  EpisodeMetricTable,
  dedupeEpisodeHighlights,
  formatHighlightDelta,
  EpisodePath,
  EpisodeStatusBadge,
  EpisodeWorkflowBadge,
  EpisodeTimeline,
  SemanticAssessmentBadge,
  episodeSearchText,
  episodeTitle,
  episodeFindingRef,
  formatEpisodeTime,
  episodeMatchesView,
  type EpisodeView,
  type Episode,
  type EpisodeResponse,
} from "../components/EpisodePrimitives";
import { InvestigationPanel } from "../components/InvestigationPanel";
import { useI18n } from "../i18n";
import { ChangeVisualEvidence } from "../components/ChangeVisualEvidence";
import { EntityLink } from "../components/EntityLink";
import { entityPath } from "../entityRoutes";

function compactValue(value: unknown, unit?: string | null) {
  if (value == null || value === "") return "—";
  return `${typeof value === "number" ? n(value, 2) : String(value)}${unit ? ` ${unit}` : ""}`;
}

export function ChangesPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();

  // Filters from URL
  const requestedView = params.get("view");
  const view: EpisodeView = requestedView === "all" || requestedView === "reviewed" ? requestedView : "attention";
  const subject = params.get("subject") || "";
  const rawChangeType = params.get("change_type") || "";
  const selectedTypes = useMemo(
    () => rawChangeType.split(",").map((s) => s.trim()).filter(Boolean),
    [rawChangeType],
  );
  const assessmentFilter = params.get("assessment") || "all";
  const search = params.get("q") || "";
  const sort = params.get("sort") || "priority";
  const where = params.get("where") || "";

  const [page, setPage] = useState(0);

  // Load episodes
  const qs = queryString(filters, { limit: "500" });
  const query = useQuery({
    queryKey: ["changes", qs],
    queryFn: () => api<EpisodeResponse>(`/api/v1/changes?${qs}`),
    refetchInterval: 60_000,
  });
  const items = query.data?.items || [];

  // Load services catalog for groups
  const servicesQuery = useQuery({
    queryKey: ["services-catalog-for-changes"],
    queryFn: () => api<{ items: Array<{ name: string; service_group?: string }> }>("/api/v1/services?limit=500"),
  });

  const serviceToGroup = useMemo(() => {
    const map = new Map<string, string>();
    (servicesQuery.data?.items || []).forEach((s) => {
      map.set(s.name, s.service_group || "Core");
    });
    return map;
  }, [servicesQuery.data]);

  const distinctGroups = useMemo(() => {
    return new Set((servicesQuery.data?.items || []).map((s) => s.service_group || "Core"));
  }, [servicesQuery.data]);

  const hasMultipleGroups = distinctGroups.size > 1;

  // Right panel "Where changes are" mode: group | service | user
  const [whereKindParam, whereNameParam] = where.split(":");
  const [whereTab, setWhereTab] = useState<"group" | "service" | "user">(() => {
    if (whereKindParam === "group" && hasMultipleGroups) return "group";
    if (whereKindParam === "user") return "user";
    return "service";
  });

  useEffect(() => {
    if (!hasMultipleGroups && whereTab === "group") {
      setWhereTab("service");
    }
  }, [hasMultipleGroups, whereTab]);

  function update(key: string, value: string) {
    setPage(0);
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  }

  function toggleType(type: string) {
    setPage(0);
    const nextTypes = selectedTypes.includes(type)
      ? selectedTypes.filter((t) => t !== type)
      : [...selectedTypes, type];
    update("change_type", nextTypes.join(","));
  }

  function addType(type: string) {
    if (!selectedTypes.includes(type)) {
      setPage(0);
      update("change_type", [...selectedTypes, type].join(","));
    }
  }

  const typeOptions = useMemo(
    () => [...new Set((query.data?.items || []).flatMap(changeTypes))].sort(),
    [query.data?.items],
  );

  // Filter episodes
  const filtered = useMemo(() => {
    return (query.data?.items || []).filter((episode) => {
      if (subject && episode.subject.type !== subject) return false;
      if (selectedTypes.length > 0) {
        const epTypes = changeTypes(episode);
        if (!selectedTypes.some((st) => epTypes.includes(st))) return false;
      }
      if (
        search &&
        !`${episodeSearchText(episode)} ${changeTypes(episode).join(" ")}`
          .toLowerCase()
          .includes(search.toLowerCase())
      ) {
        return false;
      }
      const assessment = episode.semantic_assessment;
      const status = assessment?.status || "not_evaluated";
      if (assessmentFilter === "high_confidence") {
        if (status !== "succeeded" || (assessment?.abnormal_probability ?? 0) < 0.8) return false;
      } else if (assessmentFilter === "investigate") {
        if (status !== "succeeded" || !["investigate", "urgent"].includes(assessment?.priority || "")) return false;
      } else if (assessmentFilter === "watch") {
        if (status !== "succeeded" || assessment?.priority !== "watch") return false;
      } else if (assessmentFilter !== "all") {
        if (status !== assessmentFilter) return false;
      }

      // Where filter
      if (whereKindParam && whereNameParam) {
        if (whereKindParam === "service") {
          const isMatch =
            episode.subject.name === whereNameParam ||
            episode.context.target === whereNameParam ||
            episode.context.caller === whereNameParam;
          if (!isMatch) return false;
        } else if (whereKindParam === "user") {
          const isMatch =
            episode.subject.name === whereNameParam ||
            episode.episode_key?.includes(`user:${whereNameParam}`) ||
            episode.context.caller === whereNameParam;
          if (!isMatch) return false;
        } else if (whereKindParam === "group") {
          const svc =
            episode.subject.type === "service"
              ? episode.subject.name
              : episode.context.target || episode.context.caller || "";
          const grp = serviceToGroup.get(svc) || "Core";
          if (grp !== whereNameParam) return false;
        }
      }

      return true;
    });
  }, [
    query.data?.items,
    subject,
    selectedTypes,
    search,
    assessmentFilter,
    whereKindParam,
    whereNameParam,
    serviceToGroup,
  ]);

  const rank: Record<Episode["state"], number> = {
    critical: 4,
    needs_attention: 3,
    watch: 2,
    changed: 1,
    expected: 0,
  };

  const episodes = filtered
    .filter((episode) => episodeMatchesView(episode, view))
    .sort((a, b) => (sort === "priority" ? rank[b.state] - rank[a.state] : 0) || b.last_seen_at - a.last_seen_at);

  const currentPage = Math.min(page, Math.max(0, Math.ceil(episodes.length / 25) - 1));
  const visible = episodes.slice(currentPage * 25, (currentPage + 1) * 25);
  const detailSearch = `?${queryString(filters, {
    view,
    subject,
    change_type: rawChangeType,
    assessment: assessmentFilter,
    q: search,
    sort,
    where,
  })}`;

  function reset() {
    setPage(0);
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        for (const key of ["subject", "change_type", "assessment", "q", "sort", "where"]) {
          next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  }

  const hasFilters = Boolean(
    search || selectedTypes.length > 0 || subject || assessmentFilter !== "all" || where || sort !== "priority",
  );

  // Critical count
  const criticalCount = query.data
    ? items.filter((episode) => episode.state === "critical" && episode.status !== "resolved").length
    : "—";

  // Where stats calculation (from all matching loaded items)
  const whereStats = useMemo(() => {
    const counts = new Map<string, { total: number; attention: number }>();
    const tab = whereTab;

    items.forEach((ep) => {
      let key = "";
      if (tab === "service") {
        key = ep.subject.type === "service" ? ep.subject.name : ep.context.target || ep.context.caller || "";
      } else if (tab === "user") {
        if (ep.subject.type === "user") {
          key = ep.subject.name;
        } else if (ep.episode_key?.startsWith("user:")) {
          key = ep.episode_key.split(":")[1] || "";
        }
      } else if (tab === "group") {
        const svc = ep.subject.type === "service" ? ep.subject.name : ep.context.target || ep.context.caller || "";
        key = serviceToGroup.get(svc) || "Core";
      }

      if (!key) return;
      const current = counts.get(key) || { total: 0, attention: 0 };
      current.total += 1;
      if (episodeMatchesView(ep, "attention")) {
        current.attention += 1;
      }
      counts.set(key, current);
    });

    const list = Array.from(counts.entries()).map(([name, stat]) => ({
      name,
      total: stat.total,
      attention: stat.attention,
    }));
    list.sort((a, b) => b.total - a.total);
    const max = list.length ? Math.max(...list.map((x) => x.total)) : 1;
    return { list, max };
  }, [items, whereTab, serviceToGroup]);

  // Explore on map URL generator
  function getMapAnchorUrl(episode: Episode) {
    const p = new URLSearchParams();
    p.set("start", filters.start);
    p.set("end", filters.end);
    if (filters.timezone && filters.timezone !== "local") p.set("timezone", filters.timezone);

    let user: string | null = null;
    if (episode.subject.type === "user") {
      user = episode.subject.name;
    } else if (episode.episode_key?.startsWith("user:")) {
      const parts = episode.episode_key.split(":");
      if (parts[1]) user = parts[1];
    }

    if (episode.subject.type === "user") {
      p.set("anchor_kind", "user");
      p.set("anchor", episode.subject.name);
    } else if (episode.context.operation) {
      p.set("anchor_kind", "api");
      p.set("anchor", episode.context.operation);
      p.set("anchor_service", episode.context.target || episode.subject.name);
      if (user) p.set("scope_user", user);
    } else {
      p.set("anchor_kind", "service");
      p.set("anchor", episode.subject.name);
      if (user) p.set("scope_user", user);
    }
    return `/workspace/map?${p.toString()}`;
  }

  return (
    <Page
      eyebrow={t("Changes")}
      title={t("Changes")}
      description={t(
        "Triage changes, compare the evidence, and investigate.",
        "Phân loại thay đổi, đối chiếu bằng chứng và điều tra.",
      )}
    >
      <div className="flex flex-col gap-4 xl:grid xl:grid-cols-[200px_minmax(0,1fr)_280px] xl:items-start">
        {/* Left Rail */}
        <aside className="w-full space-y-4 rounded-card border border-line bg-surface p-3 text-xs">
          {/* Critical Count */}
          <div className="flex items-center justify-between border-b border-line pb-2.5">
            <span className="text-[11px] text-muted">{t("Critical")}</span>
            <strong className="font-mono text-bad">{criticalCount}</strong>
          </div>

          {/* View Radio List */}
          <div className="space-y-1">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">
              {t("View", "Chế độ xem")}
            </div>
            {(
              [
                ["attention", t("Needs attention")],
                ["all", t("All", "Tất cả")],
                ["reviewed", t("Reviewed", "Đã xem xét")],
              ] as const
            ).map(([val, label]) => {
              const count = query.data ? filtered.filter((ep) => episodeMatchesView(ep, val)).length : "—";
              const isSelected = view === val;
              return (
                <button
                  type="button"
                  key={val}
                  onClick={() => update("view", val)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1 text-left ${
                    isSelected ? "bg-accent-soft font-semibold text-ink" : "text-muted hover:bg-hover hover:text-ink"
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`h-2 w-2 rounded-full border ${
                        isSelected ? "border-accent bg-accent" : "border-line-strong"
                      }`}
                    />
                    <span>{label}</span>
                  </span>
                  <span className="font-mono text-[11px] text-faint">{count}</span>
                </button>
              );
            })}
          </div>

          {/* Change Types Checklist */}
          {typeOptions.length > 0 && (
            <div className="space-y-1 border-t border-line pt-2.5">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">
                {t("Change type", "Loại thay đổi")}
              </div>
              <div className="max-h-48 space-y-0.5 overflow-y-auto pr-1">
                {typeOptions.map((type) => {
                  const checked = selectedTypes.includes(type);
                  const count = items.filter((ep) => changeTypes(ep).includes(type)).length;
                  return (
                    <label
                      key={type}
                      className="flex cursor-pointer items-center justify-between rounded px-1.5 py-1 hover:bg-hover text-ink"
                    >
                      <span className="flex min-w-0 items-center gap-1.5 pr-1">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleType(type)}
                          className="rounded border-line"
                        />
                        <span className="truncate text-xs">{changeTypeLabel(type, t)}</span>
                      </span>
                      <span className="font-mono text-[11px] text-faint">{count}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          {/* Subject Filter */}
          <div className="space-y-1 border-t border-line pt-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">
              {t("Subject", "Đối tượng")}
            </div>
            <div className="grid grid-cols-3 gap-1 rounded-md border border-line bg-surface-2 p-0.5 text-center">
              {[
                ["", t("All", "Tất cả")],
                ["service", "Service"],
                ["user", "User"],
              ].map(([val, label]) => (
                <button
                  type="button"
                  key={val}
                  onClick={() => update("subject", val)}
                  className={`rounded py-1 text-xs font-semibold ${
                    subject === val ? "bg-surface text-ink shadow-panel" : "text-muted hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* AI Assessment */}
          <div className="space-y-1 border-t border-line pt-2.5">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">
              {t("AI assessment", "Đánh giá AI")}
            </div>
            <select
              aria-label={t("AI assessment filter", "Lọc đánh giá AI")}
              value={assessmentFilter}
              onChange={(e) => update("assessment", e.target.value)}
              className="toolbar-control h-8 w-full px-2 text-xs"
            >
              <option value="all">{t("AI assessment: All", "Đánh giá AI: Tất cả")}</option>
              <option value="high_confidence">{t("High confidence", "Độ tin cậy cao")}</option>
              <option value="investigate">{t("Investigate", "Điều tra")}</option>
              <option value="watch">{t("Watch", "Theo dõi")}</option>
              <option value="pending">{t("Pending", "Đang chờ")}</option>
              <option value="not_evaluated">{t("Not evaluated", "Chưa đánh giá")}</option>
              <option value="failed">{t("AI unavailable", "AI không khả dụng")}</option>
              <option value="stale">{t("AI stale", "AI đã cũ")}</option>
            </select>
          </div>

          {/* Active Where Chip */}
          {where && (
            <div className="border-t border-line pt-2.5">
              <div className="mb-1 text-[10px] font-semibold uppercase text-muted">
                {t("Active filter", "Bộ lọc đang chọn")}
              </div>
              <div className="flex items-center justify-between rounded bg-accent-soft px-2 py-1 text-xs text-ink font-mono">
                <span className="truncate">{where}</span>
                <button
                  type="button"
                  onClick={() => update("where", "")}
                  className="text-muted hover:text-ink"
                  aria-label={t("Remove filter", "Gỡ bộ lọc")}
                >
                  <X size={12} />
                </button>
              </div>
            </div>
          )}

          {/* Clear Filters */}
          {hasFilters && (
            <div className="border-t border-line pt-2">
              <button
                type="button"
                onClick={reset}
                className="w-full text-left text-xs font-semibold text-accent hover:underline"
              >
                {t("Clear filters", "Xóa bộ lọc")}
              </button>
            </div>
          )}
        </aside>

        {/* Central List */}
        <section className="min-w-0 rounded-card border border-line bg-surface" aria-label={t("Change episodes", "Các thay đổi")}>
          {/* Top List Controls */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
            <label className="relative min-w-0 flex-[1_1_220px]">
              <span className="sr-only">{t("Search changes", "Tìm thay đổi")}</span>
              <Search size={13} className="absolute left-2.5 top-2.5 text-muted" />
              <input
                value={search}
                onChange={(e) => update("q", e.target.value)}
                placeholder={t("Search changes...", "Tìm thay đổi...")}
                className="toolbar-control h-8 w-full pl-8 pr-2 text-xs"
              />
            </label>

            <div className="flex items-center gap-2">
              <select
                aria-label={t("Sort", "Sắp xếp")}
                value={sort}
                onChange={(e) => update("sort", e.target.value)}
                className="toolbar-control h-8 px-2 text-xs"
              >
                <option value="priority">{t("Priority first", "Ưu tiên mức độ")}</option>
                <option value="recent">{t("Latest first", "Mới nhất trước")}</option>
              </select>
            </div>
          </div>

          <div className="border-b border-line px-3 py-1.5 text-[11px] text-muted">
            {episodes.length} {t("changes", "thay đổi")} ·{" "}
            {sort === "priority"
              ? t("ranked by priority", "xếp theo mức ưu tiên")
              : t("latest first", "mới nhất trước")}
          </div>

          {/* List Content */}
          {query.isLoading ? (
            <Loading />
          ) : query.error ? (
            <ErrorState message={query.error.message} />
          ) : visible.length ? (
            <div className="divide-y divide-line">
              {visible.map((episode) => {
                const highlight = episode.highlights.find(
                  (item) => item.before != null && item.after != null && typeof item.before === "number" && typeof item.after === "number",
                );
                const numBefore = highlight ? Number(highlight.before) : 0;
                const numAfter = highlight ? Number(highlight.after) : 0;
                const maxVal = Math.max(numBefore, numAfter, 0.001);
                const beforeW = highlight ? Math.max(4, (numBefore / maxVal) * 80) : 0;
                const afterW = highlight ? Math.max(4, (numAfter / maxVal) * 80) : 0;

                const types = changeTypes(episode);
                const mapUrl = getMapAnchorUrl(episode);

                // Build path nodes
                const targetService =
                  episode.context.target || (episode.subject.type === "service" ? episode.subject.name : "");

                return (
                  <article key={episode.id} className="grid grid-cols-1 gap-3 p-3.5 hover:bg-hover lg:grid-cols-[minmax(0,1fr)_auto]">
                    {/* Left Column */}
                    <div className="space-y-1.5 min-w-0">
                      {/* Line 1: Badges + Title */}
                      <div className="flex flex-wrap items-center gap-2">
                        <EpisodeStatusBadge episode={episode} />
                        <EpisodeWorkflowBadge episode={episode} />
                        <EntityLink
                          entity={{ kind: "change", id: episode.id }}
                          search={detailSearch}
                          className="font-semibold text-xs leading-5 text-ink hover:underline"
                        >
                          {episodeTitle(episode, t)}
                        </EntityLink>
                      </div>

                      {/* Line 2: Summary */}
                      <p className="truncate text-xs text-muted leading-relaxed">
                        {episode.summary || episode.explanation}
                      </p>

                      {/* Line 3: Path chips joined by arrows */}
                      <div className="flex flex-wrap items-center gap-1.5 text-xs">
                        {episode.subject.type === "user" && (
                          <>
                            <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-entity-user">
                              {episode.subject.name}
                            </span>
                            <span className="text-faint">→</span>
                          </>
                        )}
                        {episode.context.caller && (
                          <>
                            <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-entity-service">
                              {episode.context.caller}
                            </span>
                            <span className="text-faint">→</span>
                          </>
                        )}
                        {targetService && targetService !== episode.context.caller && (
                          <>
                            <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-entity-service">
                              {targetService}
                            </span>
                            {episode.context.operation && <span className="text-faint">→</span>}
                          </>
                        )}
                        {episode.context.operation && (
                          <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-entity-api">
                            {episode.context.operation}
                          </span>
                        )}
                        {episode.context.source_ip && (
                          <>
                            <span className="text-faint">·</span>
                            <span className="rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-entity-ip">
                              {episode.context.source_ip}
                            </span>
                          </>
                        )}
                      </div>

                      {/* Line 4: Type chips, signal count, assessment badge */}
                      <div className="flex flex-wrap items-center gap-1.5 pt-0.5 text-[11px] text-muted">
                        {types.map((type) => (
                          <button
                            key={type}
                            type="button"
                            onClick={() => addType(type)}
                            className="rounded-sm border border-line bg-surface px-1.5 py-0.5 text-[10px] text-muted hover:border-line-strong hover:text-ink"
                            title={t("Filter by this type", "Lọc theo loại này")}
                          >
                            {changeTypeLabel(type, t)}
                          </button>
                        ))}
                        <span>
                          · {episode.signal_count} {t("signals", "tín hiệu")}
                        </span>
                        {episode.semantic_assessment &&
                          episode.semantic_assessment.status !== "not_evaluated" && (
                            <SemanticAssessmentBadge assessment={episode.semantic_assessment} />
                          )}
                      </div>

                      {/* Actions */}
                      <div className="flex flex-wrap items-center gap-3 pt-1 text-xs">
                        <EntityLink
                          entity={{ kind: "change", id: episode.id }}
                          search={detailSearch}
                          className="font-semibold text-ink hover:underline"
                        >
                          {t("View details", "Xem chi tiết")}
                        </EntityLink>
                        <button
                          type="button"
                          onClick={() =>
                            nav(`${entityPath({ kind: "change", id: episode.id })}${detailSearch}#ai-investigation`)
                          }
                          className="font-semibold text-entity-user hover:underline"
                        >
                          {t("Investigate", "Điều tra")}
                        </button>
                        <Link
                          to={mapUrl}
                          className="font-semibold text-accent hover:underline inline-flex items-center gap-1"
                        >
                          <span>{t("Explore map →", "Khám phá bản đồ →")}</span>
                        </Link>
                      </div>
                    </div>

                    {/* Right Column: Mini bars & Last seen */}
                    <div className="flex flex-col items-start lg:items-end justify-between gap-2 border-t border-line pt-2 lg:border-t-0 lg:pt-0">
                      {highlight ? (
                        <div className="space-y-1">
                          <div className="grid grid-cols-[auto_80px_auto] items-center gap-1.5 font-mono text-[11px]">
                            <span className="text-[10px] text-faint">{t("before", "trước")}</span>
                            <div className="h-1.5 w-20 overflow-hidden rounded bg-surface-2">
                              <div
                                className="h-full bg-line-strong"
                                style={{ width: `${beforeW}px` }}
                              />
                            </div>
                            <span className="text-right text-muted">
                              {compactValue(highlight.before, highlight.unit)}
                            </span>

                            <span className="text-[10px] text-faint">{t("now", "hiện tại")}</span>
                            <div className="h-1.5 w-20 overflow-hidden rounded bg-surface-2">
                              <div
                                className="h-full"
                                style={{ width: `${afterW}px`, background: "var(--accent)" }}
                              />
                            </div>
                            <span className="text-right font-semibold text-ink">
                              {compactValue(highlight.after, highlight.unit)}
                            </span>
                          </div>
                          {highlight.delta != null && (
                            <div className="text-right font-mono text-[10px] text-warn">
                              {formatHighlightDelta(highlight, t)}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-muted">{t("See evidence", "Xem bằng chứng")}</span>
                      )}

                      <div className="text-[11px] text-faint">
                        {formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-muted">
              {t("No changes match the selected view.", "Không có thay đổi phù hợp với bộ lọc.")}
            </div>
          )}

          {/* Pager */}
          {query.data && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-[11px] text-muted">
              <span>
                {episodes.length ? currentPage * 25 + 1 : 0}–{Math.min((currentPage + 1) * 25, episodes.length)} /{" "}
                {episodes.length} {t("matching", "phù hợp")} · {items.length}/{query.data.total}{" "}
                {t("episodes loaded", "thay đổi đã tải")}
              </span>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                  className="disabled:opacity-40 hover:text-ink font-semibold"
                >
                  {t("Previous", "Trước")}
                </button>
                <span className="font-mono">
                  {currentPage + 1} / {Math.max(1, Math.ceil(episodes.length / 25))}
                </span>
                <button
                  type="button"
                  disabled={(currentPage + 1) * 25 >= episodes.length}
                  onClick={() => setPage(currentPage + 1)}
                  className="disabled:opacity-40 hover:text-ink font-semibold"
                >
                  {t("Next", "Sau")}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* Right Panel "Where changes are" */}
        <aside className="w-full space-y-3 rounded-card border border-line bg-surface p-3 text-xs">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">
            {t("Where changes are", "Nơi xuất hiện thay đổi")}
          </div>

          {/* Segmented control: Group | Service | User */}
          <div className="flex rounded-md border border-line bg-surface-2 p-0.5">
            {hasMultipleGroups && (
              <button
                type="button"
                onClick={() => setWhereTab("group")}
                className={`flex-1 rounded py-1 text-center text-xs font-semibold ${
                  whereTab === "group" ? "bg-surface text-ink shadow-panel" : "text-muted hover:text-ink"
                }`}
              >
                {t("Group", "Nhóm")}
              </button>
            )}
            <button
              type="button"
              onClick={() => setWhereTab("service")}
              className={`flex-1 rounded py-1 text-center text-xs font-semibold ${
                whereTab === "service" ? "bg-surface text-ink shadow-panel" : "text-muted hover:text-ink"
              }`}
            >
              Service
            </button>
            <button
              type="button"
              onClick={() => setWhereTab("user")}
              className={`flex-1 rounded py-1 text-center text-xs font-semibold ${
                whereTab === "user" ? "bg-surface text-ink shadow-panel" : "text-muted hover:text-ink"
              }`}
            >
              User
            </button>
          </div>

          {/* Rows table */}
          <div className="max-h-[500px] overflow-y-auto divide-y divide-line">
            {whereStats.list.length ? (
              whereStats.list.map((item) => {
                const targetWhere = `${whereTab}:${item.name}`;
                const isSelected = where === targetWhere;
                const barWidth = Math.max(3, (item.total / whereStats.max) * 100);

                return (
                  <button
                    type="button"
                    key={item.name}
                    onClick={() => update("where", isSelected ? "" : targetWhere)}
                    className={`flex w-full items-center justify-between gap-2 py-2 px-1 text-left transition-colors ${
                      isSelected ? "bg-accent-soft font-semibold text-ink" : "text-ink hover:bg-hover"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-mono text-xs" title={item.name}>
                        {item.name}
                      </div>
                      <div className="mt-1 h-1 w-full overflow-hidden rounded bg-surface-2">
                        <div
                          className="h-full"
                          style={{
                            width: `${barWidth}%`,
                            background: isSelected ? "var(--accent)" : "var(--warn)",
                          }}
                        />
                      </div>
                    </div>

                    <div className="shrink-0 text-right font-mono text-xs">
                      <div>{item.total}</div>
                      {item.attention > 0 && (
                        <div className="text-[10px] text-warn">
                          {item.attention} {t("attn", "cần chú ý")}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="p-3 text-center text-xs text-faint">{t("No data", "Không có dữ liệu")}</div>
            )}
          </div>
          <div className="text-[10px] text-faint">
            {t("Click any item to filter changes", "Nhấp vào mục bất kỳ để lọc thay đổi")}
          </div>
        </aside>
      </div>
    </Page>
  );
}

export function ChangeDetailPage() {
  const { id = "" } = useParams();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const aiSectionRef = useRef<HTMLDivElement>(null);
  const query = useQuery({ queryKey: ["change-episode", id, filters], queryFn: () => api<Episode>(`/api/v1/changes/${encodeURIComponent(id)}?${queryString(filters)}`) });
  const decision = useMutation({
    mutationFn: (action: "expected" | "investigate" | "resolve") => {
      if (!query.data) throw new Error("No change episode selected");
      return decideEpisode(query.data, action);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["changes"] });
      queryClient.invalidateQueries({ queryKey: ["change-episode", id] });
    },
  });

  useEffect(() => {
    if (query.data && location.hash === "#ai-investigation") {
      requestAnimationFrame(() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }, [location.hash, query.data]);

  if (query.isLoading) return <div className="console-page mx-auto max-w-[1640px] px-3 py-4 md:px-5"><Loading /></div>;
  if (query.error || !query.data) return <div className="console-page mx-auto max-w-[1640px] px-3 py-4 md:px-5"><ErrorState message={query.error?.message || t("Change episode not found", "Không tìm thấy episode thay đổi")} /></div>;

  const episode = query.data;
  const findingRef = episodeFindingRef(episode);
  const visibleHighlights = dedupeEpisodeHighlights(episode);
  const primaryHighlight = visibleHighlights.find((item) => item.before != null && item.after != null) || visibleHighlights[0];
  const contextItems = [
    [t("Subject", "Đối tượng"), episode.subject.name],
    [t("Target Service", "Target Service"), episode.context.target || "—"],
    [t("API / Operation", "API / Operation"), episode.context.operation || "—"],
  ];
  return (
    <Page eyebrow={t("Change detail", "Chi tiết thay đổi")} title={episodeTitle(episode, t)} description={t("Review the detected signals, assessment and observed changes.", "Xem tín hiệu đã phát hiện, đánh giá và thay đổi quan sát được.")} actions={<div className="flex flex-wrap gap-2"><button type="button" onClick={() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="btn border-entity-user/50 text-entity-user"><BrainCircuit size={13} />{t("Investigate", "Điều tra")}</button><button type="button" onClick={() => nav(`/changes?${queryString(filters, { view: searchParams.get("view") || "attention" })}`)} className="btn"><ArrowLeft size={13} />{t("All changes", "Tất cả thay đổi")}</button></div>}>
      <section className={`border-l-4 ${episode.state === "critical" ? "border-bad" : episode.state === "needs_attention" ? "border-warn" : "border-line-strong"} panel p-4 md:p-5`} aria-label={t("Change summary", "Tóm tắt thay đổi")}>
        <div className="flex flex-wrap items-center gap-2"><EpisodeStatusBadge episode={episode} /><EpisodeWorkflowBadge episode={episode} /><span className="text-[11px] text-muted">{formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</span></div>
        <h2 className="mt-4 max-w-4xl text-xl font-semibold leading-7 text-ink">{episodeTitle(episode, t)}</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-muted">{episode.explanation}</p>
        <div className="mt-4"><EpisodePath episode={episode} compact /></div>
        <div className="mt-5 grid gap-px overflow-hidden border border-line bg-line sm:grid-cols-3">{contextItems.map(([label, value]) => <div key={label} className="bg-surface px-3 py-2.5"><div className="text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</div><div className="mt-1 truncate font-mono text-xs text-ink">{value}</div></div>)}</div>
      </section>

      <ChangeVisualEvidence episode={episode} filters={filters} />

      <section className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,.6fr)]">
        <Panel title={t("Observed changes", "Thay đổi quan sát được")} subtitle={t("Saved detector comparison. Service traffic uses a five-minute observation and a learned baseline; merged episodes retain the latest detector values.", "So sánh detector đã lưu. Lưu lượng Service dùng quan sát năm phút và Baseline đã học; episode gộp giữ giá trị detector mới nhất.")}>
          {primaryHighlight ? <div className="grid gap-4 p-4 sm:grid-cols-[1fr_auto_1fr] sm:items-center"><div><div className="text-[10px] font-semibold uppercase tracking-wide text-muted">{t("Baseline", "Baseline")}</div><div className="mt-2 font-mono text-2xl text-muted">{compactValue(primaryHighlight.before, primaryHighlight.unit)}</div></div><div className="text-center text-2xl text-warn">→</div><div><div className="text-[10px] font-semibold uppercase tracking-wide text-warn">{t("Observed", "Quan sát được")}</div><div className="mt-2 font-mono text-2xl font-semibold text-ink">{compactValue(primaryHighlight.after, primaryHighlight.unit)}</div>{primaryHighlight.delta != null && <div className="mt-1 font-mono text-xs text-warn">{formatHighlightDelta(primaryHighlight, t)}</div>}</div></div> : <div className="p-4 text-sm text-muted">{t("No primary metric is available. Use the evidence below.", "Chưa có chỉ số chính. Xem bằng chứng bên dưới.")}</div>}
          <EpisodeMetricTable episode={episode} />
        </Panel>
        <Panel title={t("When it happened", "Thời điểm xảy ra")}><div className="space-y-3 p-4 text-xs"><div><div className="text-[10px] uppercase tracking-wide text-muted">{t("Started", "Bắt đầu")}</div><div className="mt-1 font-mono text-ink">{formatEpisodeTime(episode.started_at, true, filters.timezone)}</div></div><div><div className="text-[10px] uppercase tracking-wide text-muted">{t("Last observed", "Quan sát gần nhất")}</div><div className="mt-1 font-mono text-ink">{formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</div></div><div><div className="text-[10px] uppercase tracking-wide text-muted">{t("Detected signals", "Tín hiệu đã phát hiện")}</div><div className="mt-1 font-mono text-xl text-ink font-semibold">{episode.signal_count}</div></div></div></Panel>
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,.7fr)]">
        <div className="space-y-4"><Panel title={t("Signal timeline", "Dòng thời gian tín hiệu")} subtitle={t("What was observed, in order.", "Những gì được quan sát theo thứ tự.")}><EpisodeTimeline episode={episode} timezone={filters.timezone} /></Panel><Panel title={t("Relationship path", "Đường quan hệ")}><div className="p-4"><EpisodePath episode={episode} /></div></Panel></div>
        <div className="space-y-4"><Panel title={t("Why this is a change", "Vì sao đây là thay đổi")}><div className="space-y-3 p-4">{(episode.abnormality?.reasons || [episode.explanation]).map((reason) => <div key={reason} className="border-l-2 border-line-strong pl-3 text-xs leading-5 text-ink">{reason}</div>)}</div></Panel><Panel title={t("Detected signals", "Tín hiệu đã phát hiện")}><EpisodeEvidence episode={episode} /></Panel><EpisodeBaselineNote episode={episode} /></div>
      </div>

      <Panel title={t("Next action", "Thao tác tiếp theo")} subtitle={t("Choose the operator outcome for this change.", "Chọn cách xử lý cho thay đổi này.")} className="mt-4"><div className="flex flex-wrap gap-2 p-3"><button type="button" onClick={() => nav(`/traces?${queryString(filters, { principal: episode.subject.type === "user" ? episode.subject.name : undefined, service: episode.context.target || undefined })}`)} className="btn"><Activity size={13} />{t("View related traces", "Xem Trace liên quan")}</button><EntityLink entity={episode.subject.type === "user" ? { kind: "user", principal: episode.subject.name } : { kind: "service", name: episode.subject.name }} className="btn"><ArrowRight size={13} />{t(`Open ${episode.subject.type}`, `Mở ${episode.subject.type}`)}</EntityLink><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("expected")} className="btn text-good">{canMarkEpisodeExpected(episode) ? t("Mark expected", "Đánh dấu dự kiến") : t("Suppress", "Ẩn finding")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("investigate")} className="btn text-warn">{t("Keep monitoring", "Tiếp tục theo dõi")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("resolve")} className="btn">{t("Resolve", "Đã xử lý")}</button></div>{decision.isError && <div className="border-t border-line p-3 text-xs text-bad">{decision.error instanceof Error ? decision.error.message : t("Decision could not be saved", "Không thể lưu quyết định")}</div>}{decision.isSuccess && <div className="border-t border-line p-3 text-xs text-good">{t("Decision saved", "Đã lưu quyết định")}</div>}</Panel>

      <div id="ai-investigation" ref={aiSectionRef} className="scroll-mt-20 mt-4"><details className="panel"><summary className="flex cursor-pointer list-none items-center justify-between p-4 text-sm font-semibold text-ink"><span className="flex items-center gap-2"><BrainCircuit size={15} className="text-entity-user" />{t("Technical AI investigation", "Điều tra AI kỹ thuật")}</span><span className="text-[11px] font-normal text-muted">{t("Optional", "Tùy chọn")}</span></summary><div className="border-t border-line">{findingRef ? <InvestigationPanel findingRef={findingRef} initialScore={episode.score} initialSeverity={episode.severity} initialExplanation={episode.explanation} initialEntityId={episode.context.target || episode.subject.name} /> : <div className="p-4 text-xs text-muted">{t("AI analysis is unavailable because this episode has no source finding.", "Không thể phân tích AI vì episode chưa có finding nguồn.")}</div>}</div></details></div>
    </Page>
  );
}

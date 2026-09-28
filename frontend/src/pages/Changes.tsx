import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, ArrowRight, BrainCircuit, Search } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, queryString } from "../api";
import { useFilters } from "../App";
import { canMarkEpisodeExpected, decideEpisode } from "../episodeActions";
import { ErrorState, Loading, Page, Panel, n } from "../components";
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
  SemanticAssessmentSummary,
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

function changeTypes(episode: Episode): string[] {
  return [...new Set([...(episode.signals || []).map((signal) => signal.type), ...episode.evidence.map((evidence) => evidence.detector)].filter(Boolean).map((type) => type.toLowerCase()))];
}

function changeTypeLabel(type: string, t: (key: string, fallback?: string) => string) {
  const labels: Record<string, [string, string]> = {
    traffic_spike: ["Traffic spike", "Lưu lượng tăng đột biến"], traffic_drop: ["Traffic drop", "Lưu lượng giảm"],
    latency: ["Latency shift", "Biến động latency"], error_rate: ["Error rate increase", "Tỷ lệ lỗi tăng"],
    unusual_access: ["Unusual access", "Truy cập bất thường"], unusual_time: ["Unusual execution time", "Thời gian thực thi bất thường"],
    new_service_edge: ["New service relationship", "Quan hệ Service mới"], new_principal_edge: ["New credential relationship", "Quan hệ tài khoản mới"],
    user_new_source_ip: ["New source IP", "IP nguồn mới"], ip_new_user: ["New user on IP", "User mới trên IP"],
    operation_mix_shift: ["Operation mix shift", "Thay đổi cơ cấu API"], caller_principal_switch: ["Credential switch", "Thay đổi tài khoản gọi"],
    target_fanout_surge: ["Target fanout surge", "Số đích truy cập tăng"], source_fanout_surge: ["Source fanout surge", "Số nguồn truy cập tăng"],
    principal_rate_surge: ["User traffic surge", "Lưu lượng User tăng"], auth_failure_burst: ["Authentication failures", "Lỗi xác thực tăng"],
    failure_then_success: ["Failure then success", "Thành công sau nhiều lần lỗi"], source_identity_fanout: ["Multiple source identities", "Nhiều danh tính từ một nguồn"],
  };
  const label = labels[type];
  return label ? t(...label) : t(type, type.replace(/_/g, " "));
}

function compactValue(value: unknown, unit?: string | null) {
  if (value == null || value === "") return "—";
  return `${typeof value === "number" ? n(value, 2) : String(value)}${unit ? ` ${unit}` : ""}`;
}

export function ChangesPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const subject = params.get("subject") || "";
  const requestedView = params.get("view");
  const view: EpisodeView = requestedView === "all" || requestedView === "reviewed" ? requestedView : "attention";
  const assessmentFilter = params.get("assessment") || "all";
  const selectedType = params.get("change_type") || "";
  const search = params.get("q") || "";
  const sort = params.get("sort") || "priority";
  const [page, setPage] = useState(0);
  const qs = queryString(filters, { limit: "500" });
  const query = useQuery({ queryKey: ["changes", qs], queryFn: () => api<EpisodeResponse>(`/api/v1/changes?${qs}`), refetchInterval: 60_000 });
  const items = query.data?.items || [];
  function update(key: string, value: string) {
    setPage(0);
    setParams((previous) => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next; }, { replace: true });
  }
  const typeOptions = useMemo(() => [...new Set((query.data?.items || []).flatMap(changeTypes))].sort(), [query.data?.items]);
  const filtered = useMemo(() => (query.data?.items || []).filter((episode) => {
    if (subject && episode.subject.type !== subject) return false;
    if (selectedType && !changeTypes(episode).includes(selectedType)) return false;
    if (search && !`${episodeSearchText(episode)} ${changeTypes(episode).join(" ")}`.toLowerCase().includes(search.toLowerCase())) return false;
    const assessment = episode.semantic_assessment;
    const status = assessment?.status || "not_evaluated";
    if (assessmentFilter === "high_confidence") return status === "succeeded" && (assessment?.abnormal_probability ?? 0) >= 0.8;
    if (assessmentFilter === "investigate") return status === "succeeded" && ["investigate", "urgent"].includes(assessment?.priority || "");
    if (assessmentFilter === "watch") return status === "succeeded" && assessment?.priority === "watch";
    if (assessmentFilter !== "all") return status === assessmentFilter;
    return true;
  }), [query.data?.items, subject, selectedType, search, assessmentFilter]);
  const rank: Record<Episode["state"], number> = { critical: 4, needs_attention: 3, watch: 2, changed: 1, expected: 0 };
  const episodes = filtered.filter((episode) => episodeMatchesView(episode, view)).sort((a, b) => (sort === "priority" ? rank[b.state] - rank[a.state] : 0) || b.last_seen_at - a.last_seen_at);
  const currentPage = Math.min(page, Math.max(0, Math.ceil(episodes.length / 25) - 1));
  const visible = episodes.slice(currentPage * 25, (currentPage + 1) * 25);
  const detailSearch = `?${queryString(filters, { view, subject, change_type: selectedType, assessment: assessmentFilter, q: search, sort })}`;
  function reset() {
    setPage(0);
    setParams((previous) => { const next = new URLSearchParams(previous); for (const key of ["subject", "change_type", "assessment", "q", "sort"]) next.delete(key); return next; }, { replace: true });
  }

  return <Page eyebrow={t("Changes")} title={t("Changes")} description={t("Triage changes, compare the evidence, and investigate.", "Phân loại thay đổi, đối chiếu bằng chứng và điều tra.")}>
    <section className="panel overflow-hidden" aria-label={t("Change episodes", "Các thay đổi")}>
      <div className="flex flex-wrap items-center gap-1 border-b border-[#2a2d30] px-3 py-2">
        {([["attention", t("Needs attention")], ["all", t("All", "Tất cả")], ["reviewed", t("Reviewed", "Đã xem xét")]] as const).map(([value, label]) => <button type="button" key={value} aria-pressed={view === value} onClick={() => update("view", value)} className={`flex items-center gap-2 rounded-sm px-3 py-1.5 text-xs ${view === value ? "bg-[#5794f2]/15 text-[#5794f2]" : "text-[#a7a9ab] hover:bg-[#181b1f]"}`}>{label}<span className="font-mono">{query.data ? filtered.filter((episode) => episodeMatchesView(episode, value)).length : "—"}</span></button>)}
        <span className="ml-auto text-[11px] text-[#a7a9ab]">{t("Critical")} <strong className="font-mono text-[#f2495c]">{query.data ? filtered.filter((episode) => episode.state === "critical" && episode.status !== "resolved").length : "—"}</strong></span>
      </div>
      <div className="flex flex-wrap gap-2 border-b border-[#2a2d30] p-3">
        <label className="relative min-w-0 flex-[1_1_220px]"><span className="sr-only">{t("Search changes", "Tìm thay đổi")}</span><Search size={13} className="absolute left-2 top-2 text-[#a7a9ab]" /><input value={search} onChange={(event) => update("q", event.target.value)} placeholder={t("Search changes...", "Tìm thay đổi...")} className="toolbar-control h-8 w-full pl-7 pr-2 text-xs" /></label>
        <select aria-label={t("Change type", "Loại thay đổi")} value={selectedType} onChange={(event) => update("change_type", event.target.value)} className="toolbar-control h-8 max-w-full px-2 text-xs">
          <option value="">{t("All change types", "Mọi loại thay đổi")}</option>
          {selectedType && !typeOptions.includes(selectedType) && <option value={selectedType}>{changeTypeLabel(selectedType, t)}</option>}
          {typeOptions.map((type) => <option key={type} value={type}>{changeTypeLabel(type, t)} ({items.filter((episode) => changeTypes(episode).includes(type)).length})</option>)}
        </select>
        <select aria-label={t("Subject", "Đối tượng")} value={subject} onChange={(event) => update("subject", event.target.value)} className="toolbar-control h-8 px-2 text-xs"><option value="">{t("All subjects", "Mọi đối tượng")}</option><option value="service">Service</option><option value="user">User</option></select>
        <select id="changes-semantic-filter" aria-label={t("AI assessment filter", "Lọc đánh giá AI")} value={assessmentFilter} onChange={(event) => update("assessment", event.target.value)} className="toolbar-control h-8 max-w-full px-2 text-xs">
          <option value="all">{t("AI assessment: All", "Đánh giá AI: Tất cả")}</option><option value="high_confidence">{t("High confidence", "Độ tin cậy cao")}</option><option value="investigate">{t("Investigate", "Điều tra")}</option><option value="watch">{t("Watch", "Theo dõi")}</option><option value="pending">{t("Pending", "Đang chờ")}</option><option value="not_evaluated">{t("Not evaluated", "Chưa đánh giá")}</option><option value="failed">{t("AI unavailable", "AI không khả dụng")}</option><option value="stale">{t("AI stale", "AI đã cũ")}</option>
        </select>
        <select aria-label={t("Sort", "Sắp xếp")} value={sort} onChange={(event) => update("sort", event.target.value)} className="toolbar-control h-8 px-2 text-xs"><option value="priority">{t("Priority first", "Ưu tiên mức độ")}</option><option value="recent">{t("Latest first", "Mới nhất trước")}</option></select>
        {(search || selectedType || subject || assessmentFilter !== "all" || sort !== "priority") && <button type="button" onClick={reset} className="px-2 text-xs text-[#5794f2] hover:underline">{t("Clear filters", "Xóa bộ lọc")}</button>}
      </div>
      <div className="hidden grid-cols-[135px_minmax(0,1fr)_190px_120px_145px] gap-3 border-b border-[#2a2d30] bg-[#181b1f] px-3 py-2 text-[10px] uppercase tracking-wide text-[#a7a9ab] xl:grid"><span>{t("State", "Trạng thái")}</span><span>{t("What changed", "Điều gì thay đổi")}</span><span>{t("Before → now", "Trước → hiện tại")}</span><span>{t("Last observed", "Quan sát gần nhất")}</span><span>{t("Actions", "Thao tác")}</span></div>
      {query.isLoading ? <Loading /> : query.error ? <ErrorState message={query.error.message} /> : visible.length ? <div className="divide-y divide-[#2a2d30]">{visible.map((episode) => {
        const highlight = episode.highlights.find((item) => item.before != null && item.after != null) || episode.highlights[0];
        const types = changeTypes(episode);
        return <article key={episode.id} data-change-types={types.join(",")} className="grid gap-3 px-3 py-3 hover:bg-[#181b1f]/60 xl:grid-cols-[135px_minmax(0,1fr)_190px_120px_145px]">
          <div className="flex flex-wrap items-start gap-1.5 xl:flex-col"><EpisodeStatusBadge episode={episode} /><EpisodeWorkflowBadge episode={episode} /></div>
          <div className="min-w-0">
            <EntityLink entity={{ kind: "change", id: episode.id }} search={detailSearch} className="line-clamp-2 text-xs font-semibold leading-5 text-[#d8d9da] hover:text-[#5794f2]">{episodeTitle(episode, t)}</EntityLink>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[#a7a9ab]"><span>{episode.subject.type === "user" ? "User" : "Service"}:</span><EntityLink entity={episode.subject.type === "user" ? { kind: "user", principal: episode.subject.name } : { kind: "service", name: episode.subject.name }} className="max-w-full truncate text-[#5794f2]">{episode.subject.name}</EntityLink><span>· {episode.signal_count} {t("signals", "tín hiệu")}</span>{episode.semantic_assessment && episode.semantic_assessment.status !== "not_evaluated" && <SemanticAssessmentBadge assessment={episode.semantic_assessment} />}</div>
            <div className="mt-1 flex flex-wrap gap-1">{types.map((type) => <button key={type} type="button" title={type} onClick={() => update("change_type", type)} className="rounded-sm border border-[#34373b] px-1.5 py-0.5 text-[10px] text-[#a7a9ab] hover:border-[#5794f2] hover:text-[#5794f2]">{changeTypeLabel(type, t)}</button>)}</div>
          </div>
          <div className="min-w-0 text-[11px]">{highlight ? <><div className="truncate text-[#a7a9ab]">{t(highlight.label, highlight.label)}</div><div className="mt-1 line-clamp-2 break-words font-mono text-[#d8d9da]">{compactValue(highlight.before, highlight.unit)} <span className="text-[#a7a9ab]">→</span> {compactValue(highlight.after, highlight.unit)}</div></> : <span className="text-[#a7a9ab]">{t("See evidence", "Xem bằng chứng")}</span>}</div>
          <div className="text-[11px] text-[#a7a9ab]">{formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</div>
          <div className="flex flex-wrap items-start gap-2 xl:flex-col"><EntityLink entity={{ kind: "change", id: episode.id }} search={detailSearch} className="text-[11px] text-[#5794f2] hover:underline">{t("View details", "Xem chi tiết")} <ArrowRight size={11} className="inline" /></EntityLink><button type="button" onClick={() => nav(`${entityPath({ kind: "change", id: episode.id })}${detailSearch}#ai-investigation`)} className="text-[11px] text-[#b877d9] hover:underline">{t("Investigate", "Điều tra")}</button></div>
        </article>;
      })}</div> : <div className="p-8 text-center text-xs text-[#a7a9ab]">{t("No changes match the selected view.", "Không có thay đổi phù hợp với bộ lọc.")}</div>}
      {query.data && <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#2a2d30] px-3 py-2 text-[11px] text-[#a7a9ab]"><span>{episodes.length ? currentPage * 25 + 1 : 0}–{Math.min((currentPage + 1) * 25, episodes.length)} / {episodes.length} {t("matching", "phù hợp")} · {items.length}/{query.data.total} {t("episodes loaded", "thay đổi đã tải")}</span><div className="flex items-center gap-3"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} className="disabled:opacity-40">{t("Previous", "Trước")}</button><span>{currentPage + 1} / {Math.max(1, Math.ceil(episodes.length / 25))}</span><button type="button" disabled={(currentPage + 1) * 25 >= episodes.length} onClick={() => setPage(currentPage + 1)} className="disabled:opacity-40">{t("Next", "Sau")}</button></div></div>}
    </section>
  </Page>;
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
    <Page eyebrow={t("Change detail", "Chi tiết thay đổi")} title={episodeTitle(episode, t)} description={episode.summary} actions={<div className="flex flex-wrap gap-2"><button type="button" onClick={() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="btn border-[#b877d9]/50 text-[#b877d9]"><BrainCircuit size={13} />{t("Investigate", "Điều tra")}</button><button type="button" onClick={() => nav(`/changes?${queryString(filters, { view: searchParams.get("view") || "attention" })}`)} className="btn"><ArrowLeft size={13} />{t("All changes", "Tất cả thay đổi")}</button></div>}>
      <section className={`border-l-4 ${episode.state === "critical" ? "border-[#f2495c]" : episode.state === "needs_attention" ? "border-[#ff9830]" : "border-[#5794f2]"} panel p-4 md:p-5`} aria-label={t("Change summary", "Tóm tắt thay đổi")}>
        <div className="flex flex-wrap items-center gap-2"><EpisodeStatusBadge episode={episode} /><EpisodeWorkflowBadge episode={episode} /><span className="text-[11px] text-[#a7a9ab]">{formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</span></div>
        <h2 className="mt-4 max-w-4xl text-xl font-semibold leading-7 text-[#f1f3f5]">{episode.summary || episodeTitle(episode, t)}</h2>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-[#c2c6cc]">{episode.explanation}</p>
        <div className="mt-4"><EpisodePath episode={episode} compact /></div>
        <div className="mt-5 grid gap-px overflow-hidden border border-[#2a2d30] bg-[#2a2d30] sm:grid-cols-3">{contextItems.map(([label, value]) => <div key={label} className="bg-[#111217] px-3 py-2.5"><div className="text-[10px] font-semibold uppercase tracking-wide text-[#7b7d80]">{label}</div><div className="mt-1 truncate font-mono text-xs text-[#d8d9da]">{value}</div></div>)}</div>
      </section>

      <ChangeVisualEvidence episode={episode} filters={filters} />

      <section className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(280px,.6fr)]">
        <Panel title={t("The changed pattern", "Mẫu đã thay đổi")} subtitle={t("Normal behavior compared with the observed window.", "Hành vi bình thường so với khoảng thời gian quan sát.")}>
          {primaryHighlight ? <div className="grid gap-4 p-4 sm:grid-cols-[1fr_auto_1fr] sm:items-center"><div><div className="text-[10px] font-semibold uppercase tracking-wide text-[#7b7d80]">{t("Before", "Trước")}</div><div className="mt-2 font-mono text-2xl text-[#a7a9ab]">{compactValue(primaryHighlight.before, primaryHighlight.unit)}</div></div><div className="text-center text-2xl text-[#ff9830]">→</div><div><div className="text-[10px] font-semibold uppercase tracking-wide text-[#ff9830]">{t("Now", "Hiện tại")}</div><div className="mt-2 font-mono text-2xl font-semibold text-[#f1f3f5]">{compactValue(primaryHighlight.after, primaryHighlight.unit)}</div>{primaryHighlight.delta != null && <div className="mt-1 font-mono text-xs text-[#ff9830]">{formatHighlightDelta(primaryHighlight, t)}</div>}</div></div> : <div className="p-4 text-sm text-[#a7a9ab]">{t("No primary metric is available. Use the evidence below.", "Chưa có chỉ số chính. Xem bằng chứng bên dưới.")}</div>}
          <EpisodeMetricTable episode={episode} />
        </Panel>
        <Panel title={t("When it happened", "Thời điểm xảy ra")}><div className="space-y-3 p-4 text-xs"><div><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t("Started", "Bắt đầu")}</div><div className="mt-1 font-mono text-[#d8d9da]">{formatEpisodeTime(episode.started_at, true, filters.timezone)}</div></div><div><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t("Last observed", "Quan sát gần nhất")}</div><div className="mt-1 font-mono text-[#d8d9da]">{formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</div></div><div><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t("Signals grouped", "Tín hiệu đã nhóm")}</div><div className="mt-1 font-mono text-xl text-[#5794f2]">{episode.signal_count}</div></div></div></Panel>
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,.7fr)]">
        <div className="space-y-4"><Panel title={t("Signal timeline", "Dòng thời gian tín hiệu")} subtitle={t("What was observed, in order.", "Những gì được quan sát theo thứ tự.")}><EpisodeTimeline episode={episode} timezone={filters.timezone} /></Panel><Panel title={t("Relationship path", "Đường quan hệ")}><div className="p-4"><EpisodePath episode={episode} /></div></Panel></div>
        <div className="space-y-4"><Panel title={t("Why this is a change", "Vì sao đây là thay đổi")}><div className="space-y-3 p-4">{(episode.abnormality?.reasons || [episode.explanation]).map((reason) => <div key={reason} className="border-l-2 border-[#5794f2] pl-3 text-xs leading-5 text-[#d8d9da]">{reason}</div>)}</div></Panel><Panel title={t("Supporting evidence", "Bằng chứng hỗ trợ")}><EpisodeEvidence episode={episode} /></Panel><EpisodeBaselineNote episode={episode} /></div>
      </div>

      <Panel title={t("Next action", "Thao tác tiếp theo")} subtitle={t("Choose the operator outcome for this change.", "Chọn cách xử lý cho thay đổi này.")} className="mt-4"><div className="flex flex-wrap gap-2 p-3"><button type="button" onClick={() => nav(`/traces?${queryString(filters, { principal: episode.subject.type === "user" ? episode.subject.name : undefined, service: episode.context.target || undefined })}`)} className="btn"><Activity size={13} />{t("View related traces", "Xem Trace liên quan")}</button><EntityLink entity={episode.subject.type === "user" ? { kind: "user", principal: episode.subject.name } : { kind: "service", name: episode.subject.name }} className="btn"><ArrowRight size={13} />{t(`Open ${episode.subject.type}`, `Mở ${episode.subject.type}`)}</EntityLink><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("expected")} className="btn text-[#73bf69]">{canMarkEpisodeExpected(episode) ? t("Mark expected", "Đánh dấu dự kiến") : t("Suppress", "Ẩn finding")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("investigate")} className="btn text-[#ff9830]">{t("Keep monitoring", "Tiếp tục theo dõi")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("resolve")} className="btn">{t("Resolve", "Đã xử lý")}</button></div>{decision.isError && <div className="border-t border-[#2a2d30] p-3 text-xs text-[#f2495c]">{decision.error instanceof Error ? decision.error.message : t("Decision could not be saved", "Không thể lưu quyết định")}</div>}{decision.isSuccess && <div className="border-t border-[#2a2d30] p-3 text-xs text-[#73bf69]">{t("Decision saved", "Đã lưu quyết định")}</div>}</Panel>

      <div id="ai-investigation" ref={aiSectionRef} className="scroll-mt-20 mt-4"><details className="panel"><summary className="flex cursor-pointer list-none items-center justify-between p-4 text-sm font-semibold text-[#d8d9da]"><span className="flex items-center gap-2"><BrainCircuit size={15} className="text-[#b877d9]" />{t("Technical AI investigation", "Điều tra AI kỹ thuật")}</span><span className="text-[11px] font-normal text-[#7b7d80]">{t("Optional", "Tùy chọn")}</span></summary><div className="border-t border-[#2a2d30]">{findingRef ? <InvestigationPanel findingRef={findingRef} initialScore={episode.score} initialSeverity={episode.severity} initialExplanation={episode.explanation} initialEntityId={episode.context.target || episode.subject.name} /> : <div className="p-4 text-xs text-[#7b7d80]">{t("AI analysis is unavailable because this episode has no source finding.", "Không thể phân tích AI vì episode chưa có finding nguồn.")}</div>}</div></details></div>
    </Page>
  );
}

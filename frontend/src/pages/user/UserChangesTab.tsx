import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, BrainCircuit, Search } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, useLocation, useNavigate, useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { api, queryString } from "../../api";
import { canMarkEpisodeExpected, decideEpisode } from "../../episodeActions";
import { useFilters } from "../../App";
import { ErrorState, Loading, MetricCard, Panel } from "../../components";
import { InvestigationPanel } from "../../components/InvestigationPanel";
import { useI18n } from "../../i18n";
import { entityPath } from "../../entityRoutes";
import { EntityLink } from "../../components/EntityLink";
import {
  EpisodeBaselineNote,
  EpisodeCard,
  EpisodeEvidence,
  EpisodeMetricTable,
  EpisodePath,
  EpisodeStatusBadge,
  EpisodeWorkflowBadge,
  EpisodeTimeline,
  SemanticAssessmentSummary,
  type Episode,
  type EpisodeResponse,
  episodeCategory,
  episodeFindingRef,
  episodeMatchesView,
  episodeSearchText,
  episodeTitle,
  formatEpisodeTime,
  isEpisodeAttention,
  isEpisodeReviewed,
  type EpisodeView,
} from "../../components/EpisodePrimitives";

type UserContext = { principal: string; profile: any };

function episodeQuery(principal: string, filters: any) {
  return `/api/v1/changes?${queryString(filters, { principal, limit: "100" })}`;
}

function useEpisodeDecision(episode: Episode | null, principal: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (action: "expected" | "investigate" | "resolve") => {
      if (!episode) throw new Error("No change episode selected");
      return decideEpisode(episode, action);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-episodes", principal] });
      queryClient.invalidateQueries({ queryKey: ["change-episode"] });
      queryClient.invalidateQueries({ queryKey: ["user-detail", principal] });
    },
  });
}

export function UserChangesTab() {
  const { principal } = useOutletContext<UserContext>();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [stateFilter, setStateFilter] = useState<EpisodeView>("attention");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [search, setSearch] = useState("");
  const query = useQuery({
    queryKey: ["user-episodes", principal, filters],
    queryFn: () => api<EpisodeResponse>(episodeQuery(principal, filters)),
    enabled: Boolean(principal),
    refetchInterval: 60_000,
  });
  const episodes = query.data?.items || [];
  const visible = useMemo(() => episodes.filter((episode) => {
    if (!episodeMatchesView(episode, stateFilter)) return false;
    if (categoryFilter !== "all" && episodeCategory(episode) !== categoryFilter) return false;
    if (search && !episodeSearchText(episode).includes(search.toLowerCase())) return false;
    return true;
  }), [episodes, stateFilter, categoryFilter, search]);
  const attention = episodes.filter(isEpisodeAttention).length;
  const reviewed = episodes.filter(isEpisodeReviewed).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">{t("Changes", "Thay đổi")}</h2>
          <p className="mt-1 text-xs text-muted">{t("Changes in this user compared with established behavior.", "Các thay đổi của User so với hành vi đã thiết lập.")}</p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <MetricCard label={t("Needs attention", "Cần chú ý")} value={String(attention)} detail={t("Unresolved abnormal episodes", "Episode bất thường chưa xử lý")} tone={attention ? "bad" : "good"} accent="amber" />
        <MetricCard label={t("All changes", "Tất cả thay đổi")} value={String(episodes.length)} detail={t("Episodes in selected window", "Episode trong khoảng thời gian đã chọn")} accent="sky" />
        <MetricCard label={t("Reviewed", "Đã xem xét")} value={String(reviewed)} detail={t("Expected or resolved episodes", "Episode dự kiến hoặc đã xử lý")} accent="emerald" />
      </div>

      <Panel title={t("Changes", "Thay đổi")} subtitle={t("Episodes simplify detector signals into an operator-readable event.", "Các episode chuyển tín hiệu detector thành sự kiện dễ xử lý.")} action={<span className="font-mono text-[10px] text-muted">{visible.length} / {episodes.length}</span>}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface p-3">
          {[ ["attention", t("Needs attention", "Cần chú ý")], ["all", t("All", "Tất cả")], ["reviewed", t("Reviewed", "Đã xem xét")] ].map(([value, label]) => <button key={value} type="button" onClick={() => setStateFilter(value as EpisodeView)} className={`border px-3 py-1.5 text-[11px] ${stateFilter === value ? "border-accent bg-accent-soft text-ink" : "border-line-strong text-muted hover:text-ink"}`}>{label}</button>)}
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} className="toolbar-control h-7 px-2 text-[11px] text-muted"><option value="all">{t("All types", "Tất cả loại")}</option><option value="access">{t("Access", "Truy cập")}</option><option value="traffic">{t("Traffic", "Lưu lượng")}</option><option value="performance">{t("Performance", "Hiệu năng")}</option><option value="errors">{t("Errors", "Lỗi")}</option><option value="authentication">{t("Authentication", "Xác thực")}</option><option value="network">{t("Network", "Mạng")}</option></select>
          <label className="relative ml-auto"><Search size={13} className="absolute left-2 top-1.5 text-muted" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search changes...", "Tìm thay đổi...")} className="toolbar-control h-7 w-52 pl-7 pr-2 text-[11px] placeholder:text-muted" /></label>
        </div>
        {query.isLoading ? <Loading /> : query.error ? <ErrorState message={query.error.message} /> : visible.length ? <div>{visible.map((episode) => {
          const detailSearch = `?${queryString(filters, { principal })}`;
          const detailUrl = `${entityPath({ kind: "change", id: episode.id })}${detailSearch}`;
          return <EpisodeCard key={episode.id} episode={episode} timezone={filters.timezone} detailSearch={detailSearch} onInvestigate={() => nav(`${detailUrl}#ai-investigation`)} />;
        })}</div> : <div className="p-10 text-center text-xs text-muted">{t("No changes match these filters.", "Không có thay đổi phù hợp với bộ lọc.")}</div>}
      </Panel>
    </div>
  );
}

export function LegacyUserInvestigationRedirect() {
  const { principal = "" } = useParams();
  const [searchParams] = useSearchParams();
  const episodeId = searchParams.get("episode_id");
  const nextParams = new URLSearchParams(searchParams);
  nextParams.delete("episode_id");
  nextParams.delete("tab");
  const query = nextParams.toString();
  const base = `/users/${encodeURIComponent(principal)}/changes${episodeId ? `/${encodeURIComponent(episodeId)}` : ""}`;
  return <Navigate to={`${base}${query ? `?${query}` : ""}${episodeId ? "#ai-investigation" : ""}`} replace />;
}

export function UserChangeDetailPage() {
  const { principal = "", episodeId = "" } = useParams();
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const location = useLocation();
  const aiSectionRef = useRef<HTMLDivElement>(null);
  const query = useQuery({ queryKey: ["change-episode", episodeId, filters], queryFn: () => api<Episode>(`/api/v1/changes/${encodeURIComponent(episodeId)}?${queryString(filters)}`), enabled: Boolean(episodeId) });
  const decision = useEpisodeDecision(query.data || null, principal);
  useEffect(() => {
    if (query.data && location.hash === "#ai-investigation") {
      requestAnimationFrame(() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  }, [location.hash, query.data]);
  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState message={query.error?.message || t("Change episode not found", "Episode thay đổi không tồn tại")} />;
  const episode = query.data;
  const findingRef = episodeFindingRef(episode);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
        <div><button type="button" onClick={() => nav(`/users/${encodeURIComponent(principal)}/changes?${queryString(filters)}`)} className="mb-2 inline-flex items-center gap-1 text-[11px] text-ink font-semibold hover:underline"><ArrowLeft size={12} />{t("Back to Changes", "Quay lại Changes")}</button><div className="flex flex-wrap items-center gap-2"><EpisodeStatusBadge episode={episode} /><EpisodeWorkflowBadge episode={episode} /><EntityLink entity={{ kind: "user", principal }} className="font-mono text-[11px] text-entity-user hover:underline">{principal}</EntityLink></div><h2 className="mt-2 text-lg font-semibold text-ink">{episodeTitle(episode, t)}</h2><p className="mt-1 text-xs text-muted">{t("Started", "Bắt đầu")} {formatEpisodeTime(episode.started_at, true, filters.timezone)} · {t("Last observed", "Quan sát gần nhất")} {formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</p><div className="mt-2"><EpisodePath episode={episode} /></div></div>
        <div className="flex flex-wrap gap-2"><button type="button" onClick={() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="btn border-entity-user/50 text-entity-user"><BrainCircuit size={13} />{t("Deep investigate", "Điều tra chuyên sâu")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("expected")} className="btn text-good">{canMarkEpisodeExpected(episode) ? t("Expected behavior", "Hành vi dự kiến") : t("Suppress finding", "Ẩn finding")}</button></div>
      </div>
      <Panel title={t("What changed", "Điều gì đã thay đổi")} subtitle={t("A deterministic summary before any AI interpretation.", "Tóm tắt xác định trước mọi diễn giải của AI.")}><div className="space-y-3 p-4"><p className="max-w-4xl text-sm leading-6 text-ink">{episodeTitle(episode, t)}</p><p className="max-w-4xl text-xs leading-5 text-muted">{episode.explanation}</p><EpisodeBaselineNote episode={episode} /></div></Panel>
      <SemanticAssessmentSummary episode={episode} full timezone={filters.timezone} />
      <Panel title={t("Priority rationale", "Cơ sở xác định ưu tiên")} subtitle={t("Deterministic evidence used to evaluate the change.", "Bằng chứng xác định dùng để đánh giá thay đổi.")}><div className="space-y-3 p-4">{(episode.abnormality?.reasons || []).map((reason) => <div key={reason} className="border-l-2 border-line-strong pl-2 text-[11px] text-ink">{reason}</div>)}</div></Panel>
      <Panel title={t("Observed changes", "Thay đổi quan sát được")}><EpisodeMetricTable episode={episode} /></Panel>
      <div className="grid gap-4 lg:grid-cols-2"><Panel title={t("Timeline", "Dòng thời gian")} subtitle={t("Observed signals in chronological order.", "Tín hiệu quan sát theo thứ tự thời gian.")}><EpisodeTimeline episode={episode} timezone={filters.timezone} /></Panel><Panel title={t("Detected signals", "Tín hiệu đã phát hiện")} subtitle={t("Technical detector facts remain secondary evidence.", "Sự kiện detector kỹ thuật là bằng chứng bổ trợ.")}><EpisodeEvidence episode={episode} /></Panel></div>
      <Panel title={t("Related traces", "Trace liên quan")} subtitle={t("Open Trace Explorer with this User and Service context.", "Mở Trace Explorer theo ngữ cảnh User và Service này.")}><div className="p-3"><button type="button" onClick={() => nav(`/traces?${queryString(filters, { principal, service: episode.context.target || undefined })}`)} className="btn"><Activity size={13} />{t("View related traces", "Xem Trace liên quan")}</button></div></Panel>
      <div id="ai-investigation" ref={aiSectionRef} className="scroll-mt-20">
        <Panel title={t("Deep AI Investigation", "Điều tra AI chuyên sâu")} subtitle={t("On-demand diagnostic analysis using supporting telemetry. It does not modify L3 detection or the L4 semantic assessment.", "Phân tích chẩn đoán theo yêu cầu dựa trên telemetry hỗ trợ. Phân tích này không thay đổi phát hiện L3 hoặc đánh giá ngữ nghĩa L4.")} action={<BrainCircuit size={15} className="text-entity-user" />}>
          {findingRef ? <InvestigationPanel findingRef={findingRef} initialScore={episode.score} initialSeverity={episode.severity} initialExplanation={episode.explanation} initialEntityId={episode.context.target || principal} /> : <div className="p-4 text-xs text-muted">{t("AI analysis is unavailable because this episode has no source finding.", "Không thể phân tích AI vì episode chưa có finding nguồn.")}</div>}
        </Panel>
      </div>
      <Panel title={t("Operator decision", "Quyết định của operator")} subtitle={t("Actions currently apply to the source finding represented by this episode.", "Thao tác hiện áp dụng cho finding nguồn đại diện cho episode này.")}><div className="flex flex-wrap items-center justify-between gap-3 p-3"><span className="text-xs text-muted">{t("Choose how this change should be handled.", "Chọn cách xử lý thay đổi này.")}</span><div className="flex flex-wrap gap-2"><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("investigate")} className="btn border-warn/50 text-warn">{t("Keep monitoring", "Tiếp tục theo dõi")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("resolve")} className="btn text-good">{t("Resolve", "Đã xử lý")}</button></div></div>{decision.isError && <div className="border-t border-line p-3 text-xs text-bad">{decision.error instanceof Error ? decision.error.message : t("Decision could not be saved", "Không thể lưu quyết định")}</div>}{decision.isSuccess && <div className="border-t border-line p-3 text-xs text-good">{t("Decision saved", "Đã lưu quyết định")}</div>}</Panel>
    </div>
  );
}

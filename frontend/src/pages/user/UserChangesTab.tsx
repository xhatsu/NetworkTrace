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
import {
  EpisodeBaselineNote,
  EpisodeCard,
  EpisodeEvidence,
  EpisodeMetricTable,
  EpisodePath,
  EpisodeStatusBadge,
  EpisodeWorkflowBadge,
  EpisodeTimeline,
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
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#2a2d30] pb-3">
        <div>
          <h2 className="text-lg font-semibold text-[#d8d9da]">{t("Changes", "Thay đổi")}</h2>
          <p className="mt-1 text-xs text-[#a7a9ab]">{t("Changes in this user compared with established behavior.", "Các thay đổi của User so với hành vi đã thiết lập.")}</p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <MetricCard label={t("Needs attention", "Cần chú ý")} value={String(attention)} detail={t("Unresolved abnormal episodes", "Episode bất thường chưa xử lý")} tone={attention ? "bad" : "good"} accent="amber" />
        <MetricCard label={t("All changes", "Tất cả thay đổi")} value={String(episodes.length)} detail={t("Episodes in selected window", "Episode trong khoảng thời gian đã chọn")} accent="sky" />
        <MetricCard label={t("Reviewed", "Đã xem xét")} value={String(reviewed)} detail={t("Expected or resolved episodes", "Episode dự kiến hoặc đã xử lý")} accent="emerald" />
      </div>

      <Panel title={t("Changes", "Thay đổi")} subtitle={t("Episodes simplify detector signals into an operator-readable event.", "Các episode chuyển tín hiệu detector thành sự kiện dễ xử lý.")} action={<span className="font-mono text-[10px] text-[#7b7d80]">{visible.length} / {episodes.length}</span>}>
        <div className="flex flex-wrap items-center gap-2 border-b border-[#2a2d30] bg-[#111217] p-3">
          {[ ["attention", t("Needs attention", "Cần chú ý")], ["all", t("All", "Tất cả")], ["reviewed", t("Reviewed", "Đã xem xét")] ].map(([value, label]) => <button key={value} type="button" onClick={() => setStateFilter(value as EpisodeView)} className={`border px-3 py-1.5 text-[11px] ${stateFilter === value ? "border-[#5794f2] bg-[#5794f2]/10 text-[#d8d9da]" : "border-[#34373b] text-[#a7a9ab] hover:text-white"}`}>{label}</button>)}
          <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)} className="toolbar-control h-7 px-2 text-[11px] text-[#a7a9ab]"><option value="all">{t("All types", "Tất cả loại")}</option><option value="access">{t("Access", "Truy cập")}</option><option value="traffic">{t("Traffic", "Lưu lượng")}</option><option value="performance">{t("Performance", "Hiệu năng")}</option><option value="errors">{t("Errors", "Lỗi")}</option><option value="authentication">{t("Authentication", "Xác thực")}</option><option value="network">{t("Network", "Mạng")}</option></select>
          <label className="relative ml-auto"><Search size={13} className="absolute left-2 top-1.5 text-[#7b7d80]" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search changes...", "Tìm thay đổi...")} className="toolbar-control h-7 w-52 pl-7 pr-2 text-[11px] placeholder:text-[#7b7d80]" /></label>
        </div>
        {query.isLoading ? <Loading /> : query.error ? <ErrorState message={query.error.message} /> : visible.length ? <div>{visible.map((episode) => {
          const detailUrl = `/users/${encodeURIComponent(principal)}/changes/${encodeURIComponent(episode.id)}?${queryString(filters)}`;
          return <EpisodeCard key={episode.id} episode={episode} timezone={filters.timezone} onOpen={() => nav(detailUrl)} onInvestigate={() => nav(`${detailUrl}#ai-investigation`)} />;
        })}</div> : <div className="p-10 text-center text-xs text-[#7b7d80]">{t("No changes match these filters.", "Không có thay đổi phù hợp với bộ lọc.")}</div>}
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
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#2a2d30] pb-3">
        <div><button type="button" onClick={() => nav(`/users/${encodeURIComponent(principal)}/changes?${queryString(filters)}`)} className="mb-2 inline-flex items-center gap-1 text-[11px] text-[#5794f2] hover:text-[#d8d9da]"><ArrowLeft size={12} />{t("Back to Changes", "Quay lại Changes")}</button><div className="flex flex-wrap items-center gap-2"><EpisodeStatusBadge episode={episode} /><EpisodeWorkflowBadge episode={episode} /><span className="font-mono text-[11px] text-[#7b7d80]">{principal}</span></div><h2 className="mt-2 text-lg font-semibold text-[#d8d9da]">{episodeTitle(episode, t)}</h2><p className="mt-1 text-xs text-[#a7a9ab]">{t("Started", "Bắt đầu")} {formatEpisodeTime(episode.started_at, true, filters.timezone)} · {t("Last observed", "Quan sát gần nhất")} {formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</p><div className="mt-2"><EpisodePath episode={episode} /></div></div>
        <div className="flex flex-wrap gap-2"><button type="button" onClick={() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="btn border-[#b877d9]/50 text-[#b877d9]"><BrainCircuit size={13} />{t("Investigate with AI", "Điều tra bằng AI")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("expected")} className="btn text-[#73bf69]">{canMarkEpisodeExpected(episode) ? t("Expected behavior", "Hành vi dự kiến") : t("Suppress finding", "Ẩn finding")}</button></div>
      </div>
      <Panel title={t("What changed", "Điều gì đã thay đổi")} subtitle={t("A deterministic summary before any AI interpretation.", "Tóm tắt xác định trước mọi diễn giải của AI.")}><div className="space-y-3 p-4"><p className="max-w-4xl text-sm leading-6 text-[#d8d9da]">{episode.summary}</p><p className="max-w-4xl text-xs leading-5 text-[#a7a9ab]">{episode.explanation}</p><EpisodeBaselineNote episode={episode} /></div></Panel>
      <Panel title={t("Why this state", "Vì sao có trạng thái này")} subtitle={t("Evidence used to evaluate the change.", "Bằng chứng dùng để đánh giá thay đổi.")}><div className="space-y-3 p-4">{(episode.abnormality?.reasons || []).map((reason) => <div key={reason} className="border-l-2 border-[#5794f2] pl-2 text-[11px] text-[#d8d9da]">{reason}</div>)}</div></Panel>
      <Panel title={t("Before vs now", "Trước và hiện tại")}><EpisodeMetricTable episode={episode} /></Panel>
      <div className="grid gap-4 lg:grid-cols-2"><Panel title={t("Timeline", "Dòng thời gian")} subtitle={t("Observed signals in chronological order.", "Tín hiệu quan sát theo thứ tự thời gian.")}><EpisodeTimeline episode={episode} timezone={filters.timezone} /></Panel><Panel title={t("Evidence", "Bằng chứng")} subtitle={t("Technical detector facts remain secondary evidence.", "Sự kiện detector kỹ thuật là bằng chứng bổ trợ.")}><EpisodeEvidence episode={episode} /></Panel></div>
      <Panel title={t("Related traces", "Trace liên quan")} subtitle={t("Open Trace Explorer with this User and Service context.", "Mở Trace Explorer theo ngữ cảnh User và Service này.")}><div className="p-3"><button type="button" onClick={() => nav(`/traces?${queryString(filters, { principal, service: episode.context.target || undefined })}`)} className="btn"><Activity size={13} />{t("View related traces", "Xem Trace liên quan")}</button></div></Panel>
      <div id="ai-investigation" ref={aiSectionRef} className="scroll-mt-20">
        <Panel title={t("AI investigation", "Điều tra AI")} subtitle={t("LLM analysis supports the evidence and does not replace detector facts.", "Phân tích LLM hỗ trợ bằng chứng và không thay thế dữ kiện detector.")} action={<BrainCircuit size={15} className="text-[#b877d9]" />}>
          {findingRef ? <InvestigationPanel findingRef={findingRef} initialScore={episode.score} initialSeverity={episode.severity} initialExplanation={episode.explanation} initialEntityId={episode.context.target || principal} /> : <div className="p-4 text-xs text-[#7b7d80]">{t("AI analysis is unavailable because this episode has no source finding.", "Không thể phân tích AI vì episode chưa có finding nguồn.")}</div>}
        </Panel>
      </div>
      <Panel title={t("Operator decision", "Quyết định của operator")} subtitle={t("Actions currently apply to the source finding represented by this episode.", "Thao tác hiện áp dụng cho finding nguồn đại diện cho episode này.")}><div className="flex flex-wrap items-center justify-between gap-3 p-3"><span className="text-xs text-[#a7a9ab]">{t("Choose how this change should be handled.", "Chọn cách xử lý thay đổi này.")}</span><div className="flex flex-wrap gap-2"><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("investigate")} className="btn border-[#ff9830]/50 text-[#ff9830]">{t("Keep monitoring", "Tiếp tục theo dõi")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("resolve")} className="btn text-[#73bf69]">{t("Resolve", "Đã xử lý")}</button></div></div>{decision.isError && <div className="border-t border-[#2a2d30] p-3 text-xs text-[#f2495c]">{decision.error instanceof Error ? decision.error.message : t("Decision could not be saved", "Không thể lưu quyết định")}</div>}{decision.isSuccess && <div className="border-t border-[#2a2d30] p-3 text-xs text-[#73bf69]">{t("Decision saved", "Đã lưu quyết định")}</div>}</Panel>
    </div>
  );
}

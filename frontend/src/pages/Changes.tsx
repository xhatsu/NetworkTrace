import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowLeft, ArrowRight, BrainCircuit, Search } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, queryString } from "../api";
import { useFilters } from "../App";
import { canMarkEpisodeExpected, decideEpisode } from "../episodeActions";
import { ErrorState, Loading, MetricCard, Page, Panel, n } from "../components";
import {
  EpisodeBaselineNote,
  EpisodeCard,
  EpisodeEvidence,
  EpisodeMetricTable,
  EpisodePath,
  EpisodeStatusBadge,
  EpisodeWorkflowBadge,
  EpisodeTimeline,
  episodeFindingRef,
  formatEpisodeTime,
  episodeMatchesView,
  type EpisodeView,
  type Episode,
  type EpisodeResponse,
} from "../components/EpisodePrimitives";
import { InvestigationPanel } from "../components/InvestigationPanel";
import { useI18n } from "../i18n";

export function ChangesPage() {
  const { filters } = useFilters();
  const { t } = useI18n();
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const [subject, setSubject] = useState("");
  const [view, setView] = useState<EpisodeView>(() => {
    const requested = searchParams.get("view");
    return requested === "all" || requested === "reviewed" ? requested : "attention";
  });
  const [search, setSearch] = useState("");
  const qs = queryString(filters, { subject, q: search, limit: "300" });
  const query = useQuery({ queryKey: ["changes", qs], queryFn: () => api<EpisodeResponse>(`/api/v1/changes?${qs}`), refetchInterval: 60_000 });
  const episodes = useMemo(() => (query.data?.items || []).filter((episode) => episodeMatchesView(episode, view)), [query.data?.items, view]);
  const summary = query.data?.summary;

  return (
    <Page
      eyebrow={t("Changes", "Thay đổi")}
      title={t("Changes", "Thay đổi")}
      description={t("Operational changes across Services and Users, prioritized by evidence and impact.", "Thay đổi vận hành trên Service và User, được ưu tiên theo bằng chứng và tác động.")}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard label={t("Needs attention", "Cần chú ý")} value={n(summary?.needs_attention)} detail={t("Abnormal open episodes", "Episode bất thường đang mở")} tone={summary?.needs_attention ? "bad" : "normal"} accent="rose" />
        <MetricCard label={t("Changed", "Đã thay đổi")} value={n(summary?.changed)} detail={t("Different, not yet abnormal", "Khác biệt nhưng chưa bất thường")} accent="sky" />
        <MetricCard label={t("Reviewed", "Đã xem xét")} value={n(summary?.reviewed ?? summary?.expected)} detail={t("Expected or resolved episodes", "Episode dự kiến hoặc đã xử lý")} accent="emerald" />
      </div>

      <Panel title={t("Change episodes", "Episode thay đổi")} subtitle={t("Service and User signals are correlated once, then evaluated for abnormality.", "Tín hiệu Service và User được tương quan một lần, sau đó đánh giá mức bất thường.")} className="mt-4" action={<span className="text-[10px] text-[#7b7d80]">{query.data?.total ?? 0} {t("episodes", "episode")}</span>}>
        <div className="flex flex-wrap items-center gap-2 border-b border-[#2a2d30] bg-[#111217] p-3">
          {([ ["attention", t("Needs attention", "Cần chú ý")], ["all", t("All", "Tất cả")], ["reviewed", t("Reviewed", "Đã review")] ] as const).map(([value, label]) => (
            <button key={value} type="button" onClick={() => setView(value)} className={`border px-3 py-1.5 text-[11px] ${view === value ? "border-[#5794f2] bg-[#5794f2]/10 text-[#d8d9da]" : "border-[#34373b] text-[#a7a9ab] hover:text-white"}`}>{label}</button>
          ))}
          <select value={subject} onChange={(event) => setSubject(event.target.value)} className="toolbar-control h-7 px-2 text-[11px] text-[#a7a9ab]">
            <option value="">{t("All subjects", "Mọi đối tượng")}</option>
            <option value="user">{t("Users", "User")}</option>
            <option value="service">{t("Services", "Service")}</option>
          </select>
          <label className="relative ml-auto"><Search size={13} className="absolute left-2 top-1.5 text-[#7b7d80]" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search changes...", "Tìm thay đổi...")} className="toolbar-control h-7 w-56 pl-7 pr-2 text-[11px] placeholder:text-[#7b7d80]" /></label>
        </div>
        {query.isLoading ? <Loading /> : query.error ? <ErrorState message={query.error.message} /> : episodes.length ? (
          <div>{episodes.map((episode) => {
            const detailUrl = `/changes/${encodeURIComponent(episode.id)}?${queryString(filters, { view })}`;
            return <EpisodeCard key={episode.id} episode={episode} timezone={filters.timezone} onOpen={() => nav(detailUrl)} onInvestigate={() => nav(`${detailUrl}#ai-investigation`)} />;
          })}</div>
        ) : <div className="p-12 text-center text-xs text-[#7b7d80]">{t("No changes match the selected view.", "Không có thay đổi phù hợp với bộ lọc.")}</div>}
      </Panel>
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
  return (
    <Page eyebrow={t("Changes", "Thay đổi")} title={episode.subject.name} description={episode.summary} actions={<div className="flex flex-wrap gap-2"><button type="button" onClick={() => aiSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} className="btn border-[#b877d9]/50 text-[#b877d9]"><BrainCircuit size={13} />{t("Investigate with AI", "Điều tra bằng AI")}</button><button type="button" onClick={() => nav(`/changes?${queryString(filters, { view: searchParams.get("view") || "attention" })}`)} className="btn"><ArrowLeft size={13} />{t("Back to Changes", "Quay lại Changes")}</button></div>}>
      <div className="flex flex-wrap items-center gap-3 border border-[#2a2d30] bg-[#111217] p-3">
        <EpisodeStatusBadge episode={episode} />
        <EpisodeWorkflowBadge episode={episode} />
        <span className="text-[11px] text-[#a7a9ab]">{t("Started", "Bắt đầu")} {formatEpisodeTime(episode.started_at, true, filters.timezone)} · {t("Last observed", "Quan sát gần nhất")} {formatEpisodeTime(episode.last_seen_at, true, filters.timezone)}</span>
        <span className="ml-auto text-[10px] text-[#7b7d80]">{episode.signal_count} {t("signals grouped", "tín hiệu đã nhóm")}</span>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_.8fr]">
        <div className="space-y-4">
          <Panel title={t("What changed", "Điều gì đã thay đổi")} subtitle={t("Observed facts compared with normal behavior.", "Sự kiện quan sát được so với hành vi bình thường.")}><EpisodeMetricTable episode={episode} /></Panel>
          <Panel title={t("Relationship path", "Đường quan hệ")} subtitle={t("Focused Service → API context", "Ngữ cảnh Service → API tập trung")}><div className="p-4"><EpisodePath episode={episode} /></div></Panel>
          <Panel title={t("Timeline", "Dòng thời gian")} subtitle={t("Correlated signals in time order", "Tín hiệu tương quan theo thời gian")}><EpisodeTimeline episode={episode} timezone={filters.timezone} /></Panel>
        </div>

        <div className="space-y-4">
          <Panel title={t("Why this state", "Vì sao có trạng thái này")} subtitle={t("Evidence used to evaluate the change.", "Bằng chứng dùng để đánh giá thay đổi.")}>
            <div className="space-y-3 p-3">
              {(episode.abnormality?.reasons || []).map((reason) => <div key={reason} className="border-l-2 border-[#5794f2] pl-2 text-[11px] text-[#d8d9da]">{reason}</div>)}
              {!!episode.abnormality?.domains?.length && <div className="flex flex-wrap gap-1.5">{episode.abnormality.domains.map((domain) => <span key={domain} className="border border-[#34373b] bg-[#181b1f] px-2 py-1 text-[10px] uppercase text-[#a7a9ab]">{domain}</span>)}</div>}
            </div>
          </Panel>
          <Panel title={t("Evidence", "Bằng chứng")} subtitle={t("Detector facts supporting this episode", "Dữ kiện detector hỗ trợ episode")}><EpisodeEvidence episode={episode} /></Panel>
          <EpisodeBaselineNote episode={episode} />
          <Panel title={t("Actions", "Thao tác")} subtitle={t("Review actions apply to this episode's source finding.", "Thao tác review áp dụng cho finding nguồn của episode này.")}><div className="flex flex-wrap gap-2 p-3"><button type="button" onClick={() => nav(`/traces?${queryString(filters, { principal: episode.subject.type === "user" ? episode.subject.name : undefined, service: episode.context.target || undefined })}`)} className="btn"><Activity size={13} />{t("View related traces", "Xem Trace liên quan")}</button><button type="button" onClick={() => nav(`${episode.subject.type === "user" ? `/users/${encodeURIComponent(episode.subject.name)}/activity` : `/services/${encodeURIComponent(episode.subject.name)}`}?${queryString(filters)}`)} className="btn"><ArrowRight size={13} />{t(`Open ${episode.subject.type}`, `Mở ${episode.subject.type}`)}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("expected")} className="btn text-[#73bf69]">{canMarkEpisodeExpected(episode) ? t("Expected behavior", "Hành vi dự kiến") : t("Suppress finding", "Ẩn finding")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("investigate")} className="btn text-[#ff9830]">{t("Keep monitoring", "Tiếp tục theo dõi")}</button><button type="button" disabled={decision.isPending} onClick={() => decision.mutate("resolve")} className="btn">{t("Resolve", "Đã xử lý")}</button></div>{decision.isError && <div className="border-t border-[#2a2d30] p-3 text-xs text-[#f2495c]">{decision.error instanceof Error ? decision.error.message : t("Decision could not be saved", "Không thể lưu quyết định")}</div>}{decision.isSuccess && <div className="border-t border-[#2a2d30] p-3 text-xs text-[#73bf69]">{t("Decision saved", "Đã lưu quyết định")}</div>}</Panel>
        </div>
      </div>

      <div id="ai-investigation" ref={aiSectionRef} className="scroll-mt-20">
        <Panel title={t("AI investigation", "Điều tra AI")} subtitle={t("LLM analysis is attached to this episode and never replaces detector evidence.", "Phân tích LLM gắn với episode này và không thay thế bằng chứng detector.")} className="mt-4" action={<BrainCircuit size={15} className="text-[#b877d9]" />}>
          {findingRef ? <InvestigationPanel findingRef={findingRef} initialScore={episode.score} initialSeverity={episode.severity} initialExplanation={episode.explanation} initialEntityId={episode.context.target || episode.subject.name} /> : <div className="p-4 text-xs text-[#7b7d80]">{t("AI analysis is unavailable because this episode has no source finding.", "Không thể phân tích AI vì episode chưa có finding nguồn.")}</div>}
        </Panel>
      </div>
    </Page>
  );
}

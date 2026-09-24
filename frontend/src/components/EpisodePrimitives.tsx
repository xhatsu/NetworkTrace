import { ArrowRight, CheckCircle2, Clock3, Activity, AlertTriangle, UserRound, Boxes, CircleDot, KeyRound } from "lucide-react";
import type { ReactNode } from "react";
import { useI18n } from "../i18n";
import type { FindingRef } from "../investigations";
import { n } from "../components";

export type EpisodeHighlight = {
  label: string;
  before: unknown;
  after: unknown;
  unit?: string | null;
  delta?: number | null;
};

export type Episode = {
  id: string;
  source?: "anomaly" | "principal_change";
  source_id?: string;
  subject: { type: "user" | "service"; name: string };
  summary: string;
  explanation: string;
  started_at: number;
  last_seen_at: number;
  context: {
    caller?: string | null;
    target?: string | null;
    operation?: string | null;
    source_ip?: string | null;
  };
  highlights: EpisodeHighlight[];
  evidence: Array<{ label: string; detector: string; detail: string }>;
  signal_count: number;
  signal_ids?: string[];
  signals?: Array<{ id: string; source: string; type: string; detected_at: number }>;
  timeline?: Array<{ at: number; type: string; source: string }>;
  state: "expected" | "changed" | "needs_attention" | "critical";
  abnormality?: {
    state: "expected" | "changed" | "needs_attention" | "critical";
    is_abnormal: boolean;
    correlated: boolean;
    infrastructure_only: boolean;
    domains: string[];
    reasons: string[];
    evaluation_version: string;
  };
  severity: string;
  status: string;
  score?: number | null;
};

export type EpisodeResponse = {
  items: Episode[];
  count: number;
  total: number;
  summary?: {
    expected: number;
    changed: number;
    needs_attention: number;
    critical: number;
    changed_users: number;
    changed_services: number;
    reviewed?: number;
  };
};

export type EpisodeView = "all" | "attention" | "reviewed";

export function isEpisodeAttention(episode: Episode) {
  return ["needs_attention", "critical"].includes(episode.state) && episode.status !== "resolved";
}

export function isEpisodeReviewed(episode: Episode) {
  return episode.state === "expected" || episode.status === "resolved";
}

export function episodeMatchesView(episode: Episode, view: EpisodeView) {
  if (view === "attention") return isEpisodeAttention(episode);
  if (view === "reviewed") return isEpisodeReviewed(episode);
  return true;
}

export function episodeSearchText(episode: Episode) {
  return [
    episode.subject.name,
    episode.summary,
    episode.explanation,
    episode.context.caller,
    episode.context.target,
    episode.context.operation,
    episode.context.source_ip,
    ...episode.evidence.flatMap((item) => [item.label, item.detail]),
  ].filter(Boolean).join(" ").toLowerCase();
}

export function episodeFindingRef(episode: Episode): FindingRef | null {
  const sourceId = episode.source_id || episode.id.replace(/^(anm|chg)-/, "");
  const source = episode.source || (episode.id.startsWith("anm-") ? "anomaly" : episode.id.startsWith("chg-") ? "principal_change" : undefined);
  if (!sourceId || !/^[1-9][0-9]{0,19}$/.test(sourceId)) return null;
  if (source === "anomaly") return { kind: "anomaly_event", anomaly_event_id: sourceId };
  if (source === "principal_change") return { kind: "principal_change_event", principal_change_event_id: sourceId };
  return null;
}

export function episodeStatusLabel(state: Episode["state"], t: (key: string, fallback?: string) => string) {
  if (state === "expected") return t("Expected", "Đã xác nhận");
  if (state === "critical") return t("Critical", "Nghiêm trọng");
  if (state === "needs_attention") return t("Needs attention", "Cần chú ý");
  return t("Changed", "Đã thay đổi");
}

export function episodeStatusClass(state: Episode["state"]) {
  if (state === "expected") return "border-[#73bf69]/60 bg-[#73bf69]/10 text-[#73bf69]";
  if (state === "critical") return "border-[#f2495c]/60 bg-[#f2495c]/10 text-[#f2495c]";
  if (state === "needs_attention") return "border-[#ff9830]/60 bg-[#ff9830]/10 text-[#ff9830]";
  return "border-[#5794f2]/60 bg-[#5794f2]/10 text-[#5794f2]";
}

export function episodeCategory(episode: Episode) {
  const types = [episode.signals?.[0]?.type, ...episode.evidence.map((item) => item.detector)].filter(Boolean).join(" ").toLowerCase();
  if (types.includes("latency") || types.includes("performance")) return "performance";
  if (types.includes("error") || types.includes("failure")) return "errors";
  if (types.includes("source_ip") || types.includes("network")) return "network";
  if (types.includes("auth")) return "authentication";
  if (types.includes("tps") || types.includes("traffic") || types.includes("rate") || types.includes("surge")) return "traffic";
  return "access";
}

function changeTitle(episode: Episode, t: (key: string, fallback?: string) => string) {
  const type = [episode.signals?.[0]?.type, ...episode.evidence.map((item) => item.detector)].join(" ").toLowerCase();
  const operation = episode.context.operation;
  const target = episode.context.target;
  if (type.includes("new_operation") && operation) return `${t("Started using", "Bắt đầu sử dụng")} ${operation}`;
  if ((type.includes("new_target") || type.includes("new_service")) && target) return `${t("Started accessing", "Bắt đầu truy cập")} ${target}`;
  if (type.includes("latency")) return t("Response latency increased above normal", "Độ trễ phản hồi tăng cao hơn mức bình thường");
  if (type.includes("error") || type.includes("failure")) return t("HTTP errors increased significantly", "Lỗi HTTP tăng đáng kể");
  if (type.includes("drop")) return t("Traffic dropped below normal", "Lưu lượng giảm dưới mức bình thường");
  if (type.includes("spike") || type.includes("surge") || type.includes("rate")) return t("Traffic increased significantly above normal", "Lưu lượng tăng đáng kể so với mức bình thường");
  if (type.includes("new_source_ip")) return t("A new source address appeared", "Xuất hiện địa chỉ nguồn mới");
  return t("Behavior changed compared with normal", "Hành vi thay đổi so với mức bình thường");
}

export function episodeTitle(episode: Episode, t: (key: string, fallback?: string) => string) {
  return changeTitle(episode, t);
}

export function formatEpisodeTime(value: number, withDate = true, timezone = "local") {
  if (!value) return "—";
  const options: Intl.DateTimeFormatOptions = withDate
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" };
  if (timezone !== "local") options.timeZone = timezone;
  return new Date(value).toLocaleString([], options);
}

function displayValue(value: unknown, unit?: string | null) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return `${n(value, 2)}${unit ? ` ${unit}` : ""}`;
  return String(value);
}

export function EpisodeStatusBadge({ episode }: { episode: Episode }) {
  const { t } = useI18n();
  const Icon = episode.state === "expected" ? CheckCircle2 : episode.state === "critical" ? AlertTriangle : episode.state === "needs_attention" ? Activity : Clock3;
  return (
    <span className={`inline-flex items-center gap-1.5 border px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${episodeStatusClass(episode.state)}`}>
      <Icon size={11} /> {episodeStatusLabel(episode.state, t)}
    </span>
  );
}

export function EpisodeWorkflowBadge({ episode }: { episode: Episode }) {
  const { t } = useI18n();
  const resolved = episode.status === "resolved";
  const monitoring = ["acknowledged", "investigating"].includes(episode.status);
  const label = resolved ? t("Resolved", "Đã xử lý") : monitoring ? t("Monitoring", "Đang theo dõi") : t("Open", "Đang mở");
  const tone = resolved ? "text-[#73bf69]" : monitoring ? "text-[#ff9830]" : "text-[#a7a9ab]";
  return <span className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide ${tone}`}><CircleDot size={10} />{label}</span>;
}

export type EntityKind = "user" | "service" | "api" | "ip";

export function entityTokenClass(kind: EntityKind) {
  if (kind === "user") return "border-[#b877d9]/55 bg-[#b877d9]/10 text-[#d9b4ea]";
  if (kind === "service") return "border-[#5794f2]/55 bg-[#5794f2]/10 text-[#8db7fa]";
  if (kind === "api") return "border-[#56b9a8]/55 bg-[#56b9a8]/10 text-[#82d5c4]";
  return "border-[#34373b] bg-[#181b1f] text-[#a7a9ab]";
}

export function EntityToken({ kind, children }: { kind: EntityKind; children: ReactNode }) {
  return <span className={`inline-flex max-w-full items-center border px-2 py-1 font-mono text-[11px] ${entityTokenClass(kind)}`}>{children}</span>;
}

export function EpisodePath({ episode, compact = false }: { episode: Episode; compact?: boolean }) {
  const { t } = useI18n();
  const isPrincipalEpisode = episode.subject.type === "user";
  const subjectIsRelationshipService = episode.subject.type === "service"
    && [episode.context.caller, episode.context.target].includes(episode.subject.name);
  const nodes = [
    !isPrincipalEpisode && !subjectIsRelationshipService && {
      value: episode.subject.name,
      kind: episode.subject.type,
      label: t("Service", "Service"),
    },
    episode.context.caller && {
      value: episode.context.caller,
      kind: "service" as const,
      label: t("Caller Service", "Caller Service"),
    },
    episode.context.target && {
      value: episode.context.target,
      kind: "service" as const,
      label: t("Target Service", "Target Service"),
    },
    episode.context.operation && {
      value: episode.context.operation,
      kind: "api" as const,
      label: t("API / Operation", "API / Operation"),
    },
  ].filter(Boolean) as Array<{ value: string; kind: EntityKind; label: string }>;
  return (
    <div className={compact ? "" : "py-1"}>
      {isPrincipalEpisode && (
        <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 text-[10px] text-[#a7a9ab]">
          <span className="inline-flex items-center gap-1 font-semibold uppercase tracking-[.1em] text-[#7b7d80]"><KeyRound size={11} className="text-[#d9b4ea]" />{t("Credential observed on this call", "Credential quan sát trên call này")}</span>
          <EntityToken kind="user">{episode.subject.name}</EntityToken>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-1.5 text-[11px]">
        {nodes.length ? nodes.map((node, index) => (
          <span key={`${node.label}-${node.value}-${index}`} className="flex items-end gap-1.5">
            {index > 0 && <ArrowRight size={12} className="mb-1.5 shrink-0 text-[#7b7d80]" aria-hidden="true" />}
            <span className="min-w-0">
              <span className="mb-1 block text-[9px] font-semibold uppercase tracking-[.12em] text-[#7b7d80]">{node.label}</span>
              <EntityToken kind={node.kind}>{node.value}</EntityToken>
            </span>
          </span>
        )) : <span className="text-[#7b7d80]">{t("Relationship context unavailable", "Chưa có ngữ cảnh quan hệ")}</span>}
      </div>
      {!compact && nodes.length > 1 && (
        <p className="mt-3 max-w-4xl text-[10px] leading-4 text-[#7b7d80]">
          {isPrincipalEpisode
            ? t(
              "The Caller Service used or forwarded this observed credential when calling the Target Service and API. Open a related Trace to confirm the exact request chain and credential propagation.",
              "Caller Service đã sử dụng hoặc chuyển tiếp credential được quan sát này khi gọi Target Service và API. Mở Trace liên quan để xác nhận chuỗi request và việc truyền credential chính xác.",
            )
            : t(
              "This is the observed logical Service relationship. Open a related Trace to confirm the exact request chain.",
              "Đây là quan hệ Service logic đã quan sát. Mở Trace liên quan để xác nhận chuỗi request chính xác.",
            )}
        </p>
      )}
    </div>
  );
}

export function EpisodeCard({ episode, onOpen, onInvestigate, timezone = "local" }: { episode: Episode; onOpen: () => void; onInvestigate?: () => void; timezone?: string }) {
  const { t } = useI18n();
  const Icon = episode.subject.type === "user" ? UserRound : Boxes;
  return (
    <article className="border-b border-[#2a2d30] bg-[#111217] p-4 transition hover:bg-[#181b1f]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <EpisodeStatusBadge episode={episode} />
            <EpisodeWorkflowBadge episode={episode} />
            <span className="text-[10px] text-[#7b7d80]">{t("Last observed", "Quan sát gần nhất")} {formatEpisodeTime(episode.last_seen_at, true, timezone)}</span>
          </div>
          <h3 className="mt-2 flex items-center gap-2 text-sm font-semibold text-[#d8d9da]"><Icon size={14} className="text-[#5794f2]" />{episodeTitle(episode, t)}</h3>
          <div className="mt-2"><EpisodePath episode={episode} compact /></div>
          {episode.abnormality?.reasons?.[0] && <p className="mt-2 text-[11px] text-[#a7a9ab]">{episode.abnormality.reasons[0]}</p>}
        </div>
        <div className="flex shrink-0 gap-2">
          <button type="button" onClick={onOpen} className="btn h-7 px-2.5 text-[11px]">{t("View details", "Xem chi tiết")} <ArrowRight size={12} /></button>
          {onInvestigate && <button type="button" onClick={onInvestigate} className="btn h-7 border-[#b877d9]/50 px-2.5 text-[11px] text-[#b877d9]">{t("Investigate", "Điều tra")}</button>}
        </div>
      </div>
      {episode.highlights.length > 0 && (
        <div className="mt-3 grid gap-2 border-t border-[#2a2d30] pt-3 sm:grid-cols-2">
          {episode.highlights.slice(0, 2).map((highlight) => (
            <div key={`${highlight.label}-${String(highlight.after)}`} className="border-l-2 border-[#34373b] pl-2">
              <div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t(highlight.label, highlight.label)}</div>
              <div className="mt-1 font-mono text-xs text-[#d8d9da]">{displayValue(highlight.before, highlight.unit)} <span className="text-[#7b7d80]">→</span> {displayValue(highlight.after, highlight.unit)}</div>
              {highlight.before == null && highlight.after != null
                ? <div className="mt-0.5 text-[10px] font-semibold uppercase text-[#5794f2]">{t("Added", "Mới xuất hiện")}</div>
                : highlight.delta != null && <div className="mt-0.5 font-mono text-[10px] text-[#a7a9ab]">{Number(highlight.delta) >= 0 ? "+" : ""}{Number(highlight.delta).toFixed(1)}%</div>}
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-[#7b7d80]">
        <span>{episode.signal_count} {t("supporting signals", "tín hiệu hỗ trợ")}</span>
      </div>
    </article>
  );
}

export function EpisodeMetricTable({ episode }: { episode: Episode }) {
  const { t } = useI18n();
  if (!episode.highlights.length) return <div className="p-4 text-xs text-[#7b7d80]">{t("No metric comparison available", "Chưa có so sánh chỉ số")}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-xs">
        <thead><tr className="border-b border-[#2a2d30] text-[10px] uppercase tracking-wide text-[#7b7d80]"><th className="px-3 py-2">{t("Metric", "Chỉ số")}</th><th className="px-3 py-2">{t("Normal", "Bình thường")}</th><th className="px-3 py-2">{t("During change", "Trong thay đổi")}</th><th className="px-3 py-2 text-right">{t("Difference", "Chênh lệch")}</th></tr></thead>
        <tbody className="divide-y divide-[#2a2d30]">
          {episode.highlights.map((highlight) => <tr key={`${highlight.label}-${String(highlight.after)}`}><td className="px-3 py-2 font-semibold text-[#d8d9da]">{t(highlight.label, highlight.label)}</td><td className="px-3 py-2 font-mono text-[#a7a9ab]">{displayValue(highlight.before, highlight.unit)}</td><td className="px-3 py-2 font-mono text-[#d8d9da]">{displayValue(highlight.after, highlight.unit)}{highlight.before == null && highlight.after != null && <span className="ml-2 text-[9px] font-sans font-semibold uppercase text-[#5794f2]">{t("Added", "Mới")}</span>}</td><td className="px-3 py-2 text-right font-mono text-[#a7a9ab]">{highlight.delta == null ? "—" : `${Number(highlight.delta) >= 0 ? "+" : ""}${Number(highlight.delta).toFixed(1)}%`}</td></tr>)}
        </tbody>
      </table>
    </div>
  );
}

export function EpisodeTimeline({ episode, timezone = "local" }: { episode: Episode; timezone?: string }) {
  const { t } = useI18n();
  const timeline = episode.timeline || (episode.signals || []).map((signal) => ({ at: signal.detected_at, type: signal.type, source: signal.source }));
  return (
    <div className="divide-y divide-[#2a2d30]">
      {timeline.length ? timeline.map((item, index) => <div key={`${item.type}-${item.at}-${index}`} className="flex items-center gap-3 px-3 py-2.5 text-[11px]"><span className="w-32 shrink-0 font-mono text-[#7b7d80]">{formatEpisodeTime(item.at, true, timezone)}</span><span className="h-1.5 w-1.5 rounded-full bg-[#5794f2]" /><span className="text-[#d8d9da]">{t(item.type, item.type.replaceAll("_", " "))}</span><span className="ml-auto text-[10px] uppercase text-[#7b7d80]">{item.source}</span></div>) : <div className="p-4 text-xs text-[#7b7d80]">{t("No timeline evidence available", "Chưa có bằng chứng dòng thời gian")}</div>}
    </div>
  );
}

export function EpisodeEvidence({ episode }: { episode: Episode }) {
  const { t } = useI18n();
  return (
    <div className="divide-y divide-[#2a2d30]">
      {episode.evidence.length ? episode.evidence.map((item) => <div key={`${item.detector}-${item.label}`} className="flex gap-2.5 p-3"><CircleDot size={14} className="mt-0.5 shrink-0 text-[#5794f2]" /><div className="min-w-0"><div className="text-xs font-semibold text-[#d8d9da]">{t(item.label, item.label)}</div><div className="mt-1 text-[11px] text-[#a7a9ab]">{item.detail}</div><details className="mt-1"><summary className="cursor-pointer text-[10px] text-[#7b7d80]">{t("Technical detector detail", "Chi tiết detector kỹ thuật")}</summary><div className="mt-1 font-mono text-[10px] text-[#7b7d80]">{item.detector}</div></details></div></div>) : <div className="p-4 text-xs text-[#7b7d80]">{t("No evidence available", "Chưa có bằng chứng")}</div>}
    </div>
  );
}

export function EpisodeBaselineNote({ episode }: { episode: Episode }) {
  const { t } = useI18n();
  return <div className="border border-[#34373b] bg-[#181b1f] p-3 text-[11px] text-[#a7a9ab]"><span className="font-semibold text-[#d8d9da]">{t("Baseline context", "Ngữ cảnh baseline")}: </span>{episode.explanation || t("Compared with the established operating pattern.", "So với mô hình vận hành đã thiết lập.")}</div>;
}

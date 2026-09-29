import { ArrowRight, CheckCircle2, Clock3, Activity, AlertTriangle, UserRound, Boxes, CircleDot, KeyRound, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useI18n } from "../i18n";
import type { FindingRef } from "../investigations";
import { n } from "../components";
import { EntityLink } from "./EntityLink";
import type { EntityRef } from "../entityRoutes";

export type EpisodeHighlight = {
  label: string;
  before: unknown;
  after: unknown;
  unit?: string | null;
  delta?: number | null;
};

export type SemanticAssessment = {
  status: "not_evaluated" | "pending" | "succeeded" | "failed" | "stale";
  provider?: "jev" | null;
  provider_model?: string | null;
  provider_request_id?: string | null;
  assessment_version: "semantic-v1";
  episode_version?: string | null;
  abnormal_probability?: number | null;
  category?: "access_behavior" | "traffic" | "performance" | "errors" | "authentication" | "infrastructure" | "identity" | "mixed" | "normal_variation" | "insufficient_evidence" | null;
  category_confidence?: number | null;
  category_probabilities?: Record<string, number>;
  priority?: "informational" | "watch" | "investigate" | "urgent" | null;
  priority_confidence?: number | null;
  priority_probabilities?: Record<string, number>;
  recommendation?: "observe" | "inspect_traces" | "compare_baseline" | "review_access" | "check_dependencies" | "collect_evidence" | null;
  recommendation_confidence?: number | null;
  recommendation_probabilities?: Record<string, number>;
  input_signal_ids?: string[];
  summary?: string | null;
  supporting_signal_ids?: string[];
  caveats?: string[];
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number | null;
  evaluated_at?: number | null;
};

export type Episode = {
  id: string;
  episode_key?: string;
  episode_version?: string;
  semantic_assessment?: SemanticAssessment;
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
  state: "expected" | "changed" | "watch" | "needs_attention" | "critical";
  abnormality?: {
    state: "expected" | "changed" | "watch" | "needs_attention" | "critical";
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
    watch?: number;
    needs_attention: number;
    critical: number;
    changed_users: number;
    changed_services: number;
    reviewed?: number;
    l4_evaluated?: number;
    l4_pending?: number;
    l4_high_confidence?: number;
    l4_not_evaluated?: number;
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
  if (state === "watch") return t("Watch", "Theo dõi thêm");
  return t("Informational change", "Thay đổi thông tin");
}

export function episodeStatusClass(state: Episode["state"]) {
  if (state === "watch") return "border-[#b877d9]/60 bg-[#b877d9]/10 text-[#b877d9]";
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

/** Use the latest signal's metric when one episode contains repeated metrics. */
export function dedupeEpisodeHighlights(episode: Episode): EpisodeHighlight[] {
  const grouped = new Map<string, EpisodeHighlight>();
  for (const highlight of episode.highlights) {
    const key = `${highlight.label.trim().toLowerCase()}|${highlight.unit || ""}`;
    // _merge_signals orders signals newest first, so the first matching metric
    // is the episode's latest observed value. Picking the largest delta can
    // surface an old spike when the latest signal is a drop (or vice versa).
    if (!grouped.has(key)) grouped.set(key, highlight);
  }
  return [...grouped.values()];
}

export function formatHighlightDelta(highlight: EpisodeHighlight, t: (key: string, fallback?: string) => string) {
  const before = Number(highlight.before);
  const after = Number(highlight.after);
  if (Number.isFinite(before) && before === 0 && Number.isFinite(after) && after > 0) return t("New", "Mới");
  return highlight.delta == null ? "—" : `${Number(highlight.delta) >= 0 ? "+" : ""}${Number(highlight.delta).toFixed(1)}%`;
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

function assessmentCategoryLabel(category: NonNullable<SemanticAssessment["category"]>, t: (key: string, fallback?: string) => string) {
  const labels: Record<NonNullable<SemanticAssessment["category"]>, [string, string]> = {
    access_behavior: ["Access behavior", "Hành vi truy cập"],
    traffic: ["Traffic", "Lưu lượng"],
    performance: ["Performance", "Hiệu năng"],
    errors: ["Errors", "Lỗi"],
    authentication: ["Authentication", "Xác thực"],
    infrastructure: ["Infrastructure", "Hạ tầng"],
    identity: ["Identity", "Danh tính"],
    mixed: ["Mixed", "Hỗn hợp"],
    normal_variation: ["Normal variation", "Biến động bình thường"],
    insufficient_evidence: ["Insufficient evidence", "Chưa đủ bằng chứng"],
  };
  const [english, vietnamese] = labels[category];
  return t(english, vietnamese);
}

function assessmentPriorityLabel(priority: NonNullable<SemanticAssessment["priority"]>, t: (key: string, fallback?: string) => string) {
  const labels: Record<NonNullable<SemanticAssessment["priority"]>, [string, string]> = {
    informational: ["Informational", "Thông tin"],
    watch: ["Watch", "Theo dõi"],
    investigate: ["Investigate", "Điều tra"],
    urgent: ["Urgent", "Khẩn cấp"],
  };
  const [english, vietnamese] = labels[priority];
  return t(english, vietnamese);
}

export function SemanticAssessmentBadge({ assessment }: { assessment?: SemanticAssessment }) {
  const { t } = useI18n();
  const status = assessment?.status || "not_evaluated";
  const text = status === "succeeded" && assessment?.abnormal_probability != null
    ? `${t("AI", "AI")} ${Math.round(assessment.abnormal_probability * 100)}%${assessment.category ? ` · ${assessmentCategoryLabel(assessment.category, t)}` : ""}`
    : status === "pending" ? t("AI evaluating", "AI đang đánh giá")
      : status === "failed" ? t("AI unavailable", "AI không khả dụng")
        : status === "stale" ? t("AI stale", "AI đã cũ")
          : t("AI not evaluated", "AI chưa đánh giá");
  const tone = status === "succeeded" ? "border-[#b877d9]/50 bg-[#b877d9]/10 text-[#d9b4ea]"
    : status === "pending" ? "border-[#5794f2]/50 bg-[#5794f2]/10 text-[#8bb8fa]"
      : status === "failed" || status === "stale" ? "border-[#ff9830]/50 bg-[#ff9830]/10 text-[#ffb767]"
        : "border-[#34373b] bg-[#181b1f] text-[#a7a9ab]";
  return <span className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap border px-2 py-1 text-[10px] font-semibold ${tone}`}><Sparkles size={11} aria-hidden="true" />{text}</span>;
}

function recommendationLabel(value: NonNullable<SemanticAssessment["recommendation"]>, t: (en: string, vi: string) => string) {
  const labels = {
    observe: t("Monitor subsequent observation windows.", "Theo dõi các cửa sổ quan sát tiếp theo."),
    inspect_traces: t("Inspect related slow or failed Traces.", "Kiểm tra các Trace chậm hoặc thất bại có liên quan."),
    compare_baseline: t("Compare traffic, Latency and errors with Baseline windows.", "So sánh lưu lượng, Latency và lỗi với các cửa sổ Baseline."),
    review_access: t("Review caller, credential, target and authentication evidence.", "Rà soát bằng chứng về Service gọi, thông tin định danh, đích và xác thực."),
    check_dependencies: t("Check downstream dependencies and recent routing or deployment changes.", "Kiểm tra Service phụ thuộc và thay đổi định tuyến hoặc triển khai gần đây."),
    collect_evidence: t("Collect more telemetry to verify Baseline, persistence and attribution.", "Thu thập thêm telemetry để xác minh Baseline, tính kéo dài và nguồn phát sinh."),
  };
  return labels[value];
}

export function SemanticAssessmentSummary({ episode, full = false, timezone = "local" }: { episode: Episode; full?: boolean; timezone?: string }) {
  const { t } = useI18n();
  const assessment = episode.semantic_assessment;
  const status = assessment?.status || "not_evaluated";
  const stale = status === "stale";
  const succeeded = status === "succeeded" || stale;
  const categoryProbabilities = Object.entries(assessment?.category_probabilities || {})
    .filter(([, probability]) => probability > 0.005).sort((left, right) => right[1] - left[1]).slice(0, 4);
  const priorityProbabilities = Object.entries(assessment?.priority_probabilities || {})
    .filter(([, probability]) => probability > 0.005).sort((left, right) => right[1] - left[1]).slice(0, 3);

  if (!full) {
    if (status !== "succeeded" || !assessment) return null;
    return <div className="mt-2 border-l-2 border-[#b877d9]/60 pl-2">
      <div className="text-[10px] font-semibold uppercase tracking-[.12em] text-[#b877d9]">{t("L4 assessment", "Đánh giá L4")}{assessment.category ? ` · ${assessmentCategoryLabel(assessment.category, t)}` : ""}{assessment.priority ? ` · ${assessmentPriorityLabel(assessment.priority, t)}` : ""}</div>
      <p className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-[#c9c1d1]">{(assessment.recommendation ? recommendationLabel(assessment.recommendation, t) : assessment.summary) || t("Typed decision from Jev; see the detail panel for category and priority probabilities.", "Jev trả về quyết định có kiểu dữ liệu; xem bảng chi tiết để biết xác suất danh mục và ưu tiên.")}</p>
    </div>;
  }

  return <section aria-labelledby={`semantic-assessment-${episode.id}`} className="min-w-0 h-full border border-[#34373b] bg-[#111217]">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2a2d30] px-3 py-2.5">
      <h2 id={`semantic-assessment-${episode.id}`} className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.12em] text-[#d9b4ea]"><Sparkles size={13} aria-hidden="true" />{t("Jev AI result", "Kết quả Jev AI")}</h2>
      <SemanticAssessmentBadge assessment={assessment} />
    </div>
    {succeeded && assessment ? <div className="space-y-3 p-3">
      {stale && <p role="status" className="border-l-2 border-[#ff9830] pl-2 text-[11px] text-[#ffb767]">{t("This assessment uses an earlier evidence version and may no longer match the current episode.", "Đánh giá này dùng phiên bản bằng chứng trước đó và có thể không còn khớp với episode hiện tại.")}</p>}
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-[11px]">
        {assessment.abnormal_probability != null && <div><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t("Abnormal probability", "Xác suất bất thường")}</div><div className="mt-1 font-mono text-lg font-semibold text-[#d9b4ea]">{Math.round(assessment.abnormal_probability * 100)}%</div></div>}
        {assessment.category && <div><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t("Category · confidence", "Danh mục · độ tin cậy")}</div><div className="mt-1 text-xs text-[#d8d9da]">{assessmentCategoryLabel(assessment.category, t)}{assessment.category_confidence != null ? ` · ${Math.round(assessment.category_confidence * 100)}%` : ""}</div></div>}
        {assessment.priority && <div><div className="text-[10px] uppercase tracking-wide text-[#7b7d80]">{t("Priority · confidence", "Ưu tiên · độ tin cậy")}</div><div className="mt-1 text-xs text-[#d8d9da]">{assessmentPriorityLabel(assessment.priority, t)}{assessment.priority_confidence != null ? ` · ${Math.round(assessment.priority_confidence * 100)}%` : ""}</div></div>}
      </div>
      {assessment.recommendation && <div className="space-y-1 text-xs leading-5 text-[#d8d9da]">
        <div className="font-semibold">{stale ? t("Previous advisory recommendation", "Khuyến nghị tham khảo trước đây") : t("Advisory recommendation", "Khuyến nghị tham khảo")}{assessment.recommendation_confidence != null ? ` · ${Math.round(assessment.recommendation_confidence * 100)}%` : ""}</div>
        <p>{recommendationLabel(assessment.recommendation, t)}</p>
        <p className="text-[11px] text-[#a7a9ab]">{t("Advisory only. TraceScope state and severity remain authoritative; no action is executed.", "Chỉ mang tính tham khảo. Trạng thái và mức độ nghiêm trọng của TraceScope vẫn là căn cứ chính; không có hành động tự động.")}</p>
        {!!assessment.input_signal_ids?.length && <details className="text-[11px] text-[#a7a9ab]"><summary className="cursor-pointer">{t("Submitted evidence", "Bằng chứng đã gửi")} ({assessment.input_signal_ids.length})</summary><p className="mt-1 break-words">{assessment.input_signal_ids.join(", ")}</p></details>}
      </div>}
      {assessment.summary && <p className="max-w-4xl text-xs leading-5 text-[#d8d9da]">{assessment.summary}</p>}
      {(categoryProbabilities.length > 0 || priorityProbabilities.length > 0) && <div className="grid gap-3 sm:grid-cols-2">
        {categoryProbabilities.length > 0 && <div>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-[#7b7d80]">{t("Category probabilities", "Xác suất danh mục")}</div>
          <ul className="space-y-1">{categoryProbabilities.map(([category, probability]) => <li key={category} className="flex items-center justify-between gap-2 text-[10px] text-[#c4bdd9]"><span>{assessmentCategoryLabel(category as NonNullable<SemanticAssessment["category"]>, t)}</span><span className="font-mono">{Math.round(probability * 100)}%</span></li>)}</ul>
        </div>}
        {priorityProbabilities.length > 0 && <div>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-[#7b7d80]">{t("Priority probabilities", "Xác suất ưu tiên")}</div>
          <ul className="space-y-1">{priorityProbabilities.map(([priority, probability]) => <li key={priority} className="flex items-center justify-between gap-2 text-[10px] text-[#c4bdd9]"><span>{assessmentPriorityLabel(priority as NonNullable<SemanticAssessment["priority"]>, t)}</span><span className="font-mono">{Math.round(probability * 100)}%</span></li>)}</ul>
        </div>}
      </div>}
      <p className="max-w-4xl border-l-2 border-[#5794f2]/50 pl-2 text-[10px] leading-4 text-[#a7a9ab]">{t("Jev returns typed decisions and probabilities, not a generated explanation or per-signal attribution. Use the L3 evidence and rationale for the underlying facts.", "Jev trả về quyết định và xác suất có kiểu dữ liệu, không tạo giải thích bằng văn bản hoặc gán theo từng tín hiệu. Xem bằng chứng và lý do L3 để biết các dữ kiện nền.")}</p>
      {!!assessment.caveats?.length && <div><div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-[#7b7d80]">{t("Caveats", "Lưu ý")}</div><ul className="space-y-1">{assessment.caveats.map((caveat, index) => <li key={`${caveat}-${index}`} className="border-l-2 border-[#ff9830]/60 pl-2 text-[11px] leading-4 text-[#c4bdd9]">{caveat}</li>)}</ul></div>}
      <div className="border-t border-[#2a2d30] pt-2 text-[10px] text-[#7b7d80]">{assessment.provider === "jev" ? "Jev" : t("Semantic provider", "Nhà cung cấp ngữ nghĩa")} · {assessment.provider_model || assessment.assessment_version}{assessment.evaluated_at ? ` · ${formatEpisodeTime(assessment.evaluated_at, true, timezone)}` : ""}{assessment.input_tokens != null ? ` · ${assessment.input_tokens} ${t("input tokens", "token đầu vào")}` : ""}{assessment.cost_usd != null ? ` · $${assessment.cost_usd.toFixed(6)}` : ""}</div>
    </div> : <div className="p-3 text-[11px] leading-4 text-[#a7a9ab]">
      {status === "pending" ? t("An automatic semantic assessment is in progress.", "Đang thực hiện đánh giá ngữ nghĩa tự động.")
        : status === "failed" ? t("The semantic assessment could not be completed. Deterministic L3 state remains authoritative.", "Không thể hoàn tất đánh giá ngữ nghĩa. Trạng thái L3 xác định vẫn là căn cứ chính.")
          : t("No semantic assessment is stored for this episode version yet.", "Chưa có đánh giá ngữ nghĩa được lưu cho phiên bản episode này.")}
    </div>}
  </section>;
}

export type EntityKind = "user" | "service" | "api" | "ip";

export function entityTokenClass(kind: EntityKind) {
  if (kind === "user") return "border-[#b877d9]/55 bg-[#b877d9]/10 text-[#d9b4ea]";
  if (kind === "service") return "border-[#5794f2]/55 bg-[#5794f2]/10 text-[#8db7fa]";
  if (kind === "api") return "border-[#56b9a8]/55 bg-[#56b9a8]/10 text-[#82d5c4]";
  return "border-[#34373b] bg-[#181b1f] text-[#a7a9ab]";
}

export function EntityToken({ kind, entity, children }: { kind: EntityKind; entity?: EntityRef; children: ReactNode }) {
  const className = `inline-flex max-w-full items-center border px-2 py-1 font-mono text-[11px] ${entityTokenClass(kind)}`;
  if (!entity) return <span className={className}>{children}</span>;
  return <EntityLink entity={entity} className={className}>{children}</EntityLink>;
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
  const apiService = episode.context.target
    || (episode.subject.type === "service" ? episode.subject.name : undefined)
    || episode.context.caller;
  return (
    <div className={compact ? "" : "py-1"}>
      {isPrincipalEpisode && (
        <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 text-[10px] text-[#a7a9ab]">
          <span className="inline-flex items-center gap-1 font-semibold uppercase tracking-[.1em] text-[#7b7d80]"><KeyRound size={11} className="text-[#d9b4ea]" />{t("Credential observed on this call", "Credential quan sát trên call này")}</span>
          <EntityToken kind="user" entity={{ kind: "user", principal: episode.subject.name }}>{episode.subject.name}</EntityToken>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-1.5 text-[11px]">
        {nodes.length ? nodes.map((node, index) => (
          <span key={`${node.label}-${node.value}-${index}`} className="flex items-end gap-1.5">
            {index > 0 && <ArrowRight size={12} className="mb-1.5 shrink-0 text-[#7b7d80]" aria-hidden="true" />}
            <span className="min-w-0">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[.12em] text-[#7b7d80]">{node.label}</span>
              <EntityToken
                kind={node.kind}
                entity={node.kind === "user"
                  ? { kind: "user", principal: node.value }
                  : node.kind === "service"
                    ? { kind: "service", name: node.value }
                    : node.kind === "api" && apiService
                      ? { kind: "api", service: apiService, operation: node.value }
                      : undefined}
              >{node.value}</EntityToken>
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

export function EpisodeCard({ episode, onInvestigate, detailSearch = "", timezone = "local" }: { episode: Episode; onInvestigate?: () => void; detailSearch?: string; timezone?: string }) {
  const { t } = useI18n();
  const Icon = episode.subject.type === "user" ? UserRound : Boxes;
  return (
    <article className="border-b border-[#2a2d30] bg-[#111217] p-4 transition hover:bg-[#181b1f]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <EpisodeStatusBadge episode={episode} />
            <EpisodeWorkflowBadge episode={episode} />
            <SemanticAssessmentBadge assessment={episode.semantic_assessment} />
            <span className="text-[10px] text-[#7b7d80]">{t("Last observed", "Quan sát gần nhất")} {formatEpisodeTime(episode.last_seen_at, true, timezone)}</span>
          </div>
          <h3 className="mt-2 flex items-center gap-2 text-sm font-semibold text-[#d8d9da]"><Icon size={14} className="text-[#5794f2]" />{episodeTitle(episode, t)}</h3>
          <div className="mt-2"><EpisodePath episode={episode} compact /></div>
          {episode.abnormality?.reasons?.[0] && <p className="mt-2 text-[11px] text-[#a7a9ab]">{episode.abnormality.reasons[0]}</p>}
          <SemanticAssessmentSummary episode={episode} />
        </div>
        <div className="flex shrink-0 gap-2">
          <EntityLink entity={{ kind: "change", id: episode.id }} search={detailSearch} className="btn h-7 px-2.5 text-[11px]">
            {t("View details", "Xem chi tiết")} <ArrowRight size={12} />
          </EntityLink>
          {onInvestigate && <button type="button" onClick={onInvestigate} className="btn h-7 border-[#b877d9]/50 px-2.5 text-[11px] text-[#b877d9]">{t("Deep investigate", "Điều tra chuyên sâu")}</button>}
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
  const highlights = dedupeEpisodeHighlights(episode);
  if (!highlights.length) return <div className="p-4 text-xs text-[#7b7d80]">{t("No metric comparison available", "Chưa có so sánh chỉ số")}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-xs">
        <thead><tr className="border-b border-[#2a2d30] text-[10px] uppercase tracking-wide text-[#7b7d80]"><th className="px-3 py-2">{t("Metric", "Chỉ số")}</th><th className="px-3 py-2">{t("Detector reference", "Tham chiếu detector")}</th><th className="px-3 py-2">{t("Observed value", "Giá trị quan sát")}</th><th className="px-3 py-2 text-right">{t("Difference", "Chênh lệch")}</th></tr></thead>
        <tbody className="divide-y divide-[#2a2d30]">
          {highlights.map((highlight) => <tr key={`${highlight.label}-${highlight.unit || ""}`}><td className="px-3 py-2 font-semibold text-[#d8d9da]">{t(highlight.label, highlight.label)}</td><td className="px-3 py-2 font-mono text-[#a7a9ab]">{displayValue(highlight.before, highlight.unit)}</td><td className="px-3 py-2 font-mono text-[#d8d9da]">{displayValue(highlight.after, highlight.unit)}{highlight.before == null && highlight.after != null && <span className="ml-2 text-[10px] font-sans font-semibold uppercase text-[#5794f2]">{t("Added", "Mới")}</span>}</td><td className="px-3 py-2 text-right font-mono text-[#a7a9ab]">{formatHighlightDelta(highlight, t)}</td></tr>)}
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

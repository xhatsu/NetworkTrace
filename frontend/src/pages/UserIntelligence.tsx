import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Activity, AlertOctagon, AlertTriangle, ArrowLeft, ArrowRight, BarChart3,
  Check, CheckCircle2, ChevronRight, Clock3, Cpu, Database, ExternalLink,
  Filter, Flame, GitCompareArrows, KeyRound, Layers, Network, Radio,
  RefreshCw, Search, Server, Shield, ShieldAlert, ShieldQuestion,
  SlidersHorizontal, Sparkles, TrendingDown, TrendingUp, Users, Workflow, X, Zap,
} from "lucide-react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, chartTooltip, n } from "../components";
import { useFilters } from "../App";

export type UserChange = {
  id: number; principal_name: string; change_type: string; severity: string; score: number;
  detected_at: number; caller_service?: string; source_ip?: string; target_service?: string;
  operation?: string; old_value?: string; new_value?: string; first_observed: number;
  status: "new" | "reviewed" | "expected" | "ignored";
  incident_id?: string; principal_id?: string; base_importance?: string; category?: string;
  family?: string; reliability?: string;
  reason?: {
    summary?: string;
    evidence?: Record<string, unknown>;
    framing?: string;
    what_changed?: string;
    compared_with?: string;
    where?: Record<string, string>;
    how_reliable?: Record<string, string>;
    why_priority?: Record<string, string | number>;
    what_proves_it?: { first_observed?: number; last_observed?: number; representative_traces?: string[] };
    what_happened_afterward?: string;
  };
};

export type IncidentItem = {
  incident_id: string;
  principal_id: string;
  environment: string;
  category: string;
  scope: string;
  started_at: number;
  last_seen_at: number;
  closed_at?: number;
  status: "open" | "investigating" | "resolved" | "suppressed" | "accepted";
  score: number;
  priority: "low" | "medium" | "high";
  confidence: number;
  family_scores: Record<string, number>;
  contributing_event_ids: number[];
  suppressed_contributions: Array<{ event_id: number; change_type: string; reason: string }>;
  successor_id?: string;
};
type UserItem = {
  principal_name: string; principal_type: string; status: string; first_seen: number; last_seen: number;
  total_requests: number; unique_callers: number; unique_sources: number; unique_targets: number;
  unique_operations: number; recent_changes: number; behavior_score: number; behavior_level: string;
  learning_status?: "learning" | "established"; reference_time_ms?: number; status_basis?: string;
};
type Distribution = { value: string; requests: number; share: number; first_seen: number; last_seen: number };
type Profile = UserItem & {
  current: Record<"callers" | "sources" | "targets" | "operations", Distribution[]>;
  normal: Record<"callers" | "sources" | "targets" | "operations", Distribution[]>;
  changes: UserChange[]; hourly_activity: Array<{ day_of_week: number; hour_of_day: number; observation_count: number }>;
  daily_stats: Array<{ day_start: number; observation_count: number }>;
  typical_active_window: string;
};
const formatDate = (value?: number) => value ? new Date(value).toLocaleString() : "Not observed";
const tone = (severity: string) => severity === "high" || severity === "critical" ? "text-rose-300 border-rose-500/40 bg-rose-500/15" : severity === "medium" ? "text-amber-300 border-amber-500/40 bg-amber-500/15" : "text-emerald-300 border-emerald-500/40 bg-emerald-500/15";
const label = (value: string) => value.replaceAll("_", " ");

export function UsersPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("most_active");
  const [active, setActive] = useState("");
  const [level, setLevel] = useState("");
  const params = new URLSearchParams({ ...Object.fromEntries(Object.entries(filters).filter(([,v]) => v)) as Record<string,string>, limit:"500", sort });
  if (search) params.set("q", search); if (active) params.set("active", active); if (level) params.set("behavior_level", level);
  const users = useQuery({ queryKey:["users",params.toString()], queryFn:()=>api<{items:UserItem[];count:number}>(`/api/v1/users?${params}`), refetchInterval:60000 });
  const summary = useQuery({ queryKey:["users-summary",queryString(filters)], queryFn:()=>api<Record<string,number>>(`/api/v1/users/summary?${queryString(filters)}`) });
  return <Page eyebrow="User Intelligence" title="Observed Principals" description="TraceScope monitors observed application principals extracted from WSSE across callers, source addresses, target services, and operations. Authentication success is recorded when explicit evidence is available. Behavioral Change Events describe deviations from established observations; they do not independently establish credential compromise.">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-7">
      {[["Observed",summary.data?.observed_principals,"all known principals","cyan"],["Active",summary.data?.active_principals,"latest 15 minutes","emerald"],["New today",summary.data?.new_principals_today,"first observed","sky"],["With changes",summary.data?.principals_with_changes,"selected window","amber"],["Reactivated",summary.data?.dormant_reactivated,"after dormancy","rose"],["New targets",summary.data?.new_service_relationships,"relationship changes","violet"],["New callers",summary.data?.new_caller_relationships,"credential origins","indigo"]].map(([k,v,d,a])=><MetricCard key={String(k)} label={String(k)} value={n(Number(v||0),0)} detail={String(d)} accent={a as any}/>)}
    </div>
    <div className="card my-4 flex flex-wrap gap-2 p-3">
      <div className="flex min-w-64 flex-1 items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-3"><Search size={14} className="text-cyan-400"/><input className="w-full bg-transparent py-2 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:placeholder:text-cyan-300/50" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search principal, IP, caller, target, operation…"/></div>
      <select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={sort} onChange={e=>setSort(e.target.value)}>{[["most_active","Most active"],["most_changed","Most changed"],["most_target_services","Most targets"],["most_operations","Most operations"],["newest","Newest"],["dormant_returned","Dormant returned"]].map(([v,t])=><option className="bg-[#1a172a]" value={v} key={v}>{t}</option>)}</select>
      <select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={active} onChange={e=>setActive(e.target.value)}><option value="" className="bg-[#1a172a]">Any activity</option><option value="active" className="bg-[#1a172a]">Active</option><option value="inactive" className="bg-[#1a172a]">Inactive</option></select>
      <select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={level} onChange={e=>setLevel(e.target.value)}><option value="" className="bg-[#1a172a]">Any behavior level</option>{["low","medium","high"].map(x=><option className="bg-[#1a172a]" value={x} key={x}>{x}</option>)}</select>
    </div>
    {users.isLoading?<Loading/>:users.error?<ErrorState message={users.error.message}/>:<Panel title={`${users.data?.count||0} principals`} subtitle="Status and recency are evaluated at the selected dataset window end"><div className="overflow-auto scrollbar"><table className="w-full min-w-[1100px] text-left text-xs"><thead><tr>{["Principal","Status","Last seen","Callers","Source IPs","Targets","Operations","Requests","Changes","Behavior"].map(h=><th className="table-head px-4 py-3" key={h}>{h}</th>)}</tr></thead><tbody>{users.data?.items.map(u=><tr key={u.principal_name} onClick={()=>nav(`/users/${encodeURIComponent(u.principal_name)}?${queryString(filters)}`)} className="cursor-pointer border-t border-[rgba(255,255,255,0.08)] hover:bg-white/[0.05]"><td className="px-4 py-3 font-mono text-cyan-300"><span className="inline-flex items-center gap-2"><KeyRound size={13}/>{u.principal_name}</span><div className="mt-1 text-[10px] text-[#9e96b8]">{u.principal_type} · {u.learning_status||"learning"}</div></td><td className="px-4"><span className={u.status==="Active"?"text-emerald-300 font-medium":"text-[#c4bdd9]"}>{u.status}</span></td><td className="px-4 text-[#c4bdd9]">{formatDate(u.last_seen)}</td>{[u.unique_callers,u.unique_sources,u.unique_targets,u.unique_operations,u.total_requests,u.recent_changes].map((v,i)=><td className="px-4 font-mono text-[#f5f3fa]" key={i}>{n(v,0)}</td>)}<td className="px-4"><span className={`rounded border px-2 py-1 font-medium ${tone(u.behavior_level.toLowerCase())}`}>{u.behavior_level} · {u.behavior_score}</span></td></tr>)}</tbody></table></div></Panel>}
  </Page>;
}

function DistributionPanel({title,current,normal,accent="cyan"}:{title:string;current:Distribution[];normal:Distribution[];accent?:string}) {
  const normalBy = new Map(normal.map(x=>[x.value,x.share]));
  const learning=!normal.length;
  const barColors: Record<string, string> = {
    cyan: "bg-gradient-to-r from-cyan-500 to-blue-500",
    emerald: "bg-gradient-to-r from-emerald-500 to-teal-500",
    violet: "bg-gradient-to-r from-violet-500 to-purple-500",
    amber: "bg-gradient-to-r from-amber-500 to-orange-500",
  };
  const barClass = barColors[accent] || barColors.cyan;
  return <Panel title={title} subtitle={learning?"Historical baseline is still learning; current activity is shown without drift claims":"Current distribution compared with historical baseline"}><div className="divide-y divide-[rgba(255,255,255,0.08)] p-3">{current.slice(0,8).map(item=>{const baseline=normalBy.get(item.value)||0; const delta=item.share-baseline; return <div key={item.value} className="py-2"><div className="flex justify-between gap-3 text-xs"><span className="truncate font-mono text-[#f5f3fa]">{item.value}</span><span className={!learning&&Math.abs(delta)>.15?"font-mono text-amber-300 font-medium":"font-mono text-[#c4bdd9]"}>{(item.share*100).toFixed(1)}% <small>{learning?"(learning)":`(${delta>=0?"+":""}${(delta*100).toFixed(1)}pp)`}</small></span></div><div className="mt-1.5 h-1.5 rounded bg-white/[0.08]"><div className={`h-full rounded ${barClass}`} style={{width:`${Math.max(1,item.share*100)}%`}}/></div></div>})}{!current.length&&<div className="p-4 text-xs text-[#c4bdd9]">No activity in this period.</div>}</div></Panel>;
}

export function UserDetailPage() {
  const { principal="" }=useParams(); const {filters}=useFilters(); const nav=useNavigate(); const qs=queryString(filters);
  const q=useQuery({queryKey:["user",principal,qs],queryFn:()=>api<Profile>(`/api/v1/users/${encodeURIComponent(principal)}?${qs}`)});
  const [timelineKind,setTimelineKind]=useState("all");
  const timeline=useQuery({queryKey:["user-timeline",principal,qs,timelineKind],queryFn:()=>api<{items:any[]}>(`/api/v1/users/${encodeURIComponent(principal)}/timeline?${qs}&kind=${timelineKind}&limit=80`)});
  if(q.isLoading)return <Page eyebrow="User Intelligence" title={principal} description=""><Loading/></Page>;
  if(q.error||!q.data)return <Page eyebrow="User Intelligence" title={principal} description=""><ErrorState message={q.error?.message||"Principal not found"}/></Page>;
  const p=q.data;
  return <Page eyebrow="Principal Investigation" title={principal} description="Credential origin, expected behavior, current activity, and explainable changes." actions={<div className="flex flex-wrap gap-2"><button className="btn" onClick={()=>nav(-1)}><ArrowLeft size={13}/>Back</button><button className="btn" onClick={()=>nav(`/user-graph?principal=${encodeURIComponent(principal)}`)}><Network size={13}/>View graph</button><button className="btn" onClick={()=>nav(`/traces?principal=${encodeURIComponent(principal)}&${qs}`)}><ExternalLink size={13}/>View traces</button><button className="btn" onClick={()=>nav(`/anomalies?principal=${encodeURIComponent(principal)}`)}>Related anomalies</button></div>}>
    <div className="card mb-4 flex flex-wrap items-center justify-between gap-4 p-4"><div><div className="flex items-center gap-2"><span className={p.status==="Active"?"text-emerald-300 font-medium":"text-[#c4bdd9]"}>● {p.status} at window end</span><span className="chip">{p.principal_type}</span><span className="chip">Baseline: {p.learning_status||"learning"}</span></div><div className="mt-2 text-xs text-[#9e96b8]">First seen {formatDate(p.first_seen)} · Last seen {formatDate(p.last_seen)}</div></div><div className={`rounded-lg border px-4 py-2 ${tone(p.behavior_level.toLowerCase())}`}><div className="text-[10px] uppercase tracking-wider">Behavior change by distinct evidence type</div><div className="font-mono text-xl font-semibold">{p.behavior_score} / 100 · {p.behavior_level}</div></div></div>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">{[["Requests",p.total_requests,"observed","sky"],["Callers",p.unique_callers,"credential origins","cyan"],["Source IPs",p.unique_sources,"network origins","emerald"],["Targets",p.unique_targets,"services used","violet"],["Operations",p.unique_operations,"APIs invoked","indigo"],["Changes",p.changes.length,"selected period","amber"]].map(([k,v,d,a])=><MetricCard key={String(k)} label={String(k)} value={n(Number(v),0)} detail={String(d)} accent={a as any}/>)}</div>
    <div className="my-4 grid gap-4 lg:grid-cols-2"><DistributionPanel title="Caller Services" current={p.current.callers||[]} normal={p.normal.callers||[]} accent="cyan"/><DistributionPanel title="Source IPs" current={p.current.sources||[]} normal={p.normal.sources||[]} accent="emerald"/><DistributionPanel title="Target Services" current={p.current.targets||[]} normal={p.normal.targets||[]} accent="violet"/><DistributionPanel title="Operations" current={p.current.operations||[]} normal={p.normal.operations||[]} accent="amber"/></div>
    <Panel title="Normal Activity Pattern" subtitle={`Typical active window: ${p.typical_active_window}`}><div className="grid gap-1 p-4" style={{gridTemplateColumns:"repeat(24,minmax(0,1fr))"}}>{Array.from({length:168},(_,i)=>{const day=Math.floor(i/24),hour=i%24,value=p.hourly_activity.find(x=>x.day_of_week===day&&x.hour_of_day===hour)?.observation_count||0;const max=Math.max(1,...p.hourly_activity.map(x=>x.observation_count));return <div key={i} title={`Day ${day}, ${hour}:00 · ${value} requests`} className="h-5 rounded-sm" style={{backgroundColor:`rgba(139,92,246,${.1+.9*value/max})`}}/>})}</div><div className="px-4 pb-3 text-[10px] text-[#9e96b8]">7 rows × 24 hours · intensity represents historical request volume</div></Panel>
    <Panel title="What Changed?" subtitle="Evidence is shown alongside the score; changes are not automatically security incidents." className="mt-4"><div className="grid gap-2 p-4 md:grid-cols-2">{p.changes.slice(0,12).map(c=><ChangeCard key={c.id} change={c} onOpen={()=>nav(`/user-changes?principal=${encodeURIComponent(principal)}`)}/>)}{!p.changes.length&&<div className="p-4 text-xs text-[#c4bdd9]">No unexplained changes in this period.</div>}</div></Panel>
    <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_.8fr]"><Panel title="Behavior Timeline" subtitle="Trace activity and relationship changes in chronological order" action={<select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={timelineKind} onChange={e=>setTimelineKind(e.target.value)}>{["all","new_relationships","operations","errors"].map(x=><option className="bg-[#1a172a]" key={x}>{x}</option>)}</select>}><div className="max-h-[520px] divide-y divide-[rgba(255,255,255,0.08)] overflow-auto">{timeline.data?.items.map((item,i)=><div className="flex gap-3 p-3 text-xs" key={`${item.timestamp_ms}-${i}`}><Clock3 size={13} className="mt-0.5 shrink-0 text-violet-400"/><div><div className="font-mono text-[10px] text-[#9e96b8]">{formatDate(item.timestamp_ms)}</div><div className="mt-1 text-[#f5f3fa]"><b>{label(item.event_type)}</b> · {item.caller_service||"unknown caller"} → <span className="text-violet-300 font-medium">{principal}</span> → {item.target_service||"unknown target"} → {item.operation||""}</div></div></div>)}</div></Panel><Panel title="Where Is This Credential Used?" subtitle="Caller and source evidence"><div className="p-4">{(p.current.callers||[]).map(c=><div key={c.value} className="mb-3 rounded-lg border border-[rgba(255,255,255,0.12)] bg-[#1a172a] p-3"><div className="flex items-center gap-2 text-xs font-semibold text-[#f5f3fa]"><Server size={13} className="text-violet-400"/>{c.value}</div><div className="mt-2 space-y-1 pl-5 font-mono text-[11px] text-[#c4bdd9]">{(p.current.sources||[]).slice(0,6).map(s=><div key={s.value}>├── {s.value}</div>)}</div></div>)}</div></Panel></div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2"><SimpleTable title="Services Used" rows={p.current.targets||[]} headers={["Service","First seen","Last seen","Requests"]}/><SimpleTable title="Operations" rows={p.current.operations||[]} headers={["Operation / Target","First seen","Last seen","Count"]}/></div>
  </Page>;
}

function SimpleTable({title,rows,headers}:{title:string;rows:Distribution[];headers:string[]}){return <Panel title={title}><div className="overflow-auto scrollbar"><table className="w-full text-xs"><thead><tr>{headers.map(h=><th className="table-head px-3 py-2" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map(r=><tr className="border-t border-[rgba(255,255,255,0.08)] hover:bg-white/[0.04]" key={r.value}><td className="px-3 py-2 font-mono text-violet-300">{r.value}</td><td className="px-3 text-[#c4bdd9]">{formatDate(r.first_seen)}</td><td className="px-3 text-[#c4bdd9]">{formatDate(r.last_seen)}</td><td className="px-3 font-mono text-[#f5f3fa]">{n(r.requests,0)}</td></tr>)}</tbody></table></div></Panel>}
function ChangeCard({change,onOpen}:{change:UserChange;onOpen?:()=>void}){return <button onClick={onOpen} className="rounded-lg border border-[rgba(255,255,255,0.12)] bg-white/[0.04] p-3 text-left hover:border-violet-500/50 hover:bg-white/[0.07] transition"><div className="flex items-center justify-between"><span className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase ${tone(change.severity)}`}>{label(change.change_type)}</span><span className="font-mono text-[10px] text-[#c4bdd9]">+{change.score}</span></div><div className="mt-2 font-mono text-xs text-violet-300 font-medium">{change.principal_name}</div><p className="mt-1 text-xs text-[#f5f3fa]">{change.reason?.summary||`${change.old_value||"historical behavior"} → ${change.new_value||"new observation"}`}</p><div className="mt-2 text-[10px] text-[#9e96b8]">{formatDate(change.detected_at)} · {change.status}</div></button>}

export function UserChangesPage() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const qc = useQueryClient();
  const params = new URLSearchParams(location.search);
  const [principal, setPrincipal] = useState(params.get("principal") || "");
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [scope, setScope] = useState<"all" | "window">("all");
  const [viewMode, setViewMode] = useState<"graphs" | "list">("graphs");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"changes" | "incidents">("changes");
  const [reviewTarget, setReviewTarget] = useState<UserChange | null>(null);
  const [reviewScope, setReviewScope] = useState("change_rule");
  const [reviewReason, setReviewReason] = useState("");
  const [reviewExpiry, setReviewExpiry] = useState("never");

  const qs = scope === "window"
    ? queryString(filters, { principal: principal || undefined, change_type: type || undefined, severity: severity || undefined })
    : queryString({ timezone: filters.timezone, comparison: filters.comparison } as any, { principal: principal || undefined, change_type: type || undefined, severity: severity || undefined });

  const q = useQuery({
    queryKey: ["user-changes", qs, scope],
    queryFn: () => api<{ items: UserChange[]; count: number; total_unfiltered?: number; fallback_applied?: boolean }>(`/api/v1/user-changes?${qs}&limit=500`),
    refetchInterval: 30_000,
  });

  const incidentsQuery = useQuery({
    queryKey: ["incidents", qs],
    queryFn: () => api<{ items: IncidentItem[]; count: number }>(`/api/v1/incidents?${qs}&limit=100`),
    enabled: activeTab === "incidents",
    refetchInterval: 30_000,
  });

  async function submitReview(changeId: number, action: "expected" | "investigate" | "data_quality", reasonText?: string) {
    const expiresAt = reviewExpiry === "7d" ? Date.now() + 7 * 86400000 : reviewExpiry === "30d" ? Date.now() + 30 * 86400000 : undefined;
    await api(`/api/v1/user-changes/${changeId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        scope: reviewScope,
        reason: reasonText || reviewReason || `Operator review: ${action}`,
        operator: "operator",
        expires_at: expiresAt,
      }),
    });
    setReviewTarget(null);
    setReviewReason("");
    qc.invalidateQueries({ queryKey: ["user-changes"] });
    qc.invalidateQueries({ queryKey: ["incidents"] });
  }

  const items = q.data?.items ?? [];
  const highCritCount = items.filter((c) => c.severity === "high" || c.severity === "critical").length;
  const uniqueUsers = new Set(items.map((c) => c.principal_name)).size;
  const avgScore = items.length ? Math.round(items.reduce((s, c) => s + (c.score || 0), 0) / items.length) : 0;
  const maxScore = items.length ? Math.max(...items.map((c) => c.score || 0)) : 0;

  // Compute time-series buckets for the Global Anomaly Graph (Fleet Style)
  const chartPoints = useMemo(() => {
    if (!items.length) return [];
    const sorted = [...items].sort((a, b) => a.detected_at - b.detected_at);
    const minTs = sorted[0].detected_at;
    const maxTs = sorted[sorted.length - 1].detected_at;
    const span = Math.max(60_000, maxTs - minTs);
    const bucketCount = Math.min(24, Math.max(8, Math.ceil(span / (3600 * 1000))));
    const bucketWidth = span / bucketCount;

    const buckets = Array.from({ length: bucketCount }, (_, i) => {
      const bTs = minTs + i * bucketWidth;
      const d = new Date(bTs);
      const timeLabel = `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
      return {
        time: timeLabel,
        timestamp: bTs,
        eventCount: 0,
        totalScore: 0,
        criticalHigh: 0,
        medium: 0,
        low: 0,
        newCaller: 0,
        newTarget: 0,
        newSource: 0,
        dormant: 0,
        newOp: 0,
        firstSeen: 0,
      };
    });

    for (const item of sorted) {
      const idx = Math.min(bucketCount - 1, Math.max(0, Math.floor((item.detected_at - minTs) / bucketWidth)));
      const b = buckets[idx];
      b.eventCount += 1;
      b.totalScore += (item.score || 0);
      const sev = (item.severity || "").toLowerCase();
      if (sev === "critical" || sev === "high") b.criticalHigh += 1;
      else if (sev === "medium") b.medium += 1;
      else b.low += 1;

      const ct = item.change_type;
      if (ct === "NEW_CALLER") b.newCaller += 1;
      else if (ct === "NEW_TARGET") b.newTarget += 1;
      else if (ct === "NEW_SOURCE_IP") b.newSource += 1;
      else if (ct === "DORMANT_REACTIVATED") b.dormant += 1;
      else if (ct === "NEW_OPERATION") b.newOp += 1;
      else if (ct === "USERNAME_FIRST_SEEN") b.firstSeen += 1;
    }
    return buckets;
  }, [items]);

  // Ranked identities by behavioral anomaly volume & score
  const topFlaggedPrincipals = useMemo(() => {
    const counts: Record<string, { count: number; score: number; types: Set<string>; severity: string }> = {};
    for (const item of items) {
      const p = item.principal_name;
      if (!counts[p]) counts[p] = { count: 0, score: 0, types: new Set(), severity: "low" };
      counts[p].count += 1;
      counts[p].score += (item.score || 0);
      counts[p].types.add(item.change_type);
      if (item.severity === "critical" || item.severity === "high") {
        counts[p].severity = item.severity;
      } else if (item.severity === "medium" && counts[p].severity !== "critical" && counts[p].severity !== "high") {
        counts[p].severity = "medium";
      }
    }
    return Object.entries(counts)
      .map(([name, data]) => ({
        name,
        count: data.count,
        score: data.score,
        types: Array.from(data.types),
        severity: data.severity,
      }))
      .sort((a, b) => b.score - a.score || b.count - a.count)
      .slice(0, 6);
  }, [items]);

  return (
    <Page
      eyebrow="User Intelligence"
      title="User Behavioral Anomalies"
      description="Live identity-centric deviation metrics, multi-tiered drift timelines, explainability cards, and bounded credential risk."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {/* View mode switcher */}
          <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.12)] bg-white/[0.03] p-0.5">
            <button
              onClick={() => setViewMode("graphs")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition ${
                viewMode === "graphs"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm font-semibold"
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              <BarChart3 size={13} />
              <span>Global Graphs</span>
            </button>
            <button
              onClick={() => setViewMode("list")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition ${
                viewMode === "list"
                  ? "bg-violet-600 text-white shadow-sm font-semibold"
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              <Layers size={13} />
              <span>Findings List</span>
            </button>
          </div>

          <button
            onClick={() => {
              q.refetch();
              if (activeTab === "incidents") incidentsQuery.refetch();
            }}
            disabled={q.isFetching}
            className="btn"
            title="Refresh Behavioral Anomalies"
          >
            <RefreshCw size={13} className={q.isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      }
    >
      {/* Graceful empty window fallback banner */}
      {q.data?.fallback_applied && (
        <div className="card mb-4 flex items-center justify-between border-amber-500/40 bg-amber-500/15 p-3 text-xs text-amber-200">
          <span>Notice: No changes detected in the selected time window. Showing all {q.data.total_unfiltered || q.data.count} historical changes across the estate.</span>
          <button onClick={() => setScope("all")} className="btn border-amber-500/50 text-amber-200">View All Time</button>
        </div>
      )}

      {/* Review Modal for Expected Change */}
      {reviewTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
          <div className="card w-full max-w-md border-cyan-500/30 bg-[#161424] p-5 text-xs shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <b className="text-sm text-cyan-300">Mark Behavior as Expected</b>
              <button onClick={() => setReviewTarget(null)} className="text-[#9e96b8] hover:text-white"><X size={16} /></button>
            </div>
            <div className="mt-3 space-y-3">
              <div>
                <label className="text-[11px] text-[#9e96b8]">Principal & Change</label>
                <div className="font-mono text-white font-medium">{reviewTarget.principal_name} · {label(reviewTarget.change_type)}</div>
              </div>
              <div>
                <label className="text-[11px] text-[#9e96b8]">Scope</label>
                <select className="btn w-full mt-1 bg-white/[0.04] border-white/15 text-white" value={reviewScope} onChange={e => setReviewScope(e.target.value)}>
                  <option value="change_rule" className="bg-[#161424]">This specific entity & principal ({reviewTarget.new_value || reviewTarget.target_service || "rule"})</option>
                  <option value="target_service" className="bg-[#161424]">All operations on {reviewTarget.target_service || "target service"}</option>
                  <option value="principal" className="bg-[#161424]">Entire principal identity ({reviewTarget.principal_name})</option>
                </select>
              </div>
              <div>
                <label className="text-[11px] text-[#9e96b8]">Reason / Authorization context</label>
                <textarea
                  className="w-full mt-1 rounded-lg border border-white/15 bg-white/[0.04] p-2 text-white placeholder:text-[#9e96b8] outline-none focus:border-cyan-400"
                  rows={3}
                  placeholder="e.g. Approved maintenance deployment, verified with service owner"
                  value={reviewReason}
                  onChange={e => setReviewReason(e.target.value)}
                />
              </div>
              <div>
                <label className="text-[11px] text-[#9e96b8]">Expiry</label>
                <select className="btn w-full mt-1 bg-white/[0.04] border-white/15 text-white" value={reviewExpiry} onChange={e => setReviewExpiry(e.target.value)}>
                  <option value="never" className="bg-[#161424]">Permanent (no expiry)</option>
                  <option value="7d" className="bg-[#161424]">Expires in 7 days</option>
                  <option value="30d" className="bg-[#161424]">Expires in 30 days</option>
                </select>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2 border-t border-white/10 pt-3">
              <button onClick={() => setReviewTarget(null)} className="btn text-[#c4bdd9]">Cancel</button>
              <button onClick={() => submitReview(reviewTarget.id, "expected")} className="btn bg-cyan-600 hover:bg-cyan-500 text-white font-medium border-cyan-400">Accept Expected Change</button>
            </div>
          </div>
        </div>
      )}

      {/* KPI Summary Cards (Fleet Style) */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <MetricCard
          label="Total Anomalies"
          value={String(items.length)}
          detail={`${q.data?.total_unfiltered ?? items.length} recorded across estate`}
          accent="cyan"
        />
        <MetricCard
          label="High / Critical Threats"
          value={String(highCritCount)}
          detail="Urgent operational alerts"
          tone={highCritCount > 0 ? "bad" : "normal"}
          accent="purple"
        />
        <MetricCard
          label="Impacted Identities"
          value={String(uniqueUsers)}
          detail="Unique accounts exhibiting drift"
          accent="indigo"
        />
        <MetricCard
          label="Mean Anomaly Score"
          value={`${avgScore} pts`}
          detail={`Peak observed score: ${maxScore} pts`}
          accent="amber"
        />
        <MetricCard
          label="Active Incidents"
          value={String(incidentsQuery.data?.count ?? 0)}
          detail="Bounded 15m correlation clusters"
          accent="cyan"
        />
      </div>

      {/* Header Filters and Tab Bar */}
      <div className="card mb-4 flex flex-wrap items-center justify-between gap-3 p-3">
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] p-0.5">
            <button
              onClick={() => setActiveTab("changes")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === "changes"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              Behavioral Changes ({q.data?.count || 0})
            </button>
            <button
              onClick={() => setActiveTab("incidents")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                activeTab === "incidents"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm"
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              Bounded Incidents ({incidentsQuery.data?.count ?? 0})
            </button>
          </div>
          <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] p-0.5">
            <button
              onClick={() => setScope("all")}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                scope === "all" ? "bg-violet-600 text-white shadow-sm" : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              All Time ({q.data?.total_unfiltered ?? q.data?.count ?? 0})
            </button>
            <button
              onClick={() => setScope("window")}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                scope === "window" ? "bg-violet-600 text-white shadow-sm" : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              Selected Window
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8b949e]" />
            <input
              className="min-w-44 rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] pl-7 pr-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:border-cyan-400"
              placeholder="Filter by principal..."
              value={principal}
              onChange={(e) => setPrincipal(e.target.value)}
            />
          </div>
          <select
            className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]"
            value={type}
            onChange={(e) => setType(e.target.value)}
          >
            <option value="" className="bg-[#1a172a]">All change types</option>
            {["NEW_CALLER", "NEW_TARGET", "NEW_SOURCE_IP", "NEW_OPERATION", "DORMANT_REACTIVATED", "USERNAME_FIRST_SEEN", "CREDENTIAL_ABUSE"].map((t) => (
              <option className="bg-[#1a172a]" key={t} value={t}>{label(t)}</option>
            ))}
          </select>
          <select
            className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            <option value="" className="bg-[#1a172a]">All severities</option>
            {["critical", "high", "medium", "low"].map((s) => (
              <option className="bg-[#1a172a]" key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Content Area */}
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : activeTab === "incidents" ? (
        /* Tab 2: Bounded Incidents */
        incidentsQuery.isLoading ? <Loading /> : incidentsQuery.error ? <ErrorState message={incidentsQuery.error.message} /> : (
          <Panel
            title={`${incidentsQuery.data?.count || 0} bounded security incidents`}
            subtitle="Incidents merge related changes within 15m windows, close after 30m idle, and cap scores across distinct families"
          >
            <div className="divide-y divide-[rgba(255,255,255,0.08)]">
              {incidentsQuery.data?.items.map((inc) => (
                <div className="p-4 transition hover:bg-white/[0.02]" key={inc.incident_id}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`rounded border px-2 py-0.5 text-xs font-bold ${
                        inc.priority === "high"
                          ? "text-rose-300 border-rose-500/40 bg-rose-500/15"
                          : inc.priority === "medium"
                            ? "text-amber-300 border-amber-500/40 bg-amber-500/15"
                            : "text-emerald-300 border-emerald-500/40 bg-emerald-500/15"
                      }`}>
                        {inc.priority.toUpperCase()} PRIORITY ({inc.score} / 100)
                      </span>
                      <span className="font-mono text-cyan-300 font-semibold">{inc.principal_id.split(":").slice(-1)[0]}</span>
                      <span className="chip text-[10px]">{inc.category}</span>
                      <span className="chip text-[10px]">{inc.status}</span>
                    </div>
                    <div className="font-mono text-[10px] text-[#9e96b8]">
                      Started: {new Date(inc.started_at).toLocaleTimeString()} · Last seen: {new Date(inc.last_seen_at).toLocaleTimeString()}
                    </div>
                  </div>
                  <div className="mt-2 text-xs text-[#c4bdd9]">
                    Scope: <b className="text-white">{inc.scope}</b> · Events: <b className="text-white">{inc.contributing_event_ids?.length || 0}</b>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {Object.entries(inc.family_scores || {}).map(([fam, pts]) => (
                      <span className="rounded bg-white/[0.05] px-2 py-0.5 font-mono text-[#c4bdd9]" key={fam}>
                        {fam}: <b className="text-cyan-300">{pts} pts</b>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {(!incidentsQuery.data?.items || incidentsQuery.data.items.length === 0) && (
                <div className="p-6 text-center text-xs text-[#c4bdd9]">
                  No open incidents found for selected criteria.
                </div>
              )}
            </div>
          </Panel>
        )
      ) : viewMode === "graphs" ? (
        /* Global Graphs Dashboard (Fleet Style) */
        <div className="space-y-6">
          {/* 1. Global Anomaly Velocity & Cumulative Risk Score Over Time */}
          <Panel
            title="Global Anomaly Velocity & Cumulative Risk Score Over Time"
            subtitle="Real-time detection frequency (events/window) and aggregate threat impact (pts) across observed timeline"
          >
            {chartPoints.length === 0 ? (
              <div className="h-64 flex items-center justify-center text-xs text-[#6e7681]">
                No anomaly events observed in the active window.
              </div>
            ) : (
              <div className="h-72 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartPoints}>
                    <defs>
                      <linearGradient id="colorUserAnomVelocity" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorUserAnomScore" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#818cf8" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#818cf8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="left" stroke="#10b981" tick={{ fontSize: 10 }} unit=" ev" />
                    <YAxis yAxisId="right" orientation="right" stroke="#818cf8" tick={{ fontSize: 10 }} unit=" pts" />
                    <Tooltip
                      {...chartTooltip}
                      formatter={(v: any, name: any) => [
                        name === "Anomaly Velocity" ? `${n(v, 0)} events` : `${n(v, 0)} pts`,
                        name,
                      ]}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
                    <Area
                      yAxisId="left"
                      type="monotone"
                      dataKey="eventCount"
                      name="Anomaly Velocity"
                      stroke="#10b981"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorUserAnomVelocity)"
                    />
                    <Area
                      yAxisId="right"
                      type="monotone"
                      dataKey="totalScore"
                      name="Cumulative Risk Score"
                      stroke="#818cf8"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorUserAnomScore)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          {/* 2 & 3: Severity Distribution & Behavioral Drift Categories Timeline */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Severity Distribution Timeline */}
            <Panel
              title="Anomaly Severity & Threat Distribution Over Time"
              subtitle="Critical/High urgent threats vs Medium and Low behavioral changes"
            >
              {chartPoints.length === 0 ? (
                <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No data</div>
              ) : (
                <div className="h-64 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartPoints}>
                      <defs>
                        <linearGradient id="colorUserCrit" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.4} />
                          <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="colorUserMed" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.35} />
                          <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                      <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} />
                      <Tooltip {...chartTooltip} />
                      <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                      <Area
                        type="monotone"
                        dataKey="criticalHigh"
                        name="Critical / High"
                        stroke="#f43f5e"
                        strokeWidth={1.5}
                        fill="url(#colorUserCrit)"
                      />
                      <Area
                        type="monotone"
                        dataKey="medium"
                        name="Medium Severity"
                        stroke="#f59e0b"
                        strokeWidth={1.5}
                        fill="url(#colorUserMed)"
                      />
                      <Area
                        type="monotone"
                        dataKey="low"
                        name="Low Severity"
                        stroke="#10b981"
                        strokeWidth={1.5}
                        fillOpacity={0.1}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>

            {/* Behavioral Change Categories Timeline */}
            <Panel
              title="Behavioral Drift Categories Timeline"
              subtitle="Caller expansion, Target expansion, Foreign IP, and Dormancy reactivation"
            >
              {chartPoints.length === 0 ? (
                <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No data</div>
              ) : (
                <div className="h-64 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartPoints}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="time" stroke="#59616b" tick={{ fontSize: 10 }} />
                      <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} />
                      <Tooltip {...chartTooltip} />
                      <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                      <Line type="monotone" dataKey="newCaller" name="New Caller" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="newTarget" name="New Target" stroke="#06b6d4" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="newSource" name="New Source IP" stroke="#ec4899" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="dormant" name="Dormant Reactivated" stroke="#ef4444" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="newOp" name="New Operation" stroke="#f59e0b" strokeWidth={1.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>
          </div>

          {/* 4. Top Impacted Principals Ranking */}
          <Panel
            title="Top Flagged Identities by Anomaly Severity"
            subtitle="Identities accumulating the highest risk scores and most frequent behavioral deviations"
          >
            {topFlaggedPrincipals.length === 0 ? (
              <div className="p-6 text-center text-xs text-[#6e7681]">No flagged identities</div>
            ) : (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 p-4">
                {topFlaggedPrincipals.map((p, idx) => (
                  <div
                    key={p.name}
                    onClick={() => nav(`/users/${encodeURIComponent(p.name)}`)}
                    className="cursor-pointer rounded-xl border border-[rgba(255,255,255,0.08)] bg-white/[0.02] p-3.5 transition hover:border-cyan-500/40 hover:bg-white/[0.04] group"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 font-mono text-xs font-semibold text-cyan-300 group-hover:text-cyan-200">
                        <KeyRound size={13} className="text-cyan-400" />
                        <span>{p.name}</span>
                      </div>
                      <span className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase ${tone(p.severity)}`}>
                        +{p.score} pts
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[11px] text-[#9e96b8]">
                      <span>{p.count} anomalies detected</span>
                      <span className="font-mono text-white/80">Rank #{idx + 1}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {p.types.slice(0, 3).map((t) => (
                        <span key={t} className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[9px] font-mono text-[#c4bdd9]">
                          {label(t)}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {/* 5. Interactive Detailed Inspector Table with 7-Questions Explainability */}
          <Panel
            title={`${items.length} Behavioral Findings & Anomaly Inspector`}
            subtitle="Click any row to inspect the full 7-Question Explainability card, trace evidence, and operator review actions"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[rgba(255,255,255,0.07)] text-[10px] uppercase tracking-wider text-[#59616b]">
                    {["Severity", "Principal", "Deviation Type", "Execution Path", "Score", "Detected At", "Status", "Actions"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-4 py-2.5 font-semibold">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[rgba(255,255,255,0.05)]">
                  {items.slice(0, 50).map((c) => {
                    const isExpanded = expandedId === c.id;
                    const r = c.reason || {};
                    return (
                      <tr
                        key={c.id}
                        onClick={() => setExpandedId(isExpanded ? null : c.id)}
                        className="cursor-pointer transition hover:bg-white/[0.03] group"
                      >
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded border px-2 py-0.5 text-[10px] font-semibold uppercase ${tone(c.severity)}`}>
                            {c.severity}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-cyan-300 font-medium">
                          {c.principal_name}
                        </td>
                        <td className="px-4 py-3 text-[#f5f3fa]">
                          <span className="rounded bg-white/[0.04] px-1.5 py-0.5 border border-white/[0.06] text-[11px]">
                            {label(c.change_type)}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-[11px] text-[#c4bdd9]">
                          {c.caller_service || "direct"} → <b className="text-violet-300 font-normal">{c.target_service || "any"}</b> {c.operation ? `(${c.operation})` : ""}
                        </td>
                        <td className="px-4 py-3 font-mono font-bold text-amber-300">
                          +{c.score}
                        </td>
                        <td className="px-4 py-3 text-[11px] text-[#8b949e]">
                          {new Date(c.detected_at).toLocaleTimeString()}
                        </td>
                        <td className="px-4 py-3">
                          <span className="chip text-[10px]">{c.status}</span>
                        </td>
                        <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              title="Accept as expected change"
                              className="btn text-[11px] py-1 border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/20"
                              onClick={() => setReviewTarget(c)}
                            >
                              Expected
                            </button>
                            <button
                              title="Mark for deep investigation"
                              className="btn text-[11px] py-1 border-amber-500/40 text-amber-300 hover:bg-amber-500/20"
                              onClick={() => submitReview(c.id, "investigate")}
                            >
                              Investigate
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Expandable 7-Questions Drawer Modal if an item is selected */}
            {expandedId !== null && (() => {
              const selectedChange = items.find((x) => x.id === expandedId);
              if (!selectedChange) return null;
              const r = selectedChange.reason || {};
              return (
                <div className="p-4 border-t border-[rgba(255,255,255,0.08)] bg-[#12101b]">
                  <div className="mb-3 flex items-center justify-between border-b border-white/10 pb-2">
                    <span className="font-semibold text-cyan-400">WHAT CHANGED COMPARED WITH NORMAL? (7-Question Explainability for #{selectedChange.id})</span>
                    <button className="btn text-xs text-[#9e96b8]" onClick={() => setExpandedId(null)}>Close</button>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 text-xs">
                    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                      <span className="text-[10px] uppercase font-bold text-cyan-300">1. What changed?</span>
                      <div className="mt-1 text-white font-medium">{r.what_changed || r.summary || selectedChange.new_value}</div>
                    </div>
                    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                      <span className="text-[10px] uppercase font-bold text-cyan-300">2. Compared with what?</span>
                      <div className="mt-1 text-[#c4bdd9]">{r.compared_with || `Entity not observed for the principal during historical baseline.`}</div>
                    </div>
                    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                      <span className="text-[10px] uppercase font-bold text-cyan-300">3. Where?</span>
                      <div className="mt-1 space-y-1 font-mono text-[11px] text-[#c4bdd9]">
                        <div>Principal: <b className="text-white">{selectedChange.principal_name}</b></div>
                        <div>Path: {selectedChange.caller_service || "direct"} → {selectedChange.target_service || "unknown"} ({selectedChange.operation || "any"})</div>
                        {selectedChange.source_ip && <div>Source Address: {selectedChange.source_ip}</div>}
                      </div>
                    </div>
                    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                      <span className="text-[10px] uppercase font-bold text-cyan-300">4. How reliable is it?</span>
                      <div className="mt-1 text-[#c4bdd9]">
                        Attribution: <b className="text-emerald-300">{r.how_reliable?.attribution_method || selectedChange.reliability || "trace_linked"}</b> · Quality: <b className="text-white">healthy</b>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}
          </Panel>
        </div>
      ) : (
        /* Findings List View (Classic Mode) */
        <Panel title={`${items.length} behavioral changes`} subtitle="Chronological anomaly event stream with explainability drawer">
          <div className="divide-y divide-[rgba(255,255,255,0.08)]">
            {items.map((c) => {
              const isExpanded = expandedId === c.id;
              const r = c.reason || {};
              return (
                <div
                  key={c.id}
                  className="p-4 transition hover:bg-white/[0.02] cursor-pointer"
                  onClick={() => setExpandedId(isExpanded ? null : c.id)}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`rounded border px-2 py-0.5 text-xs font-bold uppercase ${tone(c.severity)}`}>
                        {c.severity} · {label(c.change_type)}
                      </span>
                      <span className="font-mono text-cyan-300 font-semibold">{c.principal_name}</span>
                      <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-amber-300 font-bold">
                        +{c.score} pts
                      </span>
                      <span className="chip text-[10px]">{c.status}</span>
                    </div>
                    <div className="font-mono text-[10px] text-[#9e96b8]">
                      Detected: {new Date(c.detected_at).toLocaleString()}
                    </div>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                    <div className="text-[#c4bdd9]">
                      {r.summary || `${c.old_value || "historical behavior"} → ${c.new_value || "new observation"}`}
                    </div>
                    <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                      <button className="btn text-xs border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/20" onClick={() => setReviewTarget(c)}>Expected</button>
                      <button className="btn text-xs border-amber-500/40 text-amber-300 hover:bg-amber-500/20" onClick={() => submitReview(c.id, "investigate")}>Investigate</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      )}
    </Page>
  );
}

export type GraphData = {
  nodes: Array<{ id: string; label: string; type: string }>;
  edges: Array<{ source: string; target: string; requests: number; state: string; label: string }>;
  items?: Array<{ caller_service: string; principal_name: string; target_service: string; requests: number; changed: number; last_seen: number }>;
  summary?: { total_principals: number; total_callers: number; total_targets: number; total_requests: number; changed_edges: number };
  mode: string;
};

function UserGraphCanvas({ graph, onPrincipal }: { graph: GraphData; onPrincipal: (p: string) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const positions = useMemo(() => {
    const groups = {
      caller: graph.nodes.filter((n) => n.type === "caller"),
      principal: graph.nodes.filter((n) => n.type === "principal"),
      target: graph.nodes.filter((n) => n.type === "target"),
    };
    const map = new Map<string, { x: number; y: number }>();
    (["caller", "principal", "target"] as const).forEach((type, col) =>
      groups[type].forEach((node, i) =>
        map.set(node.id, { x: 130 + col * 350, y: 55 + i * Math.max(42, 520 / Math.max(1, groups[type].length)) })
      )
    );
    return map;
  }, [graph]);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const dpr = devicePixelRatio || 1;
    const r = c.getBoundingClientRect();
    c.width = r.width * dpr;
    c.height = r.height * dpr;
    const x = c.getContext("2d")!;
    x.scale(dpr, dpr);
    x.clearRect(0, 0, r.width, r.height);
    for (const e of graph.edges) {
      const a = positions.get(e.source);
      const b = positions.get(e.target);
      if (!a || !b) continue;
      x.beginPath();
      x.moveTo(a.x, a.y);
      x.lineTo(b.x, b.y);
      x.strokeStyle = e.state === "changed" ? "#f59e0b" : "#6366f1";
      x.lineWidth = Math.min(5, 1 + Math.sqrt(e.requests) / 10);
      if (e.state === "changed") x.setLineDash([7, 4]);
      x.stroke();
      x.setLineDash([]);
    }
    for (const node of graph.nodes) {
      const p = positions.get(node.id)!;
      x.beginPath();
      x.arc(p.x, p.y, 18, 0, Math.PI * 2);
      x.fillStyle = node.type === "principal" ? "#8b5cf6" : node.type === "caller" ? "#10b981" : "#0ea5e9";
      x.fill();
      x.strokeStyle = node.type === "principal" ? "#c4b5fd" : node.type === "caller" ? "#6ee7b7" : "#7dd3fc";
      x.lineWidth = 2;
      x.stroke();
      x.fillStyle = "#f5f3fa";
      x.font = "13px Inter";
      x.textAlign = "center";
      x.fillText(node.label.slice(0, 24), p.x, p.y + 34);
    }
  }, [graph, positions]);

  return (
    <canvas
      ref={ref}
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = e.clientX - r.left;
        const py = e.clientY - r.top;
        for (const node of graph.nodes.filter((n) => n.type === "principal")) {
          const p = positions.get(node.id)!;
          if (Math.hypot(px - p.x, py - p.y) < 24) onPrincipal(node.label);
        }
      }}
      className="h-[620px] w-full cursor-pointer"
    />
  );
}

export function UserGraphPage() {
  const nav = useNavigate();
  const { filters } = useFilters();
  const params = new URLSearchParams(location.search);
  const [mode, setMode] = useState(params.get("principal") ? "principal" : "estate");
  const [principal, setPrincipal] = useState(params.get("principal") || "");
  const [service, setService] = useState("");
  const [viewMode, setViewMode] = useState<"graphs" | "topology">("graphs");

  const qs = queryString(filters, {
    principal: mode === "principal" && principal ? principal : undefined,
    service: mode === "service" && service ? service : undefined,
  });

  const q = useQuery({
    queryKey: ["user-graph", qs],
    queryFn: () => api<GraphData>(`/api/v1/user-graph?${qs}`),
    refetchInterval: 30_000,
  });

  const nodes = q.data?.nodes || [];
  const edges = q.data?.edges || [];
  const totalPrincipals = nodes.filter((n) => n.type === "principal").length;
  const totalCallers = nodes.filter((n) => n.type === "caller").length;
  const totalTargets = nodes.filter((n) => n.type === "target").length;
  const totalRequests = edges.reduce((s, e) => s + (e.requests || 0), 0);
  const changedEdgesCount = edges.filter((e) => e.state === "changed").length;

  // Top Edge Flow Chart Points (Agent Fleet Style)
  const edgeChartPoints = useMemo(() => {
    const list = edges.slice().sort((a, b) => (b.requests || 0) - (a.requests || 0)).slice(0, 16);
    const total = totalRequests || 1;
    return list.map((e) => {
      const srcName = e.source.split(":")[1] || e.source;
      const tgtName = e.target.split(":")[1] || e.target;
      return {
        edge: `${srcName} → ${tgtName}`,
        shortEdge: `${srcName.slice(0, 12)}… → ${tgtName.slice(0, 12)}…`,
        source: srcName,
        target: tgtName,
        requests: e.requests || 0,
        sharePct: Number(((e.requests || 0) / total * 100).toFixed(1)),
        isChanged: e.state === "changed" ? 1 : 0,
        state: e.state,
      };
    });
  }, [edges, totalRequests]);

  // Identity Ingress vs Target Service Fan-Out Dynamics
  const principalFanout = useMemo(() => {
    const princs = nodes.filter((n) => n.type === "principal");
    const stats: Array<{ name: string; callersCount: number; targetsCount: number; reqVolume: number }> = [];
    for (const p of princs) {
      const pLabel = p.label;
      const callers = new Set(edges.filter((e) => e.target === `principal:${pLabel}`).map((e) => e.source));
      const targets = new Set(edges.filter((e) => e.source === `principal:${pLabel}`).map((e) => e.target));
      const reqs = edges.filter((e) => e.source === `principal:${pLabel}` || e.target === `principal:${pLabel}`).reduce((s, e) => s + e.requests, 0);
      stats.push({
        name: pLabel,
        callersCount: callers.size,
        targetsCount: targets.size,
        reqVolume: reqs,
      });
    }
    return stats.sort((a, b) => b.reqVolume - a.reqVolume).slice(0, 8);
  }, [nodes, edges]);

  // Normal vs Changed Volume Breakdown
  const edgeStateVolume = useMemo(() => {
    const normal = edges.filter((e) => e.state === "normal").reduce((s, e) => s + (e.requests || 0), 0);
    const changed = edges.filter((e) => e.state === "changed").reduce((s, e) => s + (e.requests || 0), 0);
    return [
      { name: "Normal Edges", value: normal, count: edges.filter((e) => e.state === "normal").length },
      { name: "Changed / Drifted Edges", value: changed, count: edges.filter((e) => e.state === "changed").length },
    ];
  }, [edges]);

  return (
    <Page
      eyebrow="User Intelligence"
      title="Caller → Principal → Target Dependency Graph"
      description="Detailed identity relationship telemetry, microservice call velocity, credential fan-in/fan-out, and architectural drift."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {/* View mode toggle */}
          <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.12)] bg-white/[0.03] p-0.5">
            <button
              onClick={() => setViewMode("graphs")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition ${
                viewMode === "graphs"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm font-semibold"
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              <BarChart3 size={13} />
              <span>Detailed Graphs</span>
            </button>
            <button
              onClick={() => setViewMode("topology")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition ${
                viewMode === "topology"
                  ? "bg-violet-600 text-white shadow-sm font-semibold"
                  : "text-[#c4bdd9] hover:text-white"
              }`}
            >
              <Network size={13} />
              <span>Classic Topology</span>
            </button>
          </div>

          <button
            onClick={() => q.refetch()}
            disabled={q.isFetching}
            className="btn"
            title="Refresh Graph Telemetry"
          >
            <RefreshCw size={13} className={q.isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      }
    >
      {/* KPI Summary Cards (Fleet Style) */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <MetricCard
          label="Tracked Principals"
          value={String(totalPrincipals)}
          detail="Observed identities in graph"
          accent="cyan"
        />
        <MetricCard
          label="Caller Services"
          value={String(totalCallers)}
          detail="Ingress microservice sources"
          accent="emerald"
        />
        <MetricCard
          label="Target Services"
          value={String(totalTargets)}
          detail="Destination backend APIs"
          accent="violet"
        />
        <MetricCard
          label="Total Invocations"
          value={n(totalRequests, 0)}
          detail="Graph request throughput"
          accent="indigo"
        />
        <MetricCard
          label="Drifted / Changed Edges"
          value={String(changedEdgesCount)}
          detail={`${((changedEdgesCount / Math.max(1, edges.length)) * 100).toFixed(0)}% of edges exhibit drift`}
          tone={changedEdgesCount > 0 ? "bad" : "normal"}
          accent="amber"
        />
      </div>

      {/* Mode Controls Bar */}
      <div className="card mb-4 flex flex-wrap items-center justify-between gap-2 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="estate" className="bg-[#1a172a]">Estate view</option>
            <option value="principal" className="bg-[#1a172a]">Principal centered</option>
            <option value="service" className="bg-[#1a172a]">Target service usage</option>
          </select>

          {mode === "principal" && (
            <input
              className="rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:border-cyan-400"
              value={principal}
              onChange={(e) => setPrincipal(e.target.value)}
              placeholder="Filter principal name..."
            />
          )}

          {mode === "service" && (
            <input
              className="rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:border-indigo-400"
              value={service}
              onChange={(e) => setService(e.target.value)}
              placeholder="Filter target service..."
            />
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="rounded bg-emerald-500/10 border border-emerald-500/25 px-2 py-0.5 text-[10px] font-mono text-emerald-400">
            Solid = Normal Edge
          </span>
          <span className="rounded bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 text-[10px] font-mono text-amber-400">
            Dashed = Changed / Drifted
          </span>
        </div>
      </div>

      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorState message={q.error.message} />
      ) : viewMode === "graphs" ? (
        /* Detailed Graph Dashboard (Agent Fleet Style) */
        <div className="space-y-6">
          {/* 1. Identity Dependency Invocations & Request Velocity Across Edges */}
          <Panel
            title="Identity Dependency Invocations & Relative Call Share Across Edges"
            subtitle="Request volume distribution and relative share (%) across caller → principal → target microservice paths"
          >
            {edgeChartPoints.length === 0 ? (
              <div className="h-64 flex items-center justify-center text-xs text-[#6e7681]">
                No graph relationship edges available.
              </div>
            ) : (
              <div className="h-72 p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={edgeChartPoints}>
                    <defs>
                      <linearGradient id="colorGraphReqs" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorGraphShare" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#818cf8" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#818cf8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="shortEdge" stroke="#59616b" tick={{ fontSize: 10 }} />
                    <YAxis yAxisId="left" stroke="#10b981" tick={{ fontSize: 10 }} unit=" reqs" />
                    <YAxis yAxisId="right" orientation="right" stroke="#818cf8" tick={{ fontSize: 10 }} unit="%" />
                    <Tooltip
                      {...chartTooltip}
                      formatter={(v: any, name: any) => [
                        name === "Request Invocations" ? `${n(v, 0)} requests` : `${Number(v).toFixed(1)}%`,
                        name,
                      ]}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
                    <Area
                      yAxisId="left"
                      type="monotone"
                      dataKey="requests"
                      name="Request Invocations"
                      stroke="#10b981"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorGraphReqs)"
                    />
                    <Area
                      yAxisId="right"
                      type="monotone"
                      dataKey="sharePct"
                      name="Relative Call Share (%)"
                      stroke="#818cf8"
                      strokeWidth={2}
                      fillOpacity={1}
                      fill="url(#colorGraphShare)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          {/* 2 & 3: Fan-In vs Fan-Out and Edge State Drift */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Identity Ingress vs Target Service Fan-Out Dynamics */}
            <Panel
              title="Identity Ingress vs Target Service Fan-Out Dynamics"
              subtitle="Caller services using each principal credential vs target microservices accessed"
            >
              {principalFanout.length === 0 ? (
                <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No data</div>
              ) : (
                <div className="h-64 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={principalFanout}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="name" stroke="#59616b" tick={{ fontSize: 10 }} />
                      <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} />
                      <Tooltip {...chartTooltip} />
                      <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                      <Bar dataKey="callersCount" name="Caller Services (Fan-in)" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="targetsCount" name="Target Services (Fan-out)" fill="#06b6d4" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>

            {/* Edge State & Behavioral Drift Volume */}
            <Panel
              title="Edge State & Behavioral Drift Distribution"
              subtitle="Request volume traversing established baseline edges vs changed/anomalous edges"
            >
              {edges.length === 0 ? (
                <div className="h-60 flex items-center justify-center text-xs text-[#6e7681]">No data</div>
              ) : (
                <div className="h-64 p-4">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={edgeStateVolume}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="name" stroke="#59616b" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#8b949e" tick={{ fontSize: 10 }} />
                      <Tooltip {...chartTooltip} formatter={(v: any) => [`${n(v, 0)} requests`, "Volume"]} />
                      <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                      <Bar dataKey="value" name="Request Volume" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Panel>
          </div>

          {/* 4. Interactive Relationship Matrix & Call Flow Inspector (Agent Fleet Table Style) */}
          <Panel
            title="Interactive Relationship Matrix & Call Flow Inspector"
            subtitle="Caller → Principal → Target microservice dependency records with drift status and trace inspection"
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[rgba(255,255,255,0.07)] text-[10px] uppercase tracking-wider text-[#59616b]">
                    {["Caller Service", "Principal Identity", "Target Service", "Edge State", "Invocations", "Relative Share", "Actions"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-4 py-2.5 font-semibold">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[rgba(255,255,255,0.05)]">
                  {edges.slice(0, 40).map((e, idx) => {
                    const isChanged = e.state === "changed";
                    const srcName = e.source.split(":")[1] || e.source;
                    const tgtName = e.target.split(":")[1] || e.target;
                    const share = ((e.requests || 0) / Math.max(1, totalRequests) * 100);
                    return (
                      <tr key={idx} className="transition hover:bg-white/[0.03]">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2 font-mono text-emerald-300">
                            <Server size={13} className="text-emerald-400 opacity-70" />
                            <span>{srcName}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => nav(`/users/${encodeURIComponent(srcName)}`)}
                            className="font-mono text-cyan-300 hover:underline"
                          >
                            {srcName.startsWith("user:") ? srcName : e.label || "principal"}
                          </button>
                        </td>
                        <td className="px-4 py-3 font-mono text-violet-300">
                          {tgtName}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                              isChanged
                                ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                                : "border-emerald-500/25 bg-emerald-500/10 text-emerald-400"
                            }`}
                          >
                            <span className={`h-1.5 w-1.5 rounded-full ${isChanged ? "bg-amber-400 animate-pulse" : "bg-emerald-400"}`} />
                            {isChanged ? "Changed" : "Normal"}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono font-semibold text-[#f5f3fa]">
                          {n(e.requests, 0)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-16 rounded-full bg-[rgba(255,255,255,0.08)] overflow-hidden">
                              <div
                                className={`h-full rounded-full ${isChanged ? "bg-amber-400" : "bg-indigo-500"}`}
                                style={{ width: `${Math.min(100, share)}%` }}
                              />
                            </div>
                            <span className="font-mono text-[10px] text-[#8b949e]">{share.toFixed(1)}%</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={() => nav(`/traces?service=${encodeURIComponent(tgtName)}`)}
                              className="btn text-[11px] py-1 border-white/10 text-[#c4bdd9] hover:text-white"
                            >
                              Traces
                            </button>
                            <button
                              onClick={() => nav(`/user-changes`)}
                              className="btn text-[11px] py-1 border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/20"
                            >
                              Changes
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      ) : (
        /* Classic Topology View */
        <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
          <Panel title="User dependency graph">
            <UserGraphCanvas graph={q.data!} onPrincipal={(p) => nav(`/users/${encodeURIComponent(p)}`)} />
          </Panel>
          <Panel title="Changed Edges" subtitle="Explicit labels accompany visual styling">
            <div className="max-h-[620px] overflow-auto scrollbar p-3">
              {q.data?.edges
                .filter((e) => e.state !== "normal")
                .map((e, i) => (
                  <div className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs" key={i}>
                    <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-300 font-semibold text-[10px]">
                      CHANGED
                    </span>
                    <div className="mt-2 font-mono text-[#f5f3fa]">
                      {e.source.split(":")[1]} → {e.target.split(":")[1]}
                    </div>
                    <div className="text-[#c4bdd9] mt-1">
                      {e.label} · {n(e.requests, 0)} requests
                    </div>
                  </div>
                ))}
            </div>
          </Panel>
        </div>
      )}
    </Page>
  );
}

export function UserAnalyticsPage(){const nav=useNavigate();const q=useQuery({queryKey:["user-analytics"],queryFn:()=>api<Record<string,UserItem[]>>(`/api/v1/user-analytics`)});if(q.isLoading)return <Page eyebrow="User Intelligence" title="User Analytics" description=""><Loading/></Page>;if(q.error)return <Page eyebrow="User Intelligence" title="User Analytics" description=""><ErrorState message={q.error.message}/></Page>;const sections:[[string,string,string],any[]][]=[[ ["most_active","Most Active Principals","Total observed credential use"],q.data?.most_active||[]],[ ["most_changed","Most Changed Principals","Explainable behavior score"],q.data?.most_changed||[]],[ ["shared_credentials","Shared Credential Usage","Accounts used by multiple caller services"],q.data?.shared_credentials||[]],[ ["source_diversity","Source Diversity","Accounts used from many source IPs"],q.data?.source_diversity||[]],[ ["most_targets","Broadest Service Access","Most target services"],q.data?.most_targets||[]],[ ["most_operations","Broadest API Usage","Most operations"],q.data?.most_operations||[]],[ ["newest","Newest Principals","Most recently first observed"],q.data?.newest||[]],[ ["dormant_reactivated","Recently Reactivated","Returned after dormancy"],q.data?.dormant_reactivated||[]]];return <Page eyebrow="User Intelligence" title="Account Behavior Analytics" description="Estate-wide identity patterns; shared usage is investigation context, not an automatic malicious classification."><div className="grid gap-4 lg:grid-cols-2">{sections.map(([meta,rows])=><Panel title={meta[1]} subtitle={meta[2]} key={meta[0]}><div className="divide-y divide-[rgba(255,255,255,0.08)]">{rows.slice(0,10).map((u:any,i:number)=><button onClick={()=>nav(`/users/${encodeURIComponent(u.principal_name)}`)} key={u.principal_name} className="flex w-full items-center justify-between p-3 text-left text-xs hover:bg-white/[0.05] transition"><span><b className="font-mono text-cyan-300 font-medium">{i+1}. {u.principal_name}</b><small className="ml-2 text-[#9e96b8]">{u.principal_type||"shared usage"}</small></span><span className="font-mono text-[#f5f3fa] font-medium">{n(u.behavior_score??u.callers??u.unique_sources??u.unique_targets??u.unique_operations??u.total_requests,0)}</span></button>)}{!rows.length&&<div className="p-4 text-xs text-[#c4bdd9]">No qualifying principals.</div>}</div></Panel>)}</div></Page>}

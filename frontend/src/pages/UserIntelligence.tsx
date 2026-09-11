import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  Activity, ArrowLeft, ArrowRight, BarChart3, Check, Clock3, ExternalLink,
  GitCompareArrows, KeyRound, Network, Search, Server, ShieldQuestion,
  Workflow, X,
} from "lucide-react";
import { api, queryString } from "../api";
import { ErrorState, Loading, MetricCard, Page, Panel, n } from "../components";
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

export function UserChangesPage(){
  const {filters}=useFilters();
  const nav=useNavigate();
  const qc=useQueryClient();
  const params=new URLSearchParams(location.search);
  const [principal,setPrincipal]=useState(params.get("principal")||"");
  const [type,setType]=useState("");
  const [severity,setSeverity]=useState("");
  const [scope,setScope]=useState<"all"|"window">("all");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"changes" | "incidents">("changes");
  const [reviewTarget, setReviewTarget] = useState<UserChange | null>(null);
  const [reviewScope, setReviewScope] = useState("change_rule");
  const [reviewReason, setReviewReason] = useState("");
  const [reviewExpiry, setReviewExpiry] = useState("never");

  const qs=scope==="window"
    ? queryString(filters,{principal:principal||undefined,change_type:type||undefined,severity:severity||undefined})
    : queryString({timezone:filters.timezone,comparison:filters.comparison} as any,{principal:principal||undefined,change_type:type||undefined,severity:severity||undefined});
  const q=useQuery({
    queryKey:["user-changes",qs,scope],
    queryFn:()=>api<{items:UserChange[];count:number;total_unfiltered?:number;fallback_applied?:boolean}>(`/api/v1/user-changes?${qs}&limit=500`)
  });

  const incidentsQuery = useQuery({
    queryKey: ["incidents", qs],
    queryFn: () => api<{ items: IncidentItem[]; count: number }>(`/api/v1/incidents?${qs}&limit=100`),
    enabled: activeTab === "incidents",
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

  return <Page eyebrow="User Intelligence" title="User Activity Changes & Incidents" description="Observed application principal deviations, bounded incidents, and explainable change events.">
    {q.data?.fallback_applied && (
      <div className="card mb-4 flex items-center justify-between border-amber-500/40 bg-amber-500/15 p-3 text-xs text-amber-200">
        <span>Notice: No changes detected in the selected time window. Showing all {q.data.total_unfiltered || q.data.count} historical changes across the estate.</span>
        <button onClick={()=>setScope("all")} className="btn border-amber-500/50 text-amber-200">View All Time</button>
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

    {/* Header Controls and Tabs */}
    <div className="card mb-4 flex flex-wrap items-center justify-between gap-3 p-3">
      <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] p-0.5">
          <button onClick={() => setActiveTab("changes")} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${activeTab === "changes" ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm" : "text-[#c4bdd9] hover:text-white"}`}>Behavioral Changes ({q.data?.count || 0})</button>
          <button onClick={() => setActiveTab("incidents")} className={`rounded-md px-3 py-1.5 text-xs font-semibold transition ${activeTab === "incidents" ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm" : "text-[#c4bdd9] hover:text-white"}`}>Bounded Incidents</button>
        </div>
        <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] p-0.5">
          <button onClick={()=>setScope("all")} className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${scope==="all"?"bg-violet-600 text-white shadow-sm":"text-[#c4bdd9] hover:text-white"}`}>All Time ({q.data?.total_unfiltered ?? q.data?.count ?? 0})</button>
          <button onClick={()=>setScope("window")} className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${scope==="window"?"bg-violet-600 text-white shadow-sm":"text-[#c4bdd9] hover:text-white"}`}>Selected Window</button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input className="min-w-44 rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:border-cyan-400" placeholder="Filter by principal..." value={principal} onChange={e=>setPrincipal(e.target.value)}/>
        <select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={type} onChange={e=>setType(e.target.value)}>
          <option value="" className="bg-[#1a172a]">All change types</option>
          {["USERNAME_FIRST_SEEN","NEW_CALLER","NEW_SOURCE_IP","NEW_PRINCIPAL_ON_SOURCE","NEW_TARGET","NEW_OPERATION","NEW_RELATIONSHIP","DORMANT_REACTIVATED","UNUSUAL_TIME","CALLER_PRINCIPAL_SWITCH","OPERATION_MIX_SHIFT","TARGET_FANOUT_SURGE","SOURCE_FANOUT_SURGE","PRINCIPAL_RATE_SURGE","AUTH_FAILURE_BURST","FAILURE_THEN_SUCCESS","RELATIONSHIP_REAPPEARED","RELATIONSHIP_DISAPPEARED"].map(x=><option className="bg-[#1a172a]" key={x}>{x}</option>)}
        </select>
        <select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={severity} onChange={e=>setSeverity(e.target.value)}>
          <option value="" className="bg-[#1a172a]">Any importance</option>
          {["high","medium","low"].map(x=><option className="bg-[#1a172a]" key={x}>{x}</option>)}
        </select>
      </div>
    </div>

    {/* Tab 1: Behavioral Changes */}
    {activeTab === "changes" && (
      q.isLoading?<Loading/>:q.error?<ErrorState message={q.error.message}/>:<Panel title={`${q.data?.count||0} behavior changes`} subtitle="Click any event to inspect full 7-question explainability answers">
        <div className="divide-y divide-[rgba(255,255,255,0.08)]">
          {q.data?.items.map(c => {
            const isExpanded = expandedId === c.id;
            const r = c.reason || {};
            return (
              <div className={`p-4 transition hover:bg-white/[0.02] ${isExpanded ? "bg-white/[0.03]" : ""}`} key={c.id}>
                <div className="grid gap-3 md:grid-cols-[110px_180px_1fr_auto] items-start cursor-pointer" onClick={() => setExpandedId(isExpanded ? null : c.id)}>
                  <div className="font-mono text-[10px] text-[#9e96b8]">{new Date(c.detected_at).toLocaleString()}</div>
                  <div>
                    <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold ${tone(c.severity)}`}>{label(c.change_type)}</span>
                    <div className="mt-2 font-mono text-cyan-300 font-medium hover:underline" onClick={(e) => { e.stopPropagation(); nav(`/users/${encodeURIComponent(c.principal_name)}`); }}>{c.principal_name}</div>
                  </div>
                  <div className="text-xs">
                    <b className="text-[#f5f3fa] text-sm">{r.what_changed || r.summary || c.new_value}</b>
                    <div className="mt-1.5 flex flex-wrap gap-2 text-[#c4bdd9] text-[11px]">
                      {c.caller_service && <span className="rounded bg-white/[0.05] px-1.5 py-0.5">Caller: <b className="text-emerald-300 font-normal">{c.caller_service}</b></span>}
                      {c.source_ip && <span className="rounded bg-white/[0.05] px-1.5 py-0.5">Source: <b className="text-sky-300 font-normal">{c.source_ip}</b></span>}
                      {c.target_service && <span className="rounded bg-white/[0.05] px-1.5 py-0.5">Target: <b className="text-violet-300 font-normal">{c.target_service}</b></span>}
                      {c.operation && <span className="rounded bg-white/[0.05] px-1.5 py-0.5">Op: <b className="text-amber-300 font-normal">{c.operation}</b></span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5" onClick={e => e.stopPropagation()}>
                    <button title="Accept as expected change" className="btn text-xs border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/20" onClick={() => setReviewTarget(c)}>Expected</button>
                    <button title="Mark for deep investigation" className="btn text-xs border-amber-500/40 text-amber-300 hover:bg-amber-500/20" onClick={() => submitReview(c.id, "investigate")}>Investigate</button>
                    <button title="Flag as data-quality issue" className="btn text-xs border-white/20 text-[#c4bdd9] hover:bg-white/10" onClick={() => submitReview(c.id, "data_quality")}>Data-Quality</button>
                  </div>
                </div>

                {/* 7 Questions Explainability Drawer */}
                {isExpanded && (
                  <div className="mt-4 rounded-xl border border-cyan-500/25 bg-[#12101b] p-4 text-xs">
                    <div className="mb-3 flex items-center justify-between border-b border-white/10 pb-2">
                      <span className="font-semibold text-cyan-400">WHAT CHANGED COMPARED WITH NORMAL? (7-Question Explainability)</span>
                      <span className="font-mono text-[10px] text-[#9e96b8]">Fingerprint: #{c.id} · Priority: {c.severity.toUpperCase()}</span>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                        <span className="text-[10px] uppercase font-bold text-cyan-300">1. What changed?</span>
                        <div className="mt-1 text-white font-medium">{r.what_changed || r.summary || c.new_value}</div>
                      </div>
                      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                        <span className="text-[10px] uppercase font-bold text-cyan-300">2. Compared with what?</span>
                        <div className="mt-1 text-[#c4bdd9]">{r.compared_with || `This entity was not observed for the principal during the available baseline.`}</div>
                      </div>
                      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                        <span className="text-[10px] uppercase font-bold text-cyan-300">3. Where?</span>
                        <div className="mt-1 space-y-1 font-mono text-[11px] text-[#c4bdd9]">
                          <div>Principal: <b className="text-white">{c.principal_name}</b> {c.principal_id && `(${c.principal_id})`}</div>
                          <div>Path: {c.caller_service || "direct"} → {c.target_service || "unknown"} ({c.operation || "any"})</div>
                          {c.source_ip && <div>Source Address: {c.source_ip}</div>}
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                        <span className="text-[10px] uppercase font-bold text-cyan-300">4. How reliable is it?</span>
                        <div className="mt-1 text-[#c4bdd9]">
                          Attribution: <b className="text-emerald-300">{r.how_reliable?.attribution_method || c.reliability || "trace_linked"}</b> · Quality: <b className="text-white">{r.how_reliable?.collection_quality || "healthy"}</b> · Baseline: <b className="text-white">{r.how_reliable?.baseline_readiness || "ready"}</b>
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                        <span className="text-[10px] uppercase font-bold text-cyan-300">5. Why this priority?</span>
                        <div className="mt-1 text-[#c4bdd9]">
                          Contributed <b className="text-white">+{c.score} pts</b> in <b className="text-cyan-300">{c.family || "access"}</b> family (capped at {r.why_priority?.family_cap || 35} pts). Deduplicated against repetitive records in window.
                        </div>
                      </div>
                      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
                        <span className="text-[10px] uppercase font-bold text-cyan-300">6. What proves it?</span>
                        <div className="mt-1 text-[#c4bdd9]">
                          Observed at {new Date(c.detected_at).toLocaleTimeString()}.
                          {r.what_proves_it?.representative_traces && r.what_proves_it.representative_traces.length > 0 ? (
                            <div className="mt-1 flex flex-wrap gap-1.5 items-center">
                              <span>Traces:</span>
                              {r.what_proves_it.representative_traces.map((tid: string) => (
                                <a key={tid} href={`/traces/${encodeURIComponent(tid)}`} className="font-mono text-cyan-400 hover:underline bg-cyan-950/40 px-1 rounded">{tid.slice(0, 12)}…</a>
                              ))}
                            </div>
                          ) : (
                            <span className="ml-1 text-[11px] text-[#9e96b8]">Evidence captured from transaction records.</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.02] p-3 flex items-center justify-between">
                      <div>
                        <span className="text-[10px] uppercase font-bold text-cyan-300">7. What happened afterward?</span>
                        <div className="mt-1 text-white">{r.what_happened_afterward || (c.status === "expected" ? "Accepted by operator" : c.status === "reviewed" ? "Under active investigation" : "Awaiting operational review")}</div>
                      </div>
                      <div className="flex gap-2">
                        <button className="btn text-xs border-cyan-500/40 text-cyan-300" onClick={() => setReviewTarget(c)}>Review Scope</button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {(!q.data?.items || q.data.items.length === 0) && (
            <div className="p-6 text-center text-xs text-[#c4bdd9]">
              No behavioral changes found matching criteria.
            </div>
          )}
        </div>
      </Panel>
    )}

    {/* Tab 2: Bounded Incidents */}
    {activeTab === "incidents" && (
      incidentsQuery.isLoading ? <Loading/> : incidentsQuery.error ? <ErrorState message={incidentsQuery.error.message}/> : (
        <Panel title={`${incidentsQuery.data?.count || 0} bounded incidents`} subtitle="Incidents merge related changes within 15m windows, close after 30m idle, and cap scores across distinct families">
          <div className="divide-y divide-[rgba(255,255,255,0.08)]">
            {incidentsQuery.data?.items.map(inc => (
              <div className="p-4 transition hover:bg-white/[0.02]" key={inc.incident_id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`rounded border px-2 py-0.5 text-xs font-bold ${inc.priority === "high" ? "text-rose-300 border-rose-500/40 bg-rose-500/15" : inc.priority === "medium" ? "text-amber-300 border-amber-500/40 bg-amber-500/15" : "text-emerald-300 border-emerald-500/40 bg-emerald-500/15"}`}>
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
    )}
  </Page>;
}

type GraphData={nodes:Array<{id:string;label:string;type:string}>;edges:Array<{source:string;target:string;requests:number;state:string;label:string}>;mode:string};
function UserGraphCanvas({graph,onPrincipal}:{graph:GraphData;onPrincipal:(p:string)=>void}){const ref=useRef<HTMLCanvasElement>(null);const positions=useMemo(()=>{const groups={caller:graph.nodes.filter(n=>n.type==="caller"),principal:graph.nodes.filter(n=>n.type==="principal"),target:graph.nodes.filter(n=>n.type==="target")};const map=new Map<string,{x:number;y:number}>();(["caller","principal","target"] as const).forEach((type,col)=>groups[type].forEach((node,i)=>map.set(node.id,{x:130+col*350,y:55+i*Math.max(42,520/Math.max(1,groups[type].length))})));return map},[graph]);useEffect(()=>{const c=ref.current;if(!c)return;const dpr=devicePixelRatio||1,r=c.getBoundingClientRect();c.width=r.width*dpr;c.height=r.height*dpr;const x=c.getContext("2d")!;x.scale(dpr,dpr);x.clearRect(0,0,r.width,r.height);for(const e of graph.edges){const a=positions.get(e.source),b=positions.get(e.target);if(!a||!b)continue;x.beginPath();x.moveTo(a.x,a.y);x.lineTo(b.x,b.y);x.strokeStyle=e.state==="changed"?"#f59e0b":"#6366f1";x.lineWidth=Math.min(5,1+Math.sqrt(e.requests)/10);if(e.state==="changed")x.setLineDash([7,4]);x.stroke();x.setLineDash([])}for(const node of graph.nodes){const p=positions.get(node.id)!;x.beginPath();x.arc(p.x,p.y,18,0,Math.PI*2);x.fillStyle=node.type==="principal"?"#8b5cf6":node.type==="caller"?"#10b981":"#0ea5e9";x.fill();x.strokeStyle=node.type==="principal"?"#c4b5fd":node.type==="caller"?"#6ee7b7":"#7dd3fc";x.lineWidth=2;x.stroke();x.fillStyle="#f5f3fa";x.font="13px Inter";x.textAlign="center";x.fillText(node.label.slice(0,24),p.x,p.y+34)}} ,[graph,positions]);return <canvas ref={ref} onClick={e=>{const r=e.currentTarget.getBoundingClientRect();const px=e.clientX-r.left,py=e.clientY-r.top;for(const node of graph.nodes.filter(n=>n.type==="principal")){const p=positions.get(node.id)!;if(Math.hypot(px-p.x,py-p.y)<24)onPrincipal(node.label)}}} className="h-[620px] w-full cursor-pointer"/>}
export function UserGraphPage(){const nav=useNavigate();const {filters}=useFilters();const params=new URLSearchParams(location.search);const [mode,setMode]=useState(params.get("principal")?"principal":"estate");const [principal,setPrincipal]=useState(params.get("principal")||"");const [service,setService]=useState("");const qs=queryString(filters,{principal:mode==="principal"&&principal?principal:undefined,service:mode==="service"&&service?service:undefined});const q=useQuery({queryKey:["user-graph",qs],queryFn:()=>api<GraphData>(`/api/v1/user-graph?${qs}`)});return <Page eyebrow="User Intelligence" title="Caller → Principal → Target" description="Credential-centered dependency evidence. Dashed amber edges are changed; labels and badges provide non-color evidence."><div className="card mb-4 flex flex-wrap gap-2 p-3"><select className="btn bg-[rgba(255,255,255,0.04)] border-[rgba(255,255,255,0.14)] text-[#f5f3fa]" value={mode} onChange={e=>setMode(e.target.value)}><option value="estate" className="bg-[#1a172a]">Estate view</option><option value="principal" className="bg-[#1a172a]">Principal centered</option><option value="service" className="bg-[#1a172a]">Target service usage</option></select>{mode==="principal"&&<input className="rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:border-cyan-400" value={principal} onChange={e=>setPrincipal(e.target.value)} placeholder="Principal name"/>}{mode==="service"&&<input className="rounded-lg border border-[rgba(255,255,255,0.14)] bg-white/[0.04] px-3 py-1.5 text-xs text-[#f5f3fa] placeholder:text-[#9e96b8] outline-none focus:border-indigo-400" value={service} onChange={e=>setService(e.target.value)} placeholder="Target service"/>}<span className="chip">Normal: solid · Changed: dashed + badge</span></div>{q.isLoading?<Loading/>:q.error?<ErrorState message={q.error.message}/>:<div className="grid gap-4 xl:grid-cols-[1fr_320px]"><Panel title="User dependency graph"><UserGraphCanvas graph={q.data!} onPrincipal={p=>nav(`/users/${encodeURIComponent(p)}`)}/></Panel><Panel title="Changed Edges" subtitle="Explicit labels accompany visual styling"><div className="max-h-[620px] overflow-auto scrollbar p-3">{q.data?.edges.filter(e=>e.state!=="normal").map((e,i)=><div className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs" key={i}><span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-300 font-semibold text-[10px]">CHANGED</span><div className="mt-2 font-mono text-[#f5f3fa]">{e.source.split(":")[1]} → {e.target.split(":")[1]}</div><div className="text-[#c4bdd9] mt-1">{e.label} · {n(e.requests,0)} requests</div></div>)}</div></Panel></div>}</Page>}

export function UserAnalyticsPage(){const nav=useNavigate();const q=useQuery({queryKey:["user-analytics"],queryFn:()=>api<Record<string,UserItem[]>>(`/api/v1/user-analytics`)});if(q.isLoading)return <Page eyebrow="User Intelligence" title="User Analytics" description=""><Loading/></Page>;if(q.error)return <Page eyebrow="User Intelligence" title="User Analytics" description=""><ErrorState message={q.error.message}/></Page>;const sections:[[string,string,string],any[]][]=[[ ["most_active","Most Active Principals","Total observed credential use"],q.data?.most_active||[]],[ ["most_changed","Most Changed Principals","Explainable behavior score"],q.data?.most_changed||[]],[ ["shared_credentials","Shared Credential Usage","Accounts used by multiple caller services"],q.data?.shared_credentials||[]],[ ["source_diversity","Source Diversity","Accounts used from many source IPs"],q.data?.source_diversity||[]],[ ["most_targets","Broadest Service Access","Most target services"],q.data?.most_targets||[]],[ ["most_operations","Broadest API Usage","Most operations"],q.data?.most_operations||[]],[ ["newest","Newest Principals","Most recently first observed"],q.data?.newest||[]],[ ["dormant_reactivated","Recently Reactivated","Returned after dormancy"],q.data?.dormant_reactivated||[]]];return <Page eyebrow="User Intelligence" title="Account Behavior Analytics" description="Estate-wide identity patterns; shared usage is investigation context, not an automatic malicious classification."><div className="grid gap-4 lg:grid-cols-2">{sections.map(([meta,rows])=><Panel title={meta[1]} subtitle={meta[2]} key={meta[0]}><div className="divide-y divide-[rgba(255,255,255,0.08)]">{rows.slice(0,10).map((u:any,i:number)=><button onClick={()=>nav(`/users/${encodeURIComponent(u.principal_name)}`)} key={u.principal_name} className="flex w-full items-center justify-between p-3 text-left text-xs hover:bg-white/[0.05] transition"><span><b className="font-mono text-cyan-300 font-medium">{i+1}. {u.principal_name}</b><small className="ml-2 text-[#9e96b8]">{u.principal_type||"shared usage"}</small></span><span className="font-mono text-[#f5f3fa] font-medium">{n(u.behavior_score??u.callers??u.unique_sources??u.unique_targets??u.unique_operations??u.total_requests,0)}</span></button>)}{!rows.length&&<div className="p-4 text-xs text-[#c4bdd9]">No qualifying principals.</div>}</div></Panel>)}</div></Page>}

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
  reason?: { summary?: string; evidence?: Record<string, unknown>; framing?: string };
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
const tone = (severity: string) => severity === "high" ? "text-rose-400 border-rose-500/30 bg-rose-500/10" : severity === "medium" ? "text-amber-400 border-amber-500/30 bg-amber-500/10" : "text-indigo-300 border-indigo-500/30 bg-indigo-500/10";
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
  return <Page eyebrow="User Intelligence" title="Observed Principals" description="Inventory of presented usernames and system accounts. Identities are evidence of credential use, not proof of a human actor.">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-7">
      {[["Observed",summary.data?.observed_principals,"all known principals"],["Active",summary.data?.active_principals,"latest 15 minutes"],["New today",summary.data?.new_principals_today,"first observed"],["With changes",summary.data?.principals_with_changes,"selected window"],["Reactivated",summary.data?.dormant_reactivated,"after dormancy"],["New targets",summary.data?.new_service_relationships,"relationship changes"],["New callers",summary.data?.new_caller_relationships,"credential origins"]].map(([k,v,d])=><MetricCard key={String(k)} label={String(k)} value={n(Number(v||0),0)} detail={String(d)} />)}
    </div>
    <div className="card my-4 flex flex-wrap gap-2 p-3">
      <div className="flex min-w-64 flex-1 items-center gap-2 rounded-lg border border-white/10 px-3"><Search size={14}/><input className="w-full bg-transparent py-2 text-xs outline-none" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search principal, IP, caller, target, operation…"/></div>
      <select className="btn" value={sort} onChange={e=>setSort(e.target.value)}>{[["most_active","Most active"],["most_changed","Most changed"],["most_target_services","Most targets"],["most_operations","Most operations"],["newest","Newest"],["dormant_returned","Dormant returned"]].map(([v,t])=><option className="bg-[#12151a]" value={v} key={v}>{t}</option>)}</select>
      <select className="btn" value={active} onChange={e=>setActive(e.target.value)}><option value="" className="bg-[#12151a]">Any activity</option><option value="active" className="bg-[#12151a]">Active</option><option value="inactive" className="bg-[#12151a]">Inactive</option></select>
      <select className="btn" value={level} onChange={e=>setLevel(e.target.value)}><option value="" className="bg-[#12151a]">Any behavior level</option>{["low","medium","high"].map(x=><option className="bg-[#12151a]" value={x} key={x}>{x}</option>)}</select>
    </div>
    {users.isLoading?<Loading/>:users.error?<ErrorState message={users.error.message}/>:<Panel title={`${users.data?.count||0} principals`} subtitle="Status and recency are evaluated at the selected dataset window end"><div className="overflow-auto"><table className="w-full min-w-[1100px] text-left text-xs"><thead><tr>{["Principal","Status","Last seen","Callers","Source IPs","Targets","Operations","Requests","Changes","Behavior"].map(h=><th className="table-head px-4 py-3" key={h}>{h}</th>)}</tr></thead><tbody>{users.data?.items.map(u=><tr key={u.principal_name} onClick={()=>nav(`/users/${encodeURIComponent(u.principal_name)}?${queryString(filters)}`)} className="cursor-pointer border-t border-white/[.05] hover:bg-white/[.03]"><td className="px-4 py-3 font-mono text-indigo-300"><span className="inline-flex items-center gap-2"><KeyRound size={13}/>{u.principal_name}</span><div className="mt-1 text-[10px] text-[#6e7681]">{u.principal_type} · {u.learning_status||"learning"}</div></td><td className="px-4"><span className={u.status==="Active"?"text-emerald-400":"text-[#8b949e]"}>{u.status}</span></td><td className="px-4 text-[#8b949e]">{formatDate(u.last_seen)}</td>{[u.unique_callers,u.unique_sources,u.unique_targets,u.unique_operations,u.total_requests,u.recent_changes].map((v,i)=><td className="px-4 font-mono" key={i}>{n(v,0)}</td>)}<td className="px-4"><span className={`rounded border px-2 py-1 ${tone(u.behavior_level.toLowerCase())}`}>{u.behavior_level} · {u.behavior_score}</span></td></tr>)}</tbody></table></div></Panel>}
  </Page>;
}

function DistributionPanel({title,current,normal}:{title:string;current:Distribution[];normal:Distribution[]}) {
  const normalBy = new Map(normal.map(x=>[x.value,x.share]));
  const learning=!normal.length;
  return <Panel title={title} subtitle={learning?"Historical baseline is still learning; current activity is shown without drift claims":"Current distribution compared with historical baseline"}><div className="divide-y divide-white/[.05] p-3">{current.slice(0,8).map(item=>{const baseline=normalBy.get(item.value)||0; const delta=item.share-baseline; return <div key={item.value} className="py-2"><div className="flex justify-between gap-3 text-xs"><span className="truncate font-mono text-[#e6edf3]">{item.value}</span><span className={!learning&&Math.abs(delta)>.15?"font-mono text-amber-400":"font-mono text-[#8b949e]"}>{(item.share*100).toFixed(1)}% <small>{learning?"(learning)":`(${delta>=0?"+":""}${(delta*100).toFixed(1)}pp)`}</small></span></div><div className="mt-1 h-1.5 rounded bg-white/[.05]"><div className="h-full rounded bg-indigo-500" style={{width:`${Math.max(1,item.share*100)}%`}}/></div></div>})}{!current.length&&<div className="p-4 text-xs text-[#8b949e]">No activity in this period.</div>}</div></Panel>;
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
    <div className="card mb-4 flex flex-wrap items-center justify-between gap-4 p-4"><div><div className="flex items-center gap-2"><span className={p.status==="Active"?"text-emerald-400":"text-[#8b949e]"}>● {p.status} at window end</span><span className="chip">{p.principal_type}</span><span className="chip">Baseline: {p.learning_status||"learning"}</span></div><div className="mt-2 text-xs text-[#8b949e]">First seen {formatDate(p.first_seen)} · Last seen {formatDate(p.last_seen)}</div></div><div className={`rounded-lg border px-4 py-2 ${tone(p.behavior_level.toLowerCase())}`}><div className="text-[10px] uppercase">Behavior change by distinct evidence type</div><div className="font-mono text-xl">{p.behavior_score} / 100 · {p.behavior_level}</div></div></div>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">{[["Requests",p.total_requests,"observed"],["Callers",p.unique_callers,"credential origins"],["Source IPs",p.unique_sources,"network origins"],["Targets",p.unique_targets,"services used"],["Operations",p.unique_operations,"APIs invoked"],["Changes",p.changes.length,"selected period"]].map(([k,v,d])=><MetricCard key={String(k)} label={String(k)} value={n(Number(v),0)} detail={String(d)}/>)}</div>
    <div className="my-4 grid gap-4 lg:grid-cols-2"><DistributionPanel title="Caller Services" current={p.current.callers||[]} normal={p.normal.callers||[]}/><DistributionPanel title="Source IPs" current={p.current.sources||[]} normal={p.normal.sources||[]}/><DistributionPanel title="Target Services" current={p.current.targets||[]} normal={p.normal.targets||[]}/><DistributionPanel title="Operations" current={p.current.operations||[]} normal={p.normal.operations||[]}/></div>
    <Panel title="Normal Activity Pattern" subtitle={`Typical active window: ${p.typical_active_window}`}><div className="grid gap-1 p-4" style={{gridTemplateColumns:"repeat(24,minmax(0,1fr))"}}>{Array.from({length:168},(_,i)=>{const day=Math.floor(i/24),hour=i%24,value=p.hourly_activity.find(x=>x.day_of_week===day&&x.hour_of_day===hour)?.observation_count||0;const max=Math.max(1,...p.hourly_activity.map(x=>x.observation_count));return <div key={i} title={`Day ${day}, ${hour}:00 · ${value} requests`} className="h-5 rounded-sm" style={{backgroundColor:`rgba(99,102,241,${.06+.94*value/max})`}}/>})}</div><div className="px-4 pb-3 text-[10px] text-[#8b949e]">7 rows × 24 hours · intensity represents historical request volume</div></Panel>
    <Panel title="What Changed?" subtitle="Evidence is shown alongside the score; changes are not automatically security incidents." className="mt-4"><div className="grid gap-2 p-4 md:grid-cols-2">{p.changes.slice(0,12).map(c=><ChangeCard key={c.id} change={c} onOpen={()=>nav(`/user-changes?principal=${encodeURIComponent(principal)}`)}/>)}{!p.changes.length&&<div className="p-4 text-xs text-[#8b949e]">No unexplained changes in this period.</div>}</div></Panel>
    <div className="mt-4 grid gap-4 xl:grid-cols-[1.2fr_.8fr]"><Panel title="Behavior Timeline" subtitle="Trace activity and relationship changes in chronological order" action={<select className="btn" value={timelineKind} onChange={e=>setTimelineKind(e.target.value)}>{["all","new_relationships","operations","errors"].map(x=><option className="bg-[#12151a]" key={x}>{x}</option>)}</select>}><div className="max-h-[520px] divide-y divide-white/[.05] overflow-auto">{timeline.data?.items.map((item,i)=><div className="flex gap-3 p-3 text-xs" key={`${item.timestamp_ms}-${i}`}><Clock3 size={13} className="mt-0.5 shrink-0 text-indigo-400"/><div><div className="font-mono text-[10px] text-[#8b949e]">{formatDate(item.timestamp_ms)}</div><div className="mt-1"><b>{label(item.event_type)}</b> · {item.caller_service||"unknown caller"} → <span className="text-indigo-300">{principal}</span> → {item.target_service||"unknown target"} → {item.operation||""}</div></div></div>)}</div></Panel><Panel title="Where Is This Credential Used?" subtitle="Caller and source evidence"><div className="p-4">{(p.current.callers||[]).map(c=><div key={c.value} className="mb-3 rounded-lg border border-white/[.07] p-3"><div className="flex items-center gap-2 text-xs font-semibold"><Server size={13}/>{c.value}</div><div className="mt-2 space-y-1 pl-5 font-mono text-[11px] text-[#8b949e]">{(p.current.sources||[]).slice(0,6).map(s=><div key={s.value}>├── {s.value}</div>)}</div></div>)}</div></Panel></div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2"><SimpleTable title="Services Used" rows={p.current.targets||[]} headers={["Service","First seen","Last seen","Requests"]}/><SimpleTable title="Operations" rows={p.current.operations||[]} headers={["Operation / Target","First seen","Last seen","Count"]}/></div>
  </Page>;
}

function SimpleTable({title,rows,headers}:{title:string;rows:Distribution[];headers:string[]}){return <Panel title={title}><div className="overflow-auto"><table className="w-full text-xs"><thead><tr>{headers.map(h=><th className="table-head px-3 py-2" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map(r=><tr className="border-t border-white/[.05]" key={r.value}><td className="px-3 py-2 font-mono text-indigo-300">{r.value}</td><td className="px-3">{formatDate(r.first_seen)}</td><td className="px-3">{formatDate(r.last_seen)}</td><td className="px-3 font-mono">{n(r.requests,0)}</td></tr>)}</tbody></table></div></Panel>}
function ChangeCard({change,onOpen}:{change:UserChange;onOpen?:()=>void}){return <button onClick={onOpen} className="rounded-lg border border-white/[.07] bg-white/[.02] p-3 text-left hover:border-indigo-500/40"><div className="flex items-center justify-between"><span className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase ${tone(change.severity)}`}>{label(change.change_type)}</span><span className="font-mono text-[10px] text-[#8b949e]">+{change.score}</span></div><div className="mt-2 font-mono text-xs text-indigo-300">{change.principal_name}</div><p className="mt-1 text-xs text-[#c9d1d9]">{change.reason?.summary||`${change.old_value||"historical behavior"} → ${change.new_value||"new observation"}`}</p><div className="mt-2 text-[10px] text-[#8b949e]">{formatDate(change.detected_at)} · {change.status}</div></button>}

export function UserChangesPage(){
  const {filters}=useFilters();
  const nav=useNavigate();
  const qc=useQueryClient();
  const params=new URLSearchParams(location.search);
  const [principal,setPrincipal]=useState(params.get("principal")||"");
  const [type,setType]=useState("");
  const [severity,setSeverity]=useState("");
  const [scope,setScope]=useState<"all"|"window">("all");
  const qs=scope==="window"
    ? queryString(filters,{principal:principal||undefined,change_type:type||undefined,severity:severity||undefined})
    : queryString({timezone:filters.timezone,comparison:filters.comparison} as any,{principal:principal||undefined,change_type:type||undefined,severity:severity||undefined});
  const q=useQuery({
    queryKey:["user-changes",qs,scope],
    queryFn:()=>api<{items:UserChange[];count:number;total_unfiltered?:number;fallback_applied?:boolean}>(`/api/v1/user-changes?${qs}&limit=500`)
  });
  async function status(id:number,value:string){
    await api(`/api/v1/user-changes/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:value})});
    qc.invalidateQueries({queryKey:["user-changes"]});
  }
  return <Page eyebrow="User Intelligence" title="User Activity Changes" description="Identity behavior changes, separated from service and system anomalies.">
    {q.data?.fallback_applied && (
      <div className="card mb-4 flex items-center justify-between border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
        <span>Notice: No changes detected in the selected time window. Showing all {q.data.total_unfiltered || q.data.count} historical changes across the estate.</span>
        <button onClick={()=>setScope("all")} className="btn border-amber-500/40 text-amber-200">View All Time</button>
      </div>
    )}
    <div className="card mb-4 flex flex-wrap items-center gap-2 p-3">
      <div className="flex items-center rounded-lg border border-[rgba(255,255,255,0.08)] bg-white/[0.03] p-0.5">
        <button onClick={()=>setScope("all")} className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${scope==="all"?"bg-white/[0.12] text-white shadow-sm":"text-[#8b949e] hover:text-[#f0f3f6]"}`}>All Time ({q.data?.total_unfiltered ?? q.data?.count ?? 0})</button>
        <button onClick={()=>setScope("window")} className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${scope==="window"?"bg-white/[0.12] text-white shadow-sm":"text-[#8b949e] hover:text-[#f0f3f6]"}`}>Selected Window</button>
      </div>
      <input className="min-w-56 flex-1 rounded border border-white/10 bg-transparent px-3 text-xs" placeholder="Filter by principal..." value={principal} onChange={e=>setPrincipal(e.target.value)}/>
      <select className="btn" value={type} onChange={e=>setType(e.target.value)}>
        <option value="" className="bg-[#12151a]">All change types</option>
        {["USERNAME_FIRST_SEEN","NEW_CALLER","NEW_SOURCE_IP","NEW_TARGET","NEW_OPERATION","NEW_RELATIONSHIP","DORMANT_REACTIVATED","UNUSUAL_TIME","CALLER_EXPANSION","TARGET_EXPANSION","OPERATION_EXPANSION","RELATIONSHIP_REAPPEARED","RELATIONSHIP_DISAPPEARED"].map(x=><option className="bg-[#12151a]" key={x}>{x}</option>)}
      </select>
      <select className="btn" value={severity} onChange={e=>setSeverity(e.target.value)}>
        <option value="" className="bg-[#12151a]">Any severity</option>
        {["high","medium","low"].map(x=><option className="bg-[#12151a]" key={x}>{x}</option>)}
      </select>
    </div>
    {q.isLoading?<Loading/>:q.error?<ErrorState message={q.error.message}/>:<Panel title={`${q.data?.count||0} behavior changes`}>
      <div className="divide-y divide-white/[.06]">
        {q.data?.items.map(c=><div className="grid gap-3 p-4 md:grid-cols-[90px_180px_1fr_auto]" key={c.id}>
          <div className="font-mono text-[10px] text-[#8b949e]">{new Date(c.detected_at).toLocaleString()}</div>
          <div>
            <span className={`rounded border px-2 py-1 text-[10px] font-semibold ${tone(c.severity)}`}>{label(c.change_type)}</span>
            <div className="mt-2 font-mono text-indigo-300 cursor-pointer" onClick={()=>nav(`/users/${encodeURIComponent(c.principal_name)}`)}>{c.principal_name}</div>
          </div>
          <div className="text-xs">
            <b>{c.reason?.summary||c.new_value}</b>
            <div className="mt-1 text-[#8b949e]">
              {c.caller_service&&`Caller ${c.caller_service} · `}
              {c.source_ip&&`Source ${c.source_ip} · `}
              {c.target_service&&`Target ${c.target_service} · `}
              {c.operation&&`Operation ${c.operation}`}
            </div>
            <div className="mt-2 text-[10px] text-[#6e7681]">{c.reason?.framing}</div>
          </div>
          <div className="flex gap-1">
            <button title="Mark reviewed" className="btn" onClick={()=>status(c.id,"reviewed")}><Check size={12}/></button>
            <button title="Mark expected" className="btn" onClick={()=>status(c.id,"expected")}>Expected</button>
            <button title="Ignore" className="btn" onClick={()=>status(c.id,"ignored")}><X size={12}/></button>
          </div>
        </div>)}
        {(!q.data?.items || q.data.items.length === 0) && (
          <div className="p-6 text-center text-xs text-[#8b949e]">
            No behavioral changes found matching criteria.
          </div>
        )}
      </div>
    </Panel>}
  </Page>;
}

type GraphData={nodes:Array<{id:string;label:string;type:string}>;edges:Array<{source:string;target:string;requests:number;state:string;label:string}>;mode:string};
function UserGraphCanvas({graph,onPrincipal}:{graph:GraphData;onPrincipal:(p:string)=>void}){const ref=useRef<HTMLCanvasElement>(null);const positions=useMemo(()=>{const groups={caller:graph.nodes.filter(n=>n.type==="caller"),principal:graph.nodes.filter(n=>n.type==="principal"),target:graph.nodes.filter(n=>n.type==="target")};const map=new Map<string,{x:number;y:number}>();(["caller","principal","target"] as const).forEach((type,col)=>groups[type].forEach((node,i)=>map.set(node.id,{x:130+col*350,y:55+i*Math.max(42,520/Math.max(1,groups[type].length))})));return map},[graph]);useEffect(()=>{const c=ref.current;if(!c)return;const dpr=devicePixelRatio||1,r=c.getBoundingClientRect();c.width=r.width*dpr;c.height=r.height*dpr;const x=c.getContext("2d")!;x.scale(dpr,dpr);x.clearRect(0,0,r.width,r.height);for(const e of graph.edges){const a=positions.get(e.source),b=positions.get(e.target);if(!a||!b)continue;x.beginPath();x.moveTo(a.x,a.y);x.lineTo(b.x,b.y);x.strokeStyle=e.state==="changed"?"#f59e0b":"#30363d";x.lineWidth=Math.min(5,1+Math.sqrt(e.requests)/10);if(e.state==="changed")x.setLineDash([7,4]);x.stroke();x.setLineDash([])}for(const node of graph.nodes){const p=positions.get(node.id)!;x.beginPath();x.arc(p.x,p.y,18,0,Math.PI*2);x.fillStyle=node.type==="principal"?"#4f46e5":node.type==="caller"?"#0f766e":"#1d4ed8";x.fill();x.fillStyle="#e6edf3";x.font="11px Inter";x.textAlign="center";x.fillText(node.label.slice(0,24),p.x,p.y+34)}} ,[graph,positions]);return <canvas ref={ref} onClick={e=>{const r=e.currentTarget.getBoundingClientRect();const px=e.clientX-r.left,py=e.clientY-r.top;for(const node of graph.nodes.filter(n=>n.type==="principal")){const p=positions.get(node.id)!;if(Math.hypot(px-p.x,py-p.y)<24)onPrincipal(node.label)}}} className="h-[620px] w-full cursor-pointer"/>}
export function UserGraphPage(){const nav=useNavigate();const {filters}=useFilters();const params=new URLSearchParams(location.search);const [mode,setMode]=useState(params.get("principal")?"principal":"estate");const [principal,setPrincipal]=useState(params.get("principal")||"");const [service,setService]=useState("");const qs=queryString(filters,{principal:mode==="principal"&&principal?principal:undefined,service:mode==="service"&&service?service:undefined});const q=useQuery({queryKey:["user-graph",qs],queryFn:()=>api<GraphData>(`/api/v1/user-graph?${qs}`)});return <Page eyebrow="User Intelligence" title="Caller → Principal → Target" description="Credential-centered dependency evidence. Dashed amber edges are changed; labels and badges provide non-color evidence."><div className="card mb-4 flex flex-wrap gap-2 p-3"><select className="btn" value={mode} onChange={e=>setMode(e.target.value)}><option value="estate" className="bg-[#12151a]">Estate view</option><option value="principal" className="bg-[#12151a]">Principal centered</option><option value="service" className="bg-[#12151a]">Target service usage</option></select>{mode==="principal"&&<input className="rounded border border-white/10 bg-transparent px-3 text-xs" value={principal} onChange={e=>setPrincipal(e.target.value)} placeholder="Principal name"/>}{mode==="service"&&<input className="rounded border border-white/10 bg-transparent px-3 text-xs" value={service} onChange={e=>setService(e.target.value)} placeholder="Target service"/>}<span className="chip">Normal: solid · Changed: dashed + badge</span></div>{q.isLoading?<Loading/>:q.error?<ErrorState message={q.error.message}/>:<div className="grid gap-4 xl:grid-cols-[1fr_320px]"><Panel title="User dependency graph"><UserGraphCanvas graph={q.data!} onPrincipal={p=>nav(`/users/${encodeURIComponent(p)}`)}/></Panel><Panel title="Changed Edges" subtitle="Explicit labels accompany visual styling"><div className="max-h-[620px] overflow-auto p-3">{q.data?.edges.filter(e=>e.state!=="normal").map((e,i)=><div className="mb-2 rounded border border-amber-500/20 p-2 text-xs" key={i}><span className="rounded bg-amber-500/10 px-1 text-amber-400">CHANGED</span><div className="mt-2 font-mono">{e.source.split(":")[1]} → {e.target.split(":")[1]}</div><div className="text-[#8b949e]">{e.label} · {n(e.requests,0)} requests</div></div>)}</div></Panel></div>}</Page>}

export function UserAnalyticsPage(){const nav=useNavigate();const q=useQuery({queryKey:["user-analytics"],queryFn:()=>api<Record<string,UserItem[]>>(`/api/v1/user-analytics`)});if(q.isLoading)return <Page eyebrow="User Intelligence" title="User Analytics" description=""><Loading/></Page>;if(q.error)return <Page eyebrow="User Intelligence" title="User Analytics" description=""><ErrorState message={q.error.message}/></Page>;const sections:[[string,string,string],any[]][]=[[ ["most_active","Most Active Principals","Total observed credential use"],q.data?.most_active||[]],[ ["most_changed","Most Changed Principals","Explainable behavior score"],q.data?.most_changed||[]],[ ["shared_credentials","Shared Credential Usage","Accounts used by multiple caller services"],q.data?.shared_credentials||[]],[ ["source_diversity","Source Diversity","Accounts used from many source IPs"],q.data?.source_diversity||[]],[ ["most_targets","Broadest Service Access","Most target services"],q.data?.most_targets||[]],[ ["most_operations","Broadest API Usage","Most operations"],q.data?.most_operations||[]],[ ["newest","Newest Principals","Most recently first observed"],q.data?.newest||[]],[ ["dormant_reactivated","Recently Reactivated","Returned after dormancy"],q.data?.dormant_reactivated||[]]];return <Page eyebrow="User Intelligence" title="Account Behavior Analytics" description="Estate-wide identity patterns; shared usage is investigation context, not an automatic malicious classification."><div className="grid gap-4 lg:grid-cols-2">{sections.map(([meta,rows])=><Panel title={meta[1]} subtitle={meta[2]} key={meta[0]}><div className="divide-y divide-white/[.05]">{rows.slice(0,10).map((u:any,i:number)=><button onClick={()=>nav(`/users/${encodeURIComponent(u.principal_name)}`)} key={u.principal_name} className="flex w-full items-center justify-between p-3 text-left text-xs hover:bg-white/[.03]"><span><b className="font-mono text-indigo-300">{i+1}. {u.principal_name}</b><small className="ml-2 text-[#8b949e]">{u.principal_type||"shared usage"}</small></span><span className="font-mono text-[#c9d1d9]">{n(u.behavior_score??u.callers??u.unique_sources??u.unique_targets??u.unique_operations??u.total_requests,0)}</span></button>)}{!rows.length&&<div className="p-4 text-xs text-[#8b949e]">No qualifying principals.</div>}</div></Panel>)}</div></Page>}

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { ErrorState, Loading, Panel, n } from '../components';
import { useI18n } from '../i18n';
import { useFilters } from '../App';
import { formatEpisodeTime } from '../components/EpisodePrimitives';

type Node = { id:string; kind:string; label:string; environment:string; strength:number; observed_windows:number; tps:number|null; expected_tps:number|null; surprise:number|null };
type Edge = Omit<Node,'label'|'environment'> & { from:string; to:string };
type Graph = { status:string; nodes:Node[]; edges:Edge[]; through_ms?:number; total_edges?:number; shown_edges?:number; metrics:{nodes?:number;edges?:number;observed_windows?:number}; last_update?:{mode:string;windows_processed:number} };
const colors:Record<string,string>={service:'var(--entity-service)',api:'var(--entity-api)',credential:'var(--entity-user)',ip:'var(--text-muted)'};

export function BehaviorGraph() {
  const {t}=useI18n();const {filters}=useFilters();
  const [source,setSource]=useState('legacy_metrics');const [q,setQ]=useState('');const [focus,setFocus]=useState('');const [selected,setSelected]=useState('');
  const params=new URLSearchParams({source,q,node:focus,limit:'80'});
  const query=useQuery({queryKey:['behavior-graph',params.toString()],queryFn:()=>api<Graph>(`/api/v1/behavior/graph?${params}`),refetchInterval:60000});
  const graph=query.data;const nodes=graph?.nodes||[];const edges=graph?.edges||[];
  const kinds=['service','api','credential','ip'];const counts=[0,0,0,0];
  const positions=new Map(nodes.map(node=>{const column=Math.max(0,kinds.indexOf(node.kind));return [node.id,{x:column*250+15,y:50+counts[column]++*72}];}));
  const height=Math.max(220,Math.max(...counts)*72+70);const current=nodes.find(node=>node.id===selected);
  const role=(kind:string)=>({service:'Service',api:'API',credential:t('Observed credential','Credential quan sát'),ip:t('Observed IP','IP quan sát'),service_call:t('Service call','Lời gọi Service'),calls:t('Calls','Gọi'),owns:t('Owns API','Sở hữu API'),credential_on_call:t('Credential on call','Credential trong lời gọi'),peer_on_call:t('Peer on call','IP trong lời gọi')}[kind]||kind);
  return <>
    <div className="mb-3 flex flex-wrap gap-2"><select aria-label={t('Graph source','Nguồn đồ thị')} className="btn max-w-full" value={source} onChange={e=>{setSource(e.target.value);setFocus('');setSelected('');}}>{['legacy_metrics'].map(value=><option key={value} value={value}>{value}</option>)}</select><input aria-label={t('Search graph','Tìm trong đồ thị')} className="min-w-0 flex-1 border border-line-strong bg-surface-2 p-2 text-xs" placeholder={t('Service, API, credential, IP…','Service, API, credential, IP…')} value={q} onChange={e=>{setQ(e.target.value);setFocus('');}}/>{focus&&<button className="btn" onClick={()=>setFocus('')}>{t('Show all nodes','Hiện tất cả nút')}</button>}</div>
    {query.isLoading?<Loading/>:query.error?<ErrorState message={query.error.message}/>:<>
      <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted"><span>{graph?.metrics.nodes||0} {t('nodes','nút')} · {graph?.metrics.edges||0} {t('edges','cạnh')} · {graph?.metrics.observed_windows||0} {t('learned windows','cửa sổ đã học')}</span><span>{t('Learned through','Đã học đến')}: {graph?.through_ms?formatEpisodeTime(graph.through_ms,true,filters.timezone):'—'}</span><span>{t('Showing','Đang hiển thị')} {edges.length} / {graph?.total_edges||0} {t('matching edges','cạnh phù hợp')}</span></div>
      <Panel title={t('Online learned graph','Đồ thị học trực tuyến')} subtitle={t('Edge width shows decayed observation strength. Select a node to inspect its learned traffic. Dashed edges attach credential and IP evidence.', 'Độ dày cạnh thể hiện độ mạnh quan sát đã suy giảm theo thời gian. Chọn nút để xem lưu lượng đã học. Cạnh nét đứt gắn bằng chứng credential và IP.')}>
        {!nodes.length?<p className="p-6 text-sm text-muted">{t('No matching graph yet. Check source coverage or clear the search.','Chưa có đồ thị phù hợp. Kiểm tra độ phủ nguồn hoặc xóa tìm kiếm.')}</p>:<div className="max-h-[500px] overflow-auto"><svg width="1000" height={height} role="group" aria-label={t('Learned nodes and edges','Nút và cạnh đã học')}>
          {kinds.map((kind,i)=><text key={kind} x={i*250+20} y="25" fill={colors[kind]} fontSize="12">{role(kind)}</text>)}
          {edges.map(edge=>{const a=positions.get(edge.from)!;const b=positions.get(edge.to)!;const active=!selected||edge.from===selected||edge.to===selected;return <path key={edge.id} d={`M${a.x+110} ${a.y+28} C${a.x+240} ${a.y+28},${b.x-35} ${b.y+28},${b.x+110} ${b.y+28}`} fill="none" stroke={(edge.kind==='calls'||edge.kind==='service_call')?'var(--accent)':edge.kind==='credential_on_call'?'var(--entity-user)':'var(--text-muted)'} strokeWidth={1+edge.strength*4} strokeOpacity={active?.65:.12} strokeDasharray={edge.kind.endsWith('_on_call')?'4 4':undefined}><title>{role(edge.kind)} · {t('Strength','Độ mạnh')} {n(edge.strength*100,1)}% · {edge.observed_windows} {t('windows','cửa sổ')}</title></path>;})}
          {nodes.map(node=>{const p=positions.get(node.id)!;return <g key={node.id} role="button" tabIndex={0} aria-label={`${role(node.kind)}: ${node.label}`} aria-pressed={selected===node.id} onClick={()=>setSelected(node.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(node.id);}}} className="cursor-pointer focus-visible:outline focus-visible:outline-accent"><title>{node.label} · {node.environment}</title><rect x={p.x} y={p.y} width="220" height="56" rx="2" fill="var(--surface)" stroke={selected===node.id?colors[node.kind]:'var(--border-line)'}/><text x={p.x+10} y={p.y+22} fill={colors[node.kind]} fontSize="11">{node.label.length>29?node.label.slice(0,28)+'…':node.label}</text><text x={p.x+10} y={p.y+42} fill="var(--text-muted)" fontSize="10">{n(node.strength*100,1)}% · {node.tps==null?'TPS —':`${n(node.tps,4)} TPS`}</text></g>;})}
        </svg></div>}
        {current&&<div className="space-y-2 border-t border-line-strong p-4 text-xs text-muted"><p className="break-all" style={{color:colors[current.kind]}}>{role(current.kind)}: {current.label} · {current.environment}</p><p>{t('Observation strength','Độ mạnh quan sát')}: {n(current.strength*100,1)}% · {current.observed_windows} {t('observed windows','cửa sổ quan sát')}</p><p>TPS: {current.tps==null?'—':n(current.tps,4)} · {t('Learned next-window TPS','TPS đã học cho cửa sổ tiếp')}: {current.expected_tps==null?'—':n(current.expected_tps,4)} · {t('TPS surprise','Mức bất ngờ TPS')}: {current.surprise==null?'—':`${n(current.surprise*100,1)}%`}</p><button className="btn" onClick={()=>setFocus(current.id)}>{t('Focus neighborhood','Xem quan hệ lân cận')}</button></div>}
      </Panel>
      <p className="mt-3 text-xs leading-6 text-muted">{t('Every observed five-minute window reinforces each node and edge once. Support has a seven-day half-life; TPS uses an exponentially weighted mean and variance. Surprise is scored before updating. Missing windows are unknown. Strength and surprise are scores, not probabilities of safety or attack.', 'Mỗi cửa sổ năm phút quan sát củng cố từng nút và cạnh một lần. Trọng số giảm một nửa sau bảy ngày; TPS dùng trung bình và phương sai có trọng số theo thời gian. Mức bất ngờ được tính trước khi cập nhật. Cửa sổ thiếu là chưa rõ. Độ mạnh và mức bất ngờ là điểm số, không phải xác suất an toàn hoặc tấn công.')}</p>
    </>}
  </>;
}

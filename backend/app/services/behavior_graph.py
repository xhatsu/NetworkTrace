"""Online graph reinforcement from completed event-time metric windows.

This is a learned statistical graph, not a neural network or a reinforcement-
learning agent. Scores express observation surprise, never authorization.
"""
from __future__ import annotations
import copy
import math
import statistics
from collections import defaultdict
from backend.app.services.learned_behavior import DAY, BUCKET, digest, UNKNOWN

ALGORITHM = 'online-behavior-graph-v4'
HALF_LIFE_MS = 7 * DAY
ALPHA = 0.05
MIN_RATE_SAMPLES = 12
MAX_NODES = 40000
MAX_EDGES = 50000
MAX_RELATIONS = 5000
# A sustained new level is accepted as the reference after this many recent
# eligible windows, most of them material surges (3 hours of observed windows).
LEVEL_SHIFT_WINDOWS = 36
LEVEL_SHIFT_FRACTION = 0.75


def decayed_support(state: dict | None, at: int) -> float:
    if not state:
        return 0.0
    return state['support'] * math.exp(-math.log(2) * max(0, at-state['last_seen'])/HALF_LIFE_MS)


def strength(support: float) -> float:
    return 1-math.exp(-max(0,support)/20)


def windows_from_days(days: list[dict]) -> dict[int,list[dict]]:
    windows=defaultdict(dict)
    for d in days:
        clean=set(d['clean_windows'])
        ips={i['address']:i for i in d.get('observed_ips',[])}
        for at,count in zip(d['active_windows'],d.get('window_counts',[])):
            windows[at][d['id']]={'id':d['id'],'source':d['source'],'environment':d['environment'],
                'caller':d['caller'],'principal':d['principal'],'target':d['target'],'operation':d['operation'],
                'requests':count,'eligible':at in clean,
                'ips':[ips[ip] for ip,observed in d.get('ip_windows',{}).items() if at in observed and ip in ips]}
    return {at:sorted(rows.values(),key=lambda r:r['id']) for at,rows in sorted(windows.items())}


def empty_state(source):
    return {'algorithm':ALGORITHM,'source':source,'nodes':{},'edges':{},'relations':{},
            'window_digests':{},'through_ms':0,'processed_windows':0,
            'settings':{'support_half_life_days':7,'tps_alpha':ALPHA,'minimum_rate_samples':MIN_RATE_SAMPLES,
                        'support_strength_scale':20,'max_nodes':MAX_NODES,'max_edges':MAX_EDGES}}


def node_id(source,environment,kind,value):
    return digest([source,environment,kind,value])


def topology(row):
    nodes={}
    def node(kind,label):
        if str(label).lower() in UNKNOWN:
            return None
        key=node_id(row['source'],row['environment'],kind,label)
        nodes[key]={'id':key,'kind':kind,'label':label,'environment':row['environment']}
        return key
    caller=node('service',row['caller'])
    target=node('service',row['target'])
    api=node('api',row['target']+' → '+row['operation']) if row['operation'].lower() not in UNKNOWN and row['target'].lower() not in UNKNOWN else None
    credential=node('credential',row['principal'])
    edges={}
    def edge(a,b,kind,scope=''):
        if a and b:
            key=digest([a,b,kind,scope])
            edges[key]={'id':key,'from':a,'to':b,'kind':kind,'relationship_id':scope}
    edge(caller,target,'service_call')
    edge(caller,api,'calls')
    edge(target,api,'owns')
    # Full relation ID in the association key prevents inventing cross-products.
    edge(credential,api,'credential_on_call',row['id'])
    for ip in row.get('ips',[]):
        peer=node('ip',ip['address'])
        if peer:nodes[peer].update(role=ip['role'],volume_known=False)
        edge(peer,api,'peer_on_call',row['id'])
    return nodes,edges


def reinforce(state,at,requests,metadata=None,eligible=True):
    before=copy.copy(state) if state else None
    if before:before['active_days']=list(before['active_days'])
    if state is None:
        state={'first_seen':at,'last_seen':at,'support':0.0,'observed_windows':0,
               'total_requests':0,'active_days':[],'rate_samples':0,'mean_tps':0.0,'variance_tps':0.0,
               'withheld_rate_windows':0}
    state.update(metadata or {})
    previous=decayed_support(before,at)
    state['support']=previous+1
    state['strength']=strength(state['support'])
    state['prior_strength']=strength(previous)
    state['last_seen']=at
    state['observed_windows']+=1
    state['total_requests']+=requests
    day=at//DAY
    if day not in state['active_days']:state['active_days'].append(day)
    rate=requests/300
    expected=before['mean_tps'] if before and before['rate_samples'] else None
    sigma=math.sqrt(max(0,before['variance_tps'])) if expected is not None else None
    ready=bool(before and before['rate_samples']>=MIN_RATE_SAMPLES and len(before['active_days'])>=3)
    scale=max(sigma or 0,(expected or 0)*0.2,1/300)
    z=max(0,(rate-(expected or 0))/scale) if expected is not None else 0
    material=bool(ready and expected is not None and rate>=expected*3 and rate-expected>=100/300 and z>=6)
    structural=1-strength(previous)
    state['last_score']={'at':at,'observed_tps':rate,'expected_tps':expected,'stddev_tps':sigma,
        'tps_ready':ready,'tps_z':z,'tps_surprise':1-math.exp(-z/6) if ready else None,
        'structural_surprise':structural,'new':before is None,'material_tps_surge':material,
        'prior_windows':before['observed_windows'] if before else 0,'level_shift':False}
    state['last_tps']=rate
    state['surge_streak']=(before.get('surge_streak',0)+1 if before and before['last_seen']==at-BUCKET else 1) if material else 0
    # Familiarity always reflects observations. A surprising or ineligible window
    # cannot train the traffic reference used to score that same event.
    # A persistent new level replaces the reference instead of being withheld forever.
    shifted=eligible and adapt_level(state,rate,material,at)
    if eligible and not material and not shifted:
        if not state['rate_samples']:
            state['mean_tps']=rate;state['variance_tps']=0.0
        else:
            delta=rate-state['mean_tps']
            # Bounded influence from isolated high-volume windows during warmup.
            if state['rate_samples']>=MIN_RATE_SAMPLES:
                delta=max(-3*scale,min(3*scale,delta))
            state['mean_tps']+=ALPHA*delta
            state['variance_tps']=(1-ALPHA)*(state['variance_tps']+ALPHA*delta*delta)
        state['rate_samples']+=1
    elif not shifted:state['withheld_rate_windows']+=1
    return state


def adapt_level(state,rate,material,at):
    """Accept a persistent new traffic level instead of withholding it forever.

    Only eligible windows count. The buffer exists only while recent material
    surges are present, so normal entities carry no extra state.
    """
    recent=(state.get('shift_buffer') or [])+[[rate,material]]
    recent=recent[-LEVEL_SHIFT_WINDOWS:]
    surges=sum(1 for _,m in recent if m)
    if not surges:
        state.pop('shift_buffer',None);return False
    if len(recent)<LEVEL_SHIFT_WINDOWS or surges<LEVEL_SHIFT_FRACTION*LEVEL_SHIFT_WINDOWS:
        state['shift_buffer']=recent;return False
    rates=[r for r,_ in recent]
    level=statistics.median(rates)
    spread=1.4826*statistics.median(abs(r-level) for r in rates)
    state['level_shift']={'at':at,'from_tps':state['mean_tps'],'to_tps':level,'windows':len(rates)}
    state['level_shifts']=state.get('level_shifts',0)+1
    state['mean_tps']=level;state['variance_tps']=spread*spread
    state['rate_samples']+=1
    state['surge_streak']=0
    state['last_score']['level_shift']=True
    state.pop('shift_buffer',None)
    return True


def advance_graph(previous: dict | None, days: list[dict], source: str) -> dict:
    windows=windows_from_days(days)
    hashes={str(at):digest(rows) for at,rows in windows.items()}
    compatible=previous and previous.get('algorithm')==ALGORITHM and previous.get('source')==source
    old_hashes=(previous or {}).get('window_digests',{})
    # Corrections, late windows, retention eviction and quality changes trigger a
    # deterministic replay. Appending unchanged windows never reinforces twice.
    replay=not compatible or any(hashes.get(k)!=v for k,v in old_hashes.items())
    if compatible and not replay:
        replay=any(int(k)<previous['through_ms'] and k not in old_hashes for k in hashes)
    state=empty_state(source) if replay else copy.deepcopy(previous)
    new_windows=0
    for at,rows in windows.items():
        if not replay and str(at) in old_hashes:continue
        node_totals=defaultdict(int);edge_totals=defaultdict(int)
        node_metadata={};edge_metadata={};node_eligible={};edge_eligible={}
        for row in rows:
            rid=row['id'];nodes,edges=topology(row)
            old=state['relations'].get(rid)
            credential=state['nodes'].get(node_id(source,row['environment'],'credential',row['principal']))
            emergence=old.get('emergence') if old else {'at':at,'known_credential_context':bool(credential and decayed_support(credential,at)>=12 and len(credential['active_days'])>=3)}
            metadata={k:row[k] for k in ('id','source','environment','caller','principal','target','operation')}
            state['relations'][rid]=reinforce(old,at,row['requests'],metadata,row['eligible'])
            state['relations'][rid]['emergence']=emergence
            for key,n in nodes.items():
                node_totals[key]+=0 if n['kind']=='ip' else row['requests'];node_metadata[key]=n
                node_eligible[key]=node_eligible.get(key,True) and row['eligible'] and n['kind']!='ip'
            for key,e in edges.items():
                edge_totals[key]+=0 if e['kind']=='peer_on_call' else row['requests'];edge_metadata[key]=e
                edge_eligible[key]=edge_eligible.get(key,True) and row['eligible'] and e['kind']!='peer_on_call'
        for key,count in node_totals.items():state['nodes'][key]=reinforce(state['nodes'].get(key),at,count,node_metadata[key],node_eligible[key])
        for key,count in edge_totals.items():state['edges'][key]=reinforce(state['edges'].get(key),at,count,edge_metadata[key],edge_eligible[key])
        if len(state['nodes'])>MAX_NODES or len(state['edges'])>MAX_EDGES or len(state['relations'])>MAX_RELATIONS:
            raise ValueError('behavior online graph capacity exceeded')
        state['processed_windows']+=1;new_windows+=1;state['through_ms']=at+BUCKET
    state['window_digests']=hashes
    state['version']=digest([ALGORITHM,source,hashes])
    state['last_update']={'mode':'replay' if replay else 'incremental','windows_processed':new_windows}
    state['metrics']={'nodes':len(state['nodes']),'edges':len(state['edges']),'relationships':len(state['relations']),
                      'observed_windows':len(hashes),'new_windows':new_windows}
    return state


def level_shift_starts(graph):
    """Relationship ID -> window where its accepted new traffic level began."""
    return {rid:r['level_shift']['at']-(r['level_shift']['windows']-1)*BUCKET
            for rid,r in graph['relations'].items() if r.get('level_shift')}


def relationship_view(graph,profile,as_of=None):
    relation=graph['relations'].get(profile['id'])
    if not relation:return None
    at=as_of if as_of is not None else graph['through_ms']-BUCKET
    return {'algorithm':ALGORITHM,'model_version':graph['version'],
            'strength':strength(decayed_support(relation,at)),
            'effective_windows':decayed_support(relation,at),'observed_windows':relation['observed_windows'],
            'expected_tps':relation['mean_tps'],'rate_samples':relation['rate_samples'],
            'withheld_rate_windows':relation['withheld_rate_windows'],
            'level_shift':relation.get('level_shift'),
            'last_score':relation['last_score'],'surge_streak':relation['surge_streak'],
            'emergence':relation['emergence'],
            'through_ms':graph['through_ms']}

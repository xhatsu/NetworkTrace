"""Project the durable learned graph for the existing interactive topology canvas.

Never joins sources/environments or invents missing callers/latency/error data.
"""
from __future__ import annotations
from collections import defaultdict
import time
from .behavior_graph import ALGORITHM, node_id, decayed_support, strength
from .learned_behavior import DAY, BUCKET, digest

MAX_SERVICES = 500
MAX_EDGES = 2000


def learned_metrics(value, now):
    score=value['last_score']
    return {'tps':value['last_tps'], 'request_count':value['total_requests'],
            'first_seen_ms':value['first_seen'], 'last_seen_ms':value['last_seen'],
            'learning':{'strength':strength(decayed_support(value,now)),
                'observed_windows':value['observed_windows'],'effective_windows':decayed_support(value,now),
                'expected_tps':value['mean_tps'] if value['rate_samples'] else None,
                'previous_expected_tps':score['expected_tps'],
                'surprise':score['tps_surprise'],'ready':score['tps_ready'],
                'rate_samples':value['rate_samples'],'withheld_windows':value['withheld_rate_windows'],
                'surge_streak':value['surge_streak']},
            'change':{'status':'changed' if value['surge_streak']>=3 else 'learning' if not score['tps_ready'] else 'observed'}}


def project_topology(graph, environment='', now=None):
    now=now if now is not None else int(time.time()*1000)
    environments=sorted({n['environment'] for n in (graph or {}).get('nodes',{}).values()})
    env=environment or ('unknown' if 'unknown' in environments else next(iter(environments),''))
    result={'status':'learning','backend':'learned_graph','source':(graph or {}).get('source'),
            'environment':env,'environments':environments,'nodes':[],'edges':[],'entities':[],
            'relations':[],'ip_associations':[],'version':(graph or {}).get('version'),
            'through_ms':(graph or {}).get('through_ms'),
            'limits':{'services':MAX_SERVICES,'edges':MAX_EDGES},'truncated':False,
            'total_services':0,'total_edges':0,'total_relations':0}
    if not graph or graph.get('algorithm')!=ALGORITHM:return result
    result['status']='active'
    model_nodes={k:v for k,v in graph['nodes'].items() if v['environment']==env}
    service_nodes=sorted((n for n in model_nodes.values() if n['kind']=='service'),key=lambda n:(-n['last_seen'],-n['support'],n['id']))
    result['total_services']=len(service_nodes)
    service_ids={n['id'] for n in service_nodes[:MAX_SERVICES]}
    source=graph['source']
    relations=[]; used_ids=set(service_ids);api_context={}
    for relation in graph['relations'].values():
        if relation['environment']!=env:continue
        caller=node_id(source,env,'service',relation['caller']);target=node_id(source,env,'service',relation['target'])
        if target not in service_ids or (caller in model_nodes and caller not in service_ids):continue
        api=node_id(source,env,'api',relation['target']+' → '+relation['operation'])
        principal=node_id(source,env,'credential',relation['principal'])
        pair=digest([caller,target,'service_call',''])
        relations.append({'id':relation['id'],'caller_id':caller if caller in model_nodes else None,
            'target_id':target,'api_id':api if api in model_nodes else None,
            'principal_id':principal if principal in model_nodes else None,
            'edge_id':pair if pair in graph['edges'] else None})
        used_ids.update([api,principal]);api_context[api]=(relation['target'],relation['operation'])
    result['total_relations']=sum(r['environment']==env for r in graph['relations'].values())
    pairs=[e for e in graph['edges'].values() if e['kind']=='service_call' and e['from'] in service_ids and e['to'] in service_ids]
    pairs.sort(key=lambda e:(-e['last_seen'],-e['support'],e['id']))
    result['total_edges']=len(pairs)
    for edge in pairs[:MAX_EDGES]:
        result['edges'].append({'id':edge['id'],'source':edge['from'],'target':edge['to'],
            'source_name':model_nodes[edge['from']]['label'],'target_name':model_nodes[edge['to']]['label'],
            'metrics':learned_metrics(edge,now),'direct':True,'inferred':False,
            'active_in_window':now-edge['last_seen']<=30*60_000})
    visible_edges={e['id'] for e in result['edges']}
    for relation in relations:
        if relation['edge_id'] not in visible_edges:relation['edge_id']=None
    result['relations']=relations
    edges_by_node=defaultdict(set);apis_by_service=defaultdict(set)
    for relation in relations:
        if relation['api_id']:apis_by_service[relation['target_id']].add(relation['api_id'])
        if relation['edge_id']:
            for key in (relation['caller_id'],relation['target_id'],relation['api_id'],relation['principal_id']):
                if key:edges_by_node[key].add(relation['edge_id'])
    for key in sorted(used_ids):
        node=model_nodes.get(key)
        if not node or node['kind']=='ip':continue
        kind={'credential':'principal'}.get(node['kind'],node['kind'])
        entity={'id':key,'name':node['label'],'type':kind,'metrics':learned_metrics(node,now),
                'active_in_window':now-node['last_seen']<=30*60_000,
                'edge_ids':sorted(edges_by_node[key])}
        if kind=='api':entity.update(service=api_context[key][0],api=api_context[key][1],name=api_context[key][1])
        if kind=='service':
            entity['service']=node['label']
            entity['metrics']['api_count']=len(apis_by_service[key])
            result['nodes'].append(entity)
        if kind=='principal':entity['principal']=node['label']
        result['entities'].append(entity)
    relation_ids={r['id'] for r in relations}
    for edge in graph['edges'].values():
        if edge['kind']!='peer_on_call' or edge.get('relationship_id') not in relation_ids:continue
        ip=model_nodes.get(edge['from'])
        if ip:result['ip_associations'].append({'relationship_id':edge['relationship_id'],
            'source_ip':ip['label'],'role':ip.get('role','unverified_peer'),
            'first_seen_ms':edge['first_seen'],'last_seen_ms':edge['last_seen'],
            'observed_windows':edge['observed_windows'],'strength':strength(decayed_support(edge,now))})
    result['truncated']=len(service_nodes)>MAX_SERVICES or len(pairs)>MAX_EDGES or len(relations)<result['total_relations']
    return result


def topology_series(graph, days, object_id, environment):
    """Last observed day, original five-minute samples; gaps stay absent."""
    entity=graph['nodes'].get(object_id) or graph['edges'].get(object_id)
    if not entity:return []
    last=entity['last_seen']; start=last//DAY*DAY
    matching=set()
    for rid,r in graph['relations'].items():
        if r['environment']!=environment:continue
        args=(graph['source'],environment)
        caller=node_id(*args,'service',r['caller']);target=node_id(*args,'service',r['target'])
        identities={caller,target,node_id(*args,'api',r['target']+' → '+r['operation']),node_id(*args,'credential',r['principal']),digest([caller,target,'service_call',''])}
        if object_id in identities:matching.add(rid)
    totals=defaultdict(int)
    for day in days:
        if day['id'] not in matching or day['day']!=start:continue
        for at,count in zip(day['active_windows'],day['window_counts']):totals[at]+=count
    return [{'timestamp_ms':at,'tps':count/(BUCKET/1000)} for at,count in sorted(totals.items())]

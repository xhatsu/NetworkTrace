"""Separate shadow workspace. Never mutates Changes, alerts, or access controls."""
from __future__ import annotations
import fcntl
import hmac
import time
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.config import settings
from backend.app.repositories.behavior_repository import BehaviorRepository, SOURCES, stamp
from backend.app.services.learned_behavior import active_contract

router=APIRouter(prefix='/api/v1/behavior',tags=['learned-behavior'])


def repository():
    return BehaviorRepository()


def authorize(x_api_key: str | None = Header(default=None)):
    if settings.api_key and (not x_api_key or not hmac.compare_digest(x_api_key,settings.api_key)):
        raise HTTPException(401,'Valid operator API key required')


class ContractDecision(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    state: Literal['approved','temporary','prohibited','unreviewed']
    reason: str=Field(min_length=3,max_length=1000)
    reviewer: str=Field(min_length=1,max_length=120)
    expires_at_ms: int=Field(default=0,ge=0)
    expected_event_id: str=Field(default='',max_length=64)

    @model_validator(mode='after')
    def expiry(self):
        now=int(time.time()*1000)
        if self.state=='temporary' and not now<self.expires_at_ms<=now+90*86400000:
            raise ValueError('Temporary approval requires a future expiry within 90 days')
        if self.state!='temporary' and self.expires_at_ms:
            raise ValueError('Only temporary approval accepts expiry')
        return self


@router.get('/overview')
def overview(repo=Depends(repository)):
    profiles=repo.items('profiles'); deviations=repo.items('deviations')
    return {'mode':'shadow','enabled':settings.behavior_learning_enabled,'coverage':repo.coverage(),
            'profiles':len(profiles),'established':sum(p['familiarity']=='established' for p in profiles),
            'unreviewed':sum(d['status']=='unreviewed' for d in deviations),
            'approved':sum(p['contract']['state'] in {'approved','temporary'} for p in profiles),
            'limits':{'profiles_per_source':5000,'relationship_days_per_source':100000,'late_refresh_hours':48,
                      'observations_retention_days':30,'daily_retention_days':90},
            'reviewer_identity':'operator_supplied','authentication_required':bool(settings.api_key)}


@router.get('/topology')
def learned_topology(source: Literal['legacy_metrics','elasticsearch','clickhouse']='legacy_metrics',
                     environment: str=Query('',max_length=200),repo=Depends(repository)):
    from backend.app.services.behavior_topology import project_topology
    result=project_topology(repo.graph_state(source),environment)
    result['source']=source
    return result


@router.get('/topology/detail')
def learned_topology_detail(object_id: str=Query(...,min_length=64,max_length=64),
                           source: Literal['legacy_metrics','elasticsearch','clickhouse']='legacy_metrics',
                           environment: str=Query('',max_length=200),repo=Depends(repository)):
    from backend.app.services.behavior_topology import project_topology, topology_series
    graph=repo.graph_state(source); view=project_topology(graph,environment)
    entity=next((n for n in view['entities'] if n['id']==object_id),None)
    edge=next((e for e in view['edges'] if e['id']==object_id),None)
    if not entity and not edge:raise HTTPException(404,'Learned topology object not found in this scope')
    return {'entity':entity,'metrics':(entity or edge)['metrics'],
            'series':topology_series(graph,repo.days(source),object_id,view['environment']),
            'backend':'learned_graph','version':graph['version']}


@router.get('/graph')
def graph_view(source: Literal['legacy_metrics','elasticsearch','clickhouse']='legacy_metrics',
               q: str=Query('',max_length=200), node: str=Query('',max_length=64),
               limit: int=Query(150,ge=1,le=300),repo=Depends(repository)):
    from backend.app.services.behavior_graph import decayed_support, strength
    graph=repo.graph_state(source)
    if not graph:
        return {'status':'learning','source':source,'nodes':[],'edges':[],'metrics':{}}
    now=int(time.time()*1000)
    nodes=graph['nodes'];query=q.strip().casefold()
    selected={key for key,value in nodes.items() if (not query or query in value['label'].casefold()) and (not node or key==node)}
    edges=[edge for edge in graph['edges'].values() if edge['from'] in selected or edge['to'] in selected]
    edges.sort(key=lambda e:(-e['last_seen'],-e['last_score'].get('tps_z',0),e['id']))
    total=len(edges);edges=edges[:limit]
    visible={key for e in edges for key in (e['from'],e['to'])}
    def view(value):
        volume_known=value.get('volume_known',True) and value.get('kind')!='peer_on_call'
        return {k:value[k] for k in ('id','kind','label','from','to','environment','role','first_seen','last_seen','observed_windows') if k in value} | {
          'strength':strength(decayed_support(value,now)), 'effective_windows':decayed_support(value,now),
          'tps':value['last_tps'] if volume_known else None,
          'expected_tps':value['mean_tps'] if volume_known and value['rate_samples'] else None,
          'surprise':value['last_score']['tps_surprise'] if volume_known else None}
    return {'status':'active','source':source,'version':graph['version'],'algorithm':graph['algorithm'],
            'through_ms':graph['through_ms'],'last_update':graph['last_update'],
            'settings':graph['settings'],'metrics':graph['metrics'],
            'nodes':[view(nodes[key]) for key in sorted(visible)],'edges':[view(e) for e in edges],
            'total_edges':total,'shown_edges':len(edges)}


@router.get('/profiles')
@router.get('/deviations')
def collection(request: Request,
    source: Literal['legacy_metrics','elasticsearch','clickhouse'] | None=None,
    q: str=Query('',max_length=200), environment: str=Query('',max_length=200),
    state: str=Query('',max_length=40), offset: int=Query(0,ge=0,le=15000),
    limit: int=Query(25,ge=1,le=100), repo=Depends(repository)):
    kind=request.url.path.rsplit('/',1)[-1]
    items=repo.items(kind,source)
    query=q.casefold().strip()
    items=[i for i in items if (not environment or i['environment']==environment)
           and (not state or state in {i['familiarity'],i['contract']['state'],i.get('kind'),i.get('status')})
           and (not query or query in ' '.join(str(i[k]) for k in ('caller','principal','target','operation','environment')).casefold())]
    items.sort(key=lambda i:(i.get('status')!='unreviewed',-i['last_seen'],i['id']))
    return {'items':items[offset:offset+limit],'total':len(items),'offset':offset,'limit':limit}


@router.get('/contracts')
def contracts(offset: int=Query(0,ge=0,le=10000),limit: int=Query(25,ge=1,le=100),repo=Depends(repository)):
    events=repo.contracts()
    return {'items':events[offset:offset+limit],'total':len(events)}


@router.get('/profiles/{relationship_id}')
def profile(relationship_id: str,repo=Depends(repository)):
    item=repo.detail(relationship_id)
    if not item:
        raise HTTPException(404,'Behavior profile not found')
    events=repo.contracts(relationship_id)
    # Scoped search remains useful when individual retained examples expire.
    query=urlencode({'service':item['target'],'principal':item['principal'],
                     'start':item['first_seen'],'end':item['last_seen']+300000})
    return {**item,'series':repo.series(relationship_id),'contracts':events,
            'trace_search_url':'/traces?'+query,
            'evidence_expired':item['last_seen']<int(time.time()*1000)-(86400000 if item['source']=='clickhouse' else 7*86400000)}


@router.get('/deviations/{deviation_id}')
def deviation(deviation_id: str,repo=Depends(repository)):
    item=next((d for d in repo.items('deviations') if d['id']==deviation_id),None)
    if not item:
        raise HTTPException(404,'Behavior deviation not found')
    item={**item,'semantic_assessment':{'status':'not_evaluated'}}
    try:
        from backend.app.services.behavior_worker import semantic_episode
        from backend.app.repositories.semantic_assessment_repository import SemanticAssessmentRepository, assessment_from_row
        episode=semantic_episode(item)
        assessment=SemanticAssessmentRepository().get_latest(episode['episode_key'],episode['episode_version'])
        if assessment:
            item['semantic_assessment']=assessment_from_row(assessment).model_dump()
        else:
            previous=SemanticAssessmentRepository().get_latest_many([episode['episode_key']])
            if previous and previous[0]['status']=='succeeded':
                item['semantic_assessment']={**assessment_from_row(previous[0]).model_dump(),'status':'stale'}
    except Exception:
        item['semantic_assessment']={'status':'not_evaluated'}
    return item


@router.post('/profiles/{relationship_id}/contracts',dependencies=[Depends(authorize)])
def decide(relationship_id: str,body: ContractDecision,repo=Depends(repository)):
    if not repo.detail(relationship_id):
        raise HTTPException(404,'Behavior profile not found')
    lock_path=Path(settings.data_dir)/'behavior-contracts.lock'
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        events=repo.contracts(relationship_id)
        latest=max(events,key=lambda e:(e['created_at'],e['event_id'])) if events else None
        if body.expected_event_id!=(latest['event_id'] if latest else ''):
            raise HTTPException(409,'Contract changed. Reload before reviewing.')
        now=int(time.time()*1000)
        event={'event_id':uuid.uuid4().hex,'relationship_id':relationship_id,'state':body.state,
               'reason':body.reason,'reviewer':body.reviewer,'effective_at_ms':now,
               'expires_at_ms':body.expires_at_ms,'previous_event_id':body.expected_event_id,'created_at':stamp()}
        repo.insert('behavior_contracts',[event])
    return event

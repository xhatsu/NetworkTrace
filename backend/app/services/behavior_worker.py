"""Single-owner, bounded, shadow-only behavior materialization."""
from __future__ import annotations
import asyncio
import fcntl
import logging
import time
import uuid
from pathlib import Path

from backend.config import settings
from backend.app.repositories.behavior_repository import BehaviorRepository, SOURCES
from backend.app.services.learned_behavior import DAY, BUCKET, summarize_day, build_profiles, digest
from backend.app.services.behavior_sources import sql_day, apply_quality, coverage


def semantic_episode(item):
    """Names, IPs and request payloads never enter the Jev input."""
    learned=item.get('graph_learning') or {}
    baseline=learned.get('last_score',{}).get('expected_tps') if item['kind']=='graph_tps_shift' else item.get('tps',{}).get('baseline')
    return {'episode_key':'behavior:'+item['id'], 'episode_version':digest([item['version'],item['prior_profile_version'],item['observed_contract']]),
            'state':'watch', 'status':'open', 'subject':{'type':'service'},
            'signal_count':1, 'signals':[{'id':item['id'],'type':item['kind']}],
            'highlights':[{'label':'TPS','before':baseline,'after':item.get('tps',{}).get('latest')}] if item['kind'] in {'traffic_surge','graph_tps_shift'} else [], 'abnormality':{'confidence':'limited' if item['quality']=='limited' else 'observed',
             'gates':[{'type':item['kind'],'baseline_ready':item['baseline_ready'],
                       'persistent':item['persistent'],'material_impact':False,'level':'watch'}]}}


def run_source(repo, source, now):
    if source != 'legacy_metrics':
        raise ValueError('behavior learning accepts metric_buckets only')
    state=repo.state(source)
    complete_end=(now//BUCKET-1)*BUCKET  # allow one full bucket for ingestion lag
    today=complete_end//DAY*DAY
    pending=state.get('pending')
    if not pending:
        if state.get('mode')=='live' and state.get('through_ms')==complete_end and state.get('graph_version'):
            return {'status':'current','through_ms':complete_end}
        retention=30
        earliest=(now-retention*DAY+DAY-1)//DAY*DAY
        if source=='legacy_metrics' and not state.get('next_day'):
            existing=repo.query('SELECT min(bucket_start)*1000 AS first FROM metric_buckets FINAL WHERE bucket_size=300')
            if existing and existing[0]['first']:
                earliest=max(earliest,int(existing[0]['first'])//DAY*DAY)
        day=max(earliest,int(state.get('next_day',earliest)))
        if day>=today:
            # Refresh yesterday periodically for late arrivals, otherwise current day.
            refresh=int(state.get('refresh',0))+1
            state['refresh']=refresh
            day=today-DAY if refresh%6==0 else today
        pending={'day':day,'end':min(day+DAY,complete_end),'generation':uuid.uuid4().hex,'after':None,'pages':0}
        state['pending']=pending
        repo.save_state(source,state)
    day,end,generation=pending['day'],pending['end'],pending['generation']
    if end<=day:
        return {'status':'waiting'}
    # legacy_metrics is the worker-owned metric_buckets source. Missing or late
    # buckets are quality evidence; never fall back to raw spans or Elasticsearch.
    rows=sql_day(repo,source,day,end)
    rows=apply_quality(repo,rows,day,end)
    # Replaces staged raw-quality rows before visibility marker is committed.
    repo.stage(source,day,generation,rows)
    repo.commit_day(source,day,generation,summarize_day(rows,include_anonymous=True),coverage(rows,end))
    next_state={**state,'pending':None,'next_day':min(today,day+DAY),'through_ms':end,
                'mode':'live' if end>=today else 'backfill','last_success_ms':now}
    days=repo.days(source)
    profiles,deviations=build_profiles(days,repo.contracts(),now)
    from .behavior_graph import advance_graph, relationship_view
    graph=advance_graph(repo.graph_state(source),days,source)
    for item in profiles:
        item['graph_learning']=relationship_view(graph,item,now)
    for item in deviations:
        item['graph_learning']=relationship_view(graph,{'id':item['relationship_id']},now)
    known={(d['relationship_id'],d['kind']) for d in deviations}
    for profile in profiles:
        learned=profile['graph_learning']
        if not learned or now-profile['last_seen']>30*60_000:continue
        kind=None
        if learned['surge_streak']>=3 and (profile['id'],'traffic_surge') not in known:
            kind='graph_tps_shift'
        elif (learned['emergence']['known_credential_context'] and learned['observed_windows']>=3
              and learned['strength']<0.8 and (profile['id'],'access_expansion') not in known):
            kind='graph_edge_novelty'
        if kind:
            deviations.append({**profile,'relationship_id':profile['id'],
                'id':digest([profile['id'],kind,learned['emergence']['at']]),'kind':kind,
                'observed_contract':profile['contract'],'status':'unreviewed','persistent':True,
                'baseline_ready':True,'severity':'watch','reference_cutoff':learned['last_score']['at'],
                'novelty_scope':'online_graph','prohibited_windows':0})
    repo.save_graph(graph)
    next_state['graph_version']=graph['version']
    next_state['graph_metrics']=graph['metrics']
    repo.publish(source,profiles,deviations,next_state)
    return {'status':next_state['mode'],'profiles':len(profiles),'deviations':len(deviations),'through_ms':end}


def run_behavior_learning(db_path=None):
    if not settings.behavior_learning_enabled:
        return {'status':'disabled'}
    repo=BehaviorRepository(db_path)
    lock_path=Path(settings.data_dir)/'behavior-learning.lock'
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    results={}
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'another_local_owner'}
        started=time.monotonic()
        # Rotate priority so a slow remote source cannot starve the others.
        scheduler=repo.state('_scheduler')
        offset=int(scheduler.get('offset',0))%len(SOURCES)
        repo.save_state('_scheduler',{**scheduler,'offset':offset+1})
        if int(time.time())-int(scheduler.get('last_prune',0))>=3600:
            try:
                repo.prune_obsolete_generations()
                scheduler['last_prune']=int(time.time())
            except Exception:
                logging.warning('Behavior obsolete-generation cleanup unavailable')
            repo.save_state('_scheduler',{**scheduler,'offset':offset+1})
        for source in SOURCES[offset:]+SOURCES[:offset]:
            if time.monotonic()-started>settings.behavior_budget_seconds:
                break
            try:
                results[source]=run_source(repo,source,int(time.time()*1000))
            except Exception as exc:
                logging.warning('Behavior shadow source %s unavailable (%s)',source,type(exc).__name__)
                state=repo.state(source)
                repo.save_state(source,{**state,'error':type(exc).__name__,'last_error_ms':int(time.time()*1000)})
                results[source]={'status':'unavailable'}
        if settings.semantic_assessment_enabled and time.monotonic()-started<settings.behavior_budget_seconds:
            try:
                from backend.app.services.semantic_provider import create_semantic_provider
                from backend.app.services.semantic_worker import SemanticAssessmentWorker
                from backend.app.repositories.semantic_assessment_repository import SemanticAssessmentRepository
                async def assess():
                    worker=SemanticAssessmentWorker(SemanticAssessmentRepository(db_path),create_semantic_provider(settings),
                        settings.semantic_model,batch_size=1,retry_seconds=settings.semantic_retry_seconds)
                    items=sorted(repo.items('deviations'),key=lambda d:d['last_seen'],reverse=True)[:100]
                    return await asyncio.wait_for(worker.run_once([semantic_episode(d) for d in items]),timeout=5)
                results['advisory']=asyncio.run(assess())
            except Exception:
                results['advisory']={'status':'unavailable'}
    return {'status':'shadow','sources':results}

"""Isolated learned-memory tests. No production database or provider calls."""
import copy
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.services.learned_behavior import DAY, BUCKET, relationship_id, summarize_day, build_profiles, active_contract
from backend.app.services.behavior_sources import normalize, es_query
from backend.app.api import behavior
from backend.app.services import behavior_worker

NOW = 1800000000000 // DAY * DAY


def observation(day=0, window=0, **extra):
    return normalize('elasticsearch',dict(environment='prod',caller='caller',principal='credential',target='target',
        operation='/read',bucket_ms=NOW+day*DAY+window*BUCKET,requests=100,observed_ips=[],**extra))


def history():
    rows=[]
    for day in range(-10,0):
        rows.extend(summarize_day([observation(day,w) for w in range(3)]))
    return rows


def test_relationship_scope_and_new_combination():
    a=observation(); b={**a,'environment':'test'}
    assert relationship_id(a)!=relationship_id(b)
    assert relationship_id(a)!=relationship_id({**a,'source':'legacy_metrics'})
    days=history()+summarize_day([{**observation(0,w),'operation':'/export'} for w in range(3)])
    profiles,deviations=build_profiles(days,[],NOW+DAY)
    assert len(profiles)==2 and len(deviations)==1
    d=deviations[0]
    assert d['kind']=='access_expansion' and d['prior_days']==10 and d['persistent']
    assert d['prior_requests']==3000 and d['graph_features']['new_api_for_credential']
    assert d['contract']['state']=='unreviewed'
    assert d['reference_windows']==0  # Cannot learn its own expansion as the reference.


def test_exact_windows_late_arrivals_and_retries():
    rows=[observation(0,2),observation(0,0),observation(0,1),observation(0,0)]
    summary=summarize_day(rows)[0]
    assert summary['requests']==300
    assert len(summary['active_windows'])==3
    assert summary['first_seen']==NOW and summary['last_seen']==NOW+2*BUCKET


def test_anonymous_and_unknown_environment():
    assert summarize_day([{**observation(),'principal':'-anonymous-'}])==[]
    legacy=normalize('legacy_metrics',{**observation(),'environment':None})
    assert legacy['environment']=='unknown'
    assert legacy['reference_eligible']  # volume reference is isolated to this source


def test_familiar_is_not_approved_and_no_zero_imputation():
    profiles,deviations=build_profiles(history(),[],NOW)
    assert profiles[0]['familiarity']=='established'
    assert profiles[0]['contract']['state']=='unreviewed'
    assert profiles[0]['median_active_window_requests']==100
    assert profiles[0]['mad_active_window_requests']==0
    assert not deviations


def test_expired_replacement_does_not_restore_old_approval():
    events=[dict(event_id='a',created_at=1,effective_at_ms=10,expires_at_ms=0,state='approved'),
            dict(event_id='b',created_at=2,effective_at_ms=20,expires_at_ms=30,state='temporary')]
    assert active_contract(events,15)['state']=='approved'
    assert active_contract(events,25)['state']=='temporary'
    assert active_contract(events,30)['state']=='unreviewed'


def test_prohibition_not_retroactive():
    days=summarize_day([observation(0,w) for w in range(3)])
    rid=days[0]['id']
    event=dict(event_id='a',relationship_id=rid,created_at=1,effective_at_ms=NOW+BUCKET,expires_at_ms=0,state='prohibited')
    _,deviations=build_profiles(days,[event],NOW+DAY)
    assert deviations[0]['kind']=='contract_violation'
    assert deviations[0]['prohibited_windows']==2
    assert deviations[0]['observed_contract']['state']=='unreviewed'
    event['effective_at_ms']=NOW+DAY
    assert build_profiles(days,[event],NOW+DAY)[1]==[]


def test_ip_is_attached_and_infrastructure_is_labeled(monkeypatch):
    from backend.app.services import behavior_sources
    monkeypatch.setattr(behavior_sources,'settings',SimpleNamespace(known_f5=('10.0.0.1',),known_lb=(),known_reverse_proxy=(),known_nat=()))
    row=normalize('elasticsearch',{**observation(),'observed_ips':['10.0.0.1','192.0.2.1']})
    assert row['observed_ips'][0]['role']=='infrastructure'
    assert row['observed_ips'][1]['role']=='unverified_peer'
    assert summarize_day([row])[0]['observed_ips']==row['observed_ips']


def test_es_preserves_environment_and_recorded_operation():
    q=es_query(1,2)
    sources=q['aggs']['buckets']['composite']['sources']
    assert sources[-1]['environment']['terms']['field']=='behavior.environment'
    assert sources[-2]['operation']['terms']['field']=='topology.api'
    assert 'peer.service' not in q['runtime_mappings']['topology.caller']['script']['source']
    assert q['aggs']['buckets']['aggs']['auth_success']['filter']=={'term':{'auth_result':'success'}}


class MemoryRepo:
    def __init__(self):
        self.profiles,self.deviations=build_profiles(history(),[],NOW)
        self.events=[]
    def items(self,kind,source=None):
        rows=copy.deepcopy(self.profiles if kind=='profiles' else self.deviations)
        for r in rows:r['contract']=active_contract(self.events,int(time.time()*1000))
        return rows
    def contracts(self,rid=None):return list(reversed(self.events))
    def detail(self,rid):return next((r for r in self.items('profiles') if r['id']==rid),None)
    def series(self,rid):return []
    def coverage(self):return []
    def days(self,source):return history()
    def insert(self,table,rows):self.events.extend(rows)
    def graph_state(self,source):
        from backend.app.services.behavior_graph import advance_graph
        return advance_graph(None,history(),source) if source=='elasticsearch' else None


@pytest.fixture
def client(tmp_path,monkeypatch):
    repo=MemoryRepo(); app=FastAPI();app.include_router(behavior.router)
    app.dependency_overrides[behavior.repository]=lambda:repo
    monkeypatch.setattr(behavior,'settings',SimpleNamespace(api_key='test-key',data_dir=tmp_path,behavior_learning_enabled=True))
    with TestClient(app) as c: yield c,repo


def test_api_pagination_filter_and_detail(client):
    c,repo=client
    assert c.get('/api/v1/behavior/overview').json()['mode']=='shadow'
    assert c.get('/api/v1/behavior/profiles?q=missing').json()['total']==0
    assert c.get('/api/v1/behavior/profiles?source=invalid').status_code==422
    assert c.get('/api/v1/behavior/profiles?limit=101').status_code==422
    assert c.get('/api/v1/behavior/profiles/missing').status_code==404
    data=c.get('/api/v1/behavior/profiles/'+repo.profiles[0]['id']).json()
    assert data['contracts']==[] and data['trace_search_url'].startswith('/traces?')


def test_graph_api_bounds_search_focus_and_empty(client):
    c,_=client
    assert c.get('/api/v1/behavior/graph?source=invalid').status_code==422
    assert c.get('/api/v1/behavior/graph?limit=301').status_code==422
    assert c.get('/api/v1/behavior/graph').json()['status']=='learning'
    graph=c.get('/api/v1/behavior/graph?source=elasticsearch&limit=1').json()
    assert graph['status']=='active' and len(graph['edges'])==1
    assert len(graph['nodes'])==2 and graph['total_edges']>1
    assert all(0<=node['strength']<=1 for node in graph['nodes'])
    focused=c.get('/api/v1/behavior/graph',params={'source':'elasticsearch','node':graph['nodes'][0]['id']}).json()
    assert all(graph['nodes'][0]['id'] in (e['from'],e['to']) for e in focused['edges'])
    assert not c.get('/api/v1/behavior/graph?source=elasticsearch&q=unmatched').json()['nodes']


def test_learned_topology_api_and_scoped_detail(client):
    c,_=client
    assert c.get('/api/v1/behavior/topology?source=invalid').status_code==422
    graph=c.get('/api/v1/behavior/topology?source=elasticsearch').json()
    assert graph['status']=='active' and len(graph['edges'])==1
    key=graph['nodes'][0]['id']
    detail=c.get('/api/v1/behavior/topology/detail',params={'source':'elasticsearch','object_id':key})
    assert detail.status_code==200 and detail.json()['series']
    assert c.get('/api/v1/behavior/topology/detail',params={'source':'elasticsearch','object_id':key,'environment':'other'}).status_code==404
    assert c.get('/api/v1/behavior/topology/detail?object_id=bad').status_code==422


def test_contract_auth_validation_conflict_and_history(client):
    c,repo=client; url='/api/v1/behavior/profiles/'+repo.profiles[0]['id']+'/contracts'
    body={'state':'approved','reason':'Reviewed request','reviewer':'operator'}
    assert c.post(url,json=body).status_code==401
    headers={'X-API-Key':'test-key'}
    first=c.post(url,json=body,headers=headers)
    assert first.status_code==200
    assert c.post(url,json=body,headers=headers).status_code==409
    body.update(state='temporary',expected_event_id=first.json()['event_id'],expires_at_ms=int(time.time()*1000)-1)
    assert c.post(url,json=body,headers=headers).status_code==422
    body['expires_at_ms']=int(time.time()*1000)+3600000
    assert c.post(url,json=body,headers=headers).status_code==200
    assert c.get('/api/v1/behavior/contracts').json()['total']==2


def test_partial_es_day_never_publishes(monkeypatch):
    class Repo:
        def __init__(self):self.value={};self.published=False
        def state(self,s):return self.value
        def save_state(self,s,state):self.value=state
        def stage(self,*args):pass
        def commit_day(self,*args):self.published=True
    repo=Repo()
    monkeypatch.setattr(behavior_worker,'es_page',lambda *args:([observation()],{'cursor':1}))
    monkeypatch.setattr(behavior_worker,'settings',SimpleNamespace(elasticsearch_url='http://example.test'))
    result=behavior_worker.run_source(repo,'elasticsearch',NOW)
    assert result['status']=='materializing' and not repo.published
    assert repo.value['pending']['pages']==2


def test_jev_input_excludes_entity_and_ip():
    from backend.app.services.semantic_worker import _assessment_input
    _,ds=build_profiles(history()+summarize_day([{**observation(),'operation':'/export'}]),[],NOW+DAY)
    payload=_assessment_input(behavior_worker.semantic_episode(ds[0])).model_dump_json()
    assert '/export' not in payload and 'credential"' not in payload and '192.0.2.1' not in payload


def test_tps_surge_is_persistent_material_and_does_not_train_itself():
    base=[]
    for day in range(-10,0):
        base.extend(summarize_day([observation(day,w) for w in range(4)]))
    current=summarize_day([{**observation(0,w),'requests':1000} for w in range(3)])
    profiles,deviations=build_profiles(base+current,[],NOW+3*BUCKET)
    rate=profiles[0]['tps']
    assert rate['baseline']==pytest.approx(100/300)
    assert rate['latest']==pytest.approx(1000/300)
    assert rate['persistent_surge']
    assert [d['kind'] for d in deviations]==['traffic_surge']
    assert rate['reference_cutoff']==NOW
    # Gaps cannot prove persistence.
    gap=summarize_day([{**observation(0,w),'requests':1000} for w in (0,2,4)])
    assert not build_profiles(base+gap,[],NOW+5*BUCKET)[0][0]['tps']['persistent_surge']


def test_tiny_rates_and_missing_windows_do_not_alert():
    base=[]
    for day in range(-10,0):
        base.extend(summarize_day([{**observation(day,w),'requests':1} for w in range(4)]))
    current=summarize_day([{**observation(0,w),'requests':10} for w in range(3)])
    p,ds=build_profiles(base+current,[],NOW+3*BUCKET)
    assert p[0]['tps']['baseline']==pytest.approx(1/300)
    assert not p[0]['tps']['persistent_surge']
    assert not ds


def test_raw_retention_refresh_preserves_expired_prefix(monkeypatch):
    class Repo:
        def __init__(self):self.saved=[]
        def state(self,s):return {'pending':{'day':NOW-DAY,'end':NOW,'generation':'new','after':None,'pages':0}}
        def committed_day(self,s,d):return [{**observation(-1,0),'source':'clickhouse'}]
        def save_state(self,*args):pass
        def stage(self,s,d,g,rows):self.saved=rows
        def commit_day(self,*args):pass
        def days(self,s):return []
        def contracts(self):return []
        def publish(self,*args):pass
        def graph_state(self,*args):return None
        def save_graph(self,*args):pass
    repo=Repo()
    monkeypatch.setattr(behavior_worker,'sql_day',lambda *args:[])
    monkeypatch.setattr(behavior_worker,'apply_quality',lambda repo,rows,*args:rows)
    behavior_worker.run_source(repo,'clickhouse',NOW+3600000)
    assert len(repo.saved)==1 and repo.saved[0]['bucket_ms']==NOW-DAY

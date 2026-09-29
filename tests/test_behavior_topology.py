import copy
import pytest
from backend.app.services.behavior_sources import normalize
from backend.app.services.learned_behavior import DAY,BUCKET,summarize_day
from backend.app.services.behavior_graph import advance_graph
from backend.app.services.behavior_topology import project_topology,topology_series

NOW=1800000000000//DAY*DAY


def observations(**overrides):
    return [normalize('elasticsearch',dict(environment='prod',caller='checkout',principal='robot',target='payments',operation='/charge',bucket_ms=NOW+w*BUCKET,requests=100,observed_ips=['192.0.2.1'],**overrides)) for w in range(3)]


def test_service_edge_reinforces_once_with_multiple_apis():
    rows=observations();rows += [{**row,'operation':'/export'} for row in rows]
    graph=advance_graph(None,summarize_day(rows),'elasticsearch')
    edge=next(e for e in graph['edges'].values() if e['kind']=='service_call')
    assert edge['observed_windows']==3 and edge['total_requests']==600
    assert edge['last_tps']==pytest.approx(200/300)
    view=project_topology(graph,'prod',NOW+3*BUCKET)
    assert len(view['nodes'])==2 and len(view['edges'])==1
    assert len(view['relations'])==2 and len(view['ip_associations'])==2
    assert all('p95_latency_ms' not in n['metrics'] and 'error_rate' not in n['metrics'] for n in view['nodes'])
    assert all(r['edge_id']==edge['id'] for r in view['relations'])
    for node in view['entities']:
        assert node['edge_ids']==[edge['id']]
    assert topology_series(graph,summarize_day(rows),edge['id'],'prod')==[{'timestamp_ms':NOW+w*BUCKET,'tps':200/300} for w in range(3)]


def test_unknown_caller_does_not_hide_api_or_create_a_service_edge():
    rows=[{**r,'caller':'unknown'} for r in observations()]
    graph=advance_graph(None,summarize_day(rows),'elasticsearch')
    view=project_topology(graph,'prod',NOW)
    assert len(view['nodes'])==1 and not view['edges']
    assert len(view['entities'])==3
    assert view['relations'][0]['caller_id'] is None
    assert view['relations'][0]['edge_id'] is None


def test_environments_never_merge_and_missing_environment_is_empty():
    rows=observations(); rows += [{**r,'environment':'staging'} for r in rows]
    graph=advance_graph(None,summarize_day(rows),'elasticsearch')
    prod=project_topology(graph,'prod',NOW); staging=project_topology(graph,'staging',NOW)
    assert prod['environments']==['prod','staging']
    assert not ({n['id'] for n in prod['nodes']}&{n['id'] for n in staging['nodes']})
    assert not project_topology(graph,'missing',NOW)['nodes']


def test_projection_limit_disclosed_and_no_dangling_edges(monkeypatch):
    from backend.app.services import behavior_topology
    graph=advance_graph(None,summarize_day(observations()),'elasticsearch')
    monkeypatch.setattr(behavior_topology,'MAX_SERVICES',1)
    view=project_topology(graph,'prod',NOW)
    assert view['truncated'] and view['total_services']==2 and len(view['nodes'])==1
    assert not view['edges']


def test_old_model_waits_for_replay_and_empty_model_is_honest():
    assert project_topology(None)['status']=='learning'
    graph=advance_graph(None,summarize_day(observations()),'elasticsearch')
    old=copy.deepcopy(graph);old['algorithm']='obsolete'
    assert project_topology(old)['status']=='learning'
    assert not project_topology(old)['nodes']


def test_tps_series_retains_gaps_and_fractional_values():
    rows=[{**r,'requests':3} for i,r in enumerate(observations()) if i!=1]
    days=summarize_day(rows);graph=advance_graph(None,days,'elasticsearch')
    view=project_topology(graph,'prod',NOW)
    samples=topology_series(graph,days,view['nodes'][0]['id'],'prod')
    assert [p['timestamp_ms'] for p in samples]==[NOW,NOW+2*BUCKET]
    assert all(p['tps']==0.01 for p in samples)


def test_anonymous_service_is_learned_without_credential_profiles_or_fake_callers():
    from backend.app.services.learned_behavior import build_profiles
    rows=[normalize('legacy_metrics',dict(principal='-anonymous-',target='navidrome',operation='/rest/ping',bucket_ms=NOW+i*BUCKET,requests=30)) for i in range(3)]
    days=summarize_day(rows,include_anonymous=True)
    graph=advance_graph(None,days,'legacy_metrics')
    view=project_topology(graph,'unknown',NOW+3*BUCKET)
    assert [n['name'] for n in view['nodes']]==['navidrome']
    assert view['nodes'][0]['metrics']['tps']==pytest.approx(0.1)
    assert view['nodes'][0]['metrics']['learning']['rate_samples']==3
    assert not view['edges']
    assert not any(n['type']=='principal' for n in view['entities'])
    assert build_profiles(days,[],NOW+DAY)==([],[])

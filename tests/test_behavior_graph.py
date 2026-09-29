"""Online learned-state invariants: score, then reinforce, once per window."""
import copy
import math
import pytest
from backend.app.services.behavior_graph import advance_graph, reinforce, decayed_support, HALF_LIFE_MS, windows_from_days
from backend.app.services.behavior_sources import normalize
from backend.app.services.learned_behavior import DAY,BUCKET,summarize_day

NOW=1800000000000//DAY*DAY


def day_rows(day=0, requests=100, operation='/read', windows=3):
    return summarize_day([normalize('elasticsearch',dict(environment='prod',caller='caller',principal='credential',
        target='target',operation=operation,bucket_ms=NOW+day*DAY+i*BUCKET,requests=requests,
        observed_ips=['192.0.2.1'] if i==0 else [])) for i in range(windows)])


def test_window_updates_reinforce_once_and_idempotently():
    days=day_rows(); first=advance_graph(None,days,'elasticsearch')
    repeated=advance_graph(first,days,'elasticsearch')
    assert repeated['last_update']['windows_processed']==0
    assert repeated['version']==first['version']
    assert repeated['relations']==first['relations']
    relation=next(iter(first['relations'].values()))
    assert relation['observed_windows']==3
    assert relation['total_requests']==300
    assert relation['last_score']['prior_windows']==2
    assert relation['strength']>relation['prior_strength']


def test_late_correction_replays_to_same_state_as_fresh_training():
    days=day_rows(0)+day_rows(2)
    initial=advance_graph(None,days,'elasticsearch')
    correction=day_rows(0,200)+day_rows(1)+day_rows(2)
    revised=advance_graph(initial,correction,'elasticsearch')
    fresh=advance_graph(None,correction,'elasticsearch')
    assert revised==fresh
    assert initial['relations']!=fresh['relations']


def test_temporal_expiry_rebuilds_only_retained_memory():
    initial=advance_graph(None,day_rows(0)+day_rows(1),'elasticsearch')
    revised=advance_graph(initial,day_rows(1),'elasticsearch')
    assert revised==advance_graph(None,day_rows(1),'elasticsearch')


def test_support_decays_without_zero_traffic_training():
    state=reinforce(None,NOW,300)
    assert decayed_support(state,NOW+HALF_LIFE_MS)==pytest.approx(0.5)
    later=reinforce(copy.deepcopy(state),NOW+HALF_LIFE_MS,300)
    assert later['support']==pytest.approx(1.5)
    assert later['mean_tps']==1
    assert later['observed_windows']==2


def test_scores_are_preupdate_and_repeated_surges_do_not_train_reference():
    days=sum((day_rows(d,100,windows=12) for d in range(3)),[])
    previous=advance_graph(None,days,'elasticsearch')
    advanced=advance_graph(previous,days+day_rows(3,3000),'elasticsearch')
    old=next(iter(previous['relations'].values()));new=next(iter(advanced['relations'].values()))
    assert new['surge_streak']==3
    assert new['last_score']['expected_tps']==pytest.approx(100/300)
    assert new['mean_tps']==old['mean_tps']
    assert new['withheld_rate_windows']==3
    assert new['observed_windows']==old['observed_windows']+3
    assert new['last_score']['tps_surprise']>0.99


def test_graph_distinguishes_roles_and_exact_peer_windows():
    graph=advance_graph(None,day_rows(),'elasticsearch')
    assert {n['kind'] for n in graph['nodes'].values()}=={'service','api','credential','ip'}
    ip=next(n for n in graph['nodes'].values() if n['kind']=='ip')
    assert ip['observed_windows']==1  # Not smeared across the daily summary.
    assert ip['rate_samples']==0 and not ip['volume_known']
    assert {e['kind'] for e in graph['edges'].values()}=={'service_call','calls','owns','credential_on_call','peer_on_call'}


def test_new_edge_uses_previous_node_context():
    days=sum((day_rows(d,windows=12) for d in range(3)),[])
    graph=advance_graph(None,days+day_rows(3,operation='/export'),'elasticsearch')
    new=next(r for r in graph['relations'].values() if r['operation']=='/export')
    assert new['emergence']['known_credential_context']
    assert new['observed_windows']==3
    assert new['strength']<0.2


def test_ineligible_windows_increase_familiarity_not_tps_reference():
    rows=day_rows()
    rows[0]['clean_windows']=[];rows[0]['clean_counts']=[]
    graph=advance_graph(None,rows,'elasticsearch')
    relation=next(iter(graph['relations'].values()))
    assert relation['observed_windows']==3 and relation['rate_samples']==0
    assert relation['withheld_rate_windows']==3


def test_missing_caller_keeps_measured_api_rate_without_inventing_call_edge():
    row=normalize('elasticsearch',dict(principal='credential',target='target',operation='/read',bucket_ms=NOW,requests=30))
    graph=advance_graph(None,summarize_day([row]),'elasticsearch')
    assert next(iter(graph['relations'].values()))['mean_tps']==pytest.approx(0.1)
    assert not any(e['kind']=='calls' for e in graph['edges'].values())
    assert not any(n['label']=='unknown' for n in graph['nodes'].values())


def test_relationship_strength_decays_during_unobserved_time():
    from backend.app.services.behavior_graph import relationship_view
    graph=advance_graph(None,day_rows(),'elasticsearch')
    profile={'id':next(iter(graph['relations']))}
    old=relationship_view(graph,profile)
    later=relationship_view(graph,profile,graph['through_ms']-BUCKET+HALF_LIFE_MS)
    assert later['effective_windows']==pytest.approx(old['effective_windows']/2)
    assert later['expected_tps']==old['expected_tps']


def test_sources_and_environments_do_not_merge():
    rows=day_rows(); second=copy.deepcopy(rows)
    from backend.app.services.learned_behavior import relationship_id
    second[0]['environment']='staging';second[0]['id']=relationship_id(second[0])
    graph=advance_graph(None,rows+second,'elasticsearch')
    assert len(graph['relations'])==2
    assert {n['environment'] for n in graph['nodes'].values()}=={'prod','staging'}

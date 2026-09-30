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


def _trained(days=3):
    return sum((day_rows(d,100,windows=12) for d in range(days)),[])


def test_persistent_new_level_is_accepted_after_bounded_surge_period():
    from backend.app.services.behavior_graph import LEVEL_SHIFT_WINDOWS, level_shift_starts
    base=_trained()
    previous=advance_graph(None,base,'elasticsearch')
    shifted=advance_graph(previous,base+day_rows(3,400,windows=LEVEL_SHIFT_WINDOWS),'elasticsearch')
    relation=next(iter(shifted['relations'].values()))
    assert relation['level_shifts']==1
    assert relation['mean_tps']==pytest.approx(400/300)
    assert relation['surge_streak']==0 and 'shift_buffer' not in relation
    assert relation['level_shift']['from_tps']==pytest.approx(100/300)
    start=level_shift_starts(shifted)[relation['id']]
    assert start==NOW+3*DAY
    # Traffic at the accepted level is no longer a material surge.
    later=advance_graph(shifted,base+day_rows(3,400,windows=LEVEL_SHIFT_WINDOWS+3),'elasticsearch')
    assert next(iter(later['relations'].values()))['surge_streak']==0


def test_shorter_surge_is_withheld_and_never_becomes_the_reference():
    from backend.app.services.behavior_graph import LEVEL_SHIFT_WINDOWS
    base=_trained()
    graph=advance_graph(None,base+day_rows(3,400,windows=LEVEL_SHIFT_WINDOWS-1),'elasticsearch')
    relation=next(iter(graph['relations'].values()))
    assert relation.get('level_shifts',0)==0
    assert relation['mean_tps']==pytest.approx(100/300)
    assert len(relation['shift_buffer'])==LEVEL_SHIFT_WINDOWS-1


def test_ineligible_surge_windows_do_not_trigger_level_acceptance():
    from backend.app.services.behavior_graph import LEVEL_SHIFT_WINDOWS
    surge=day_rows(3,400,windows=LEVEL_SHIFT_WINDOWS)
    surge[0]['clean_windows']=[];surge[0]['clean_counts']=[]
    graph=advance_graph(None,_trained()+surge,'elasticsearch')
    relation=next(iter(graph['relations'].values()))
    assert relation.get('level_shifts',0)==0 and 'shift_buffer' not in relation


def test_profile_tps_reference_restarts_at_accepted_level_shift():
    from backend.app.services.learned_behavior import build_profiles
    days=sum((day_rows(d,100,windows=24) for d in range(8)),[])
    rid=days[0]['id']; now=NOW+8*DAY
    before,_=build_profiles(days,[],now)
    after,_=build_profiles(days,[],now,{rid:NOW+7*DAY})
    assert before[0]['tps']['reference_windows']>0
    assert after[0]['tps']['reference_windows']==0 and after[0]['tps']['reference_start']==NOW+7*DAY


def test_labelled_replay_benchmark_has_no_regressions():
    from backend.scripts.benchmark_behavior import replay
    results,_=replay(train_days=8,step=6,seed=3)
    failures=[r for r in results if not r['pass'] and not r['known_gap']]
    assert not failures, failures

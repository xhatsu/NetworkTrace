from backend.app.services.change_policy import evaluate_episode


def metric(kind='error_rate', current=20, baseline=1, **meta):
    return {'source': 'anomaly', 'severity': 'critical', 'raw_status': 'open',
            'signal': {'anomaly_type': kind, 'current_value': current,
                       'baseline_value': baseline, 'metadata': meta}}


def test_novelty_duplicates_are_not_independent():
    s = {'signal': {'change_type': 'NEW_TARGET'}}
    result = evaluate_episode([s, s])
    assert result['state'] == 'changed'
    assert not result['correlated']


def test_small_error_sample_is_watch():
    assert evaluate_episode([metric(total_requests=50, total_errors=5)])['state'] == 'watch'


def sustained(**overrides):
    values = dict(total_requests=200, total_errors=40, baseline_sample_count=6,
                  observation_bucket_start_ms=900000,
                  abnormal_bucket_starts_ms=[600000, 900000])
    values.update(overrides)
    return values


def test_persistent_material_errors_need_attention():
    assert evaluate_episode([metric(**sustained())])['state'] == 'needs_attention'


def test_retries_do_not_count_as_persistence():
    assert evaluate_episode([metric(**sustained(abnormal_bucket_starts_ms=[900000, 900000]))])['state'] == 'watch'


def test_old_and_future_windows_do_not_count():
    assert evaluate_episode([metric(**sustained(abnormal_bucket_starts_ms=[0, 1200000, 900000]))])['state'] == 'watch'


def test_weak_baseline_blocks_promotion():
    assert evaluate_episode([metric(**sustained(baseline_sample_count=2))])['state'] == 'watch'


def test_severe_persistent_error_impact():
    assert evaluate_episode([metric(current=60, **sustained(total_errors=120))])['state'] == 'critical'


def test_immediate_near_total_failure():
    assert evaluate_episode([metric(current=95, total_requests=1000, total_errors=950)])['state'] == 'critical'


def test_traffic_growth_without_capacity_impact_is_watch():
    assert evaluate_episode([metric('traffic_spike', current=100, **sustained(total_requests=30000))])['state'] == 'watch'


def test_missing_telemetry_is_not_confirmed_outage():
    assert evaluate_episode([metric('traffic_drop', current=0, baseline=10, **sustained())])['state'] == 'watch'


def test_explicit_authentication_needs_no_historical_baseline():
    s = {'signal': {'change_type': 'FAILURE_THEN_SUCCESS', 'reason': {
        'impact_evidence': {'explicit_auth_failures': 25, 'same_scope_successes': 1},
        'how_reliable': {'attribution_method': 'explicit_security_event', 'collection_quality': 'healthy'}}}}
    assert evaluate_episode([s])['state'] == 'needs_attention'
    s['signal']['reason']['impact_evidence']['same_scope_successes'] = 0
    assert evaluate_episode([s])['state'] == 'watch'


def test_suppression_does_not_erase_impact():
    s = metric(current=95, total_requests=1000, total_errors=950)
    s['raw_status'] = 'suppressed'
    assert evaluate_episode([s])['state'] == 'critical'

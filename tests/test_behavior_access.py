import time
from backend.app.services.behavior_sources import normalize
from backend.app.services.learned_behavior import DAY, BUCKET, summarize_day
from backend.app.services.behavior_graph import advance_graph
from backend.app.services.behavior_access import project_flow, project_matrix, api_label

BASE = 1800000000000 // DAY * DAY


def row(bucket, principal='robot', caller='checkout', target='payments', operation='/charge', ips=('192.0.2.1',), n=100):
    return normalize('elasticsearch', dict(environment='prod', caller=caller, principal=principal, target=target,
                                            operation=operation, bucket_ms=bucket, requests=n, observed_ips=list(ips)))


def build(rows):
    return advance_graph(None, summarize_day(rows, include_anonymous=True), 'elasticsearch')


def history(**kw):
    """Ten days of activity, so the relationship is established."""
    return [row(BASE + d * DAY + w * BUCKET, **kw) for d in range(10) for w in range(20)]


def flow(graph, **kw):
    args = dict(environment='prod', focus_type='service', focus='payments')
    args.update(kw)
    return project_flow(graph, [], [], **args)


def link(result, a, b):
    ids = {n['label']: n['id'] for n in result['nodes']}
    return next((l for l in result['links'] if l['source'] == ids.get(a) and l['target'] == ids.get(b)), None)


def test_established_ghost_and_new_states():
    rows = history()  # robot -> payments/charge, active until day 9
    rows += history(principal='batch', operation='/refund')[:20]  # batch only on day 0 -> ghost later
    end = BASE + 9 * DAY + 20 * BUCKET
    rows += [row(end + w * BUCKET, principal='intruder', operation='/admin') for w in range(3)]  # new right now
    graph = build(rows)
    view = flow(graph)
    states = {n['label']: n['state'] for n in view['nodes']}
    assert states['robot'] == 'established'
    assert states['batch'] == 'ghost'
    assert states['intruder'] == 'new'
    ghost = link(view, 'batch', api_label('payments', '/refund'))
    assert ghost['state'] == 'ghost' and ghost['observed_tps'] == 0 and ghost['width_tps'] > 0


def test_no_caller_gives_no_caller_ribbon_and_anonymous_is_no_credential():
    rows = history(caller='unknown') + history(principal='-anonymous-', operation='/health', caller='unknown')
    view = flow(build(rows))
    assert not [n for n in view['nodes'] if n['kind'] == 'caller']
    assert not any(n['label'] in ('-anonymous-', 'unknown') for n in view['nodes'])
    assert any(n['label'] == api_label('payments', '/health') for n in view['nodes'])  # anonymous keeps its API bar
    health = next(n['id'] for n in view['nodes'] if n['label'] == api_label('payments', '/health'))
    assert not [l for l in view['links'] if l['target'] == health]                       # but adds no ribbon
    full = flow(build(rows), collapse_service=False)
    assert link(full, 'payments', api_label('payments', '/health'))                     # uncollapsed: Service -> API


def test_service_focus_links_credentials_to_their_own_apis():
    rows = history() + history(principal='batch', operation='/refund')
    view = flow(build(rows))
    assert 'service' not in view['columns'] and not [n for n in view['nodes'] if n['kind'] == 'service']
    pairs = {(l['from_column'], l['to_column']) for l in view['links']}
    assert ('credential', 'api') in pairs and not {p for p in pairs if 'service' in p}
    assert link(view, 'robot', api_label('payments', '/charge'))
    assert link(view, 'batch', api_label('payments', '/refund'))
    assert not link(view, 'robot', api_label('payments', '/refund'))
    assert not link(view, 'batch', api_label('payments', '/charge'))


def test_top_n_and_other_bucket():
    rows = [r for i in range(30) for r in history(principal=f'cred{i:02}', n=10 + i)[:10]]
    view = flow(build(rows), top=5)
    creds = [n for n in view['nodes'] if n['kind'] == 'credential']
    assert len(creds) == 6 and creds[-1]['label'] == 'Other' and creds[-1]['other_count'] == 25
    assert view['caps']['credential'] == {'shown': 5, 'total': 30}
    total = sum(l['width_tps'] for l in view['links'] if l['from_column'] == 'credential')
    assert total > 0


def test_cross_filter_and_ip_groups():
    rows = history() + history(principal='other', operation='/refund', ips=('198.51.100.9',))
    graph = build(rows)
    view = flow(graph, filters={'credential': 'robot'})
    assert {n['label'] for n in view['nodes'] if n['kind'] == 'credential'} == {'robot'}
    assert view['ip']['expanded_role'] is None and view['ip']['total'] == 1
    ip_nodes = [n for n in view['nodes'] if n['kind'] == 'ip']
    assert ip_nodes and all(n['group'] for n in ip_nodes)          # collapsed by default
    assert all(not l['volume_known'] for l in view['links'] if l['to_column'] == 'ip')
    role = view['ip']['roles'][0]['role']
    expanded = flow(graph, filters={'credential': 'robot'}, ip_role=role)
    assert [n['label'] for n in expanded['nodes'] if n['kind'] == 'ip' and not n['group']] == ['192.0.2.1']


def test_infrastructure_ips_are_flagged_not_origins():
    graph = build(history(ips=('10.0.0.5',)))
    for node in graph['nodes'].values():
        if node['kind'] == 'ip':
            node['role'] = 'nat_gateway'
    role = flow(graph)['ip']['roles'][0]
    assert role['role'] == 'nat' and role['infrastructure'] is True


def test_baseline_basis_uses_expected_tps_and_environment_isolation():
    graph = build(history())
    observed = flow(graph)['nodes']
    baseline = flow(graph, basis='baseline')['nodes']
    assert observed[0]['expected_tps'] and baseline
    assert flow(graph, environment='staging')['nodes'] == []


def test_matrix_orders_role_groups_and_pages():
    rows = []
    for i in range(6):
        for op in ('/a', '/b', '/c'):
            rows += history(principal=f'admin{i}', operation=op)[:5]
    for i in range(6):
        for op in ('/x', '/y', '/z'):
            rows += history(principal=f'user{i}', operation=op)[:5]
    graph = build(rows)
    m = project_matrix(graph, [], [], 'prod')
    assert m['row_total'] == 12 and m['col_total'] == 6
    names = [r['name'] for r in m['rows']]
    groups = [n[:4] for n in names]
    assert groups == sorted(groups, key=lambda g: groups.index(g))   # blocks are contiguous
    page = project_matrix(graph, [], [], 'prod', row_limit=5, col_limit=2)
    assert len(page['rows']) == 5 and len(page['cols']) == 2 and page['row_total'] == 12
    assert all(c['row'] < 5 and c['col'] < 2 for c in page['cells'])


def synthetic_graph(credentials, apis, services=8, ips_per_relation=3):
    """Directly assembled snapshot; the real engine caps relations at 5,000."""
    now = BASE + 30 * DAY
    relations, nodes, edges = {}, {}, {}
    n = 0
    for c in range(credentials):
        for a in range(apis):
            if (c * 7 + a) % 3:
                continue
            rid = f'r{c}-{a}'
            relations[rid] = dict(id=rid, environment='prod', caller=f'caller{c % 20}', principal=f'cred{c}', target=f's{a % services}',
                operation=f'/op{a}', first_seen=now - 20 * DAY, last_seen=now - (0 if a % 5 else 3 * DAY), last_tps=0.5, mean_tps=0.4,
                rate_samples=30, observed_windows=100, active_days=list(range(10)), surge_streak=0, last_score={'at': now, 'material_tps_surge': False})
            for i in range(ips_per_relation):
                ip = f'10.{(c * 31 + i) % 250}.{a % 250}.{n % 250}'
                nid = f'ip-{ip}'; n += 1
                nodes[nid] = dict(id=nid, kind='ip', label=ip, role=('load_balancer' if i == 0 else 'unverified_peer'))
                edges[f'e{rid}-{i}'] = dict(id=f'e{rid}-{i}', kind='peer_on_call', **{'from': nid}, to='x', relationship_id=rid,
                    first_seen=now - 20 * DAY, last_seen=now)
    return {'algorithm': 'online-behavior-graph-v4', 'source': 'legacy_metrics', 'through_ms': now, 'version': 'v', 'relations': relations, 'nodes': nodes, 'edges': edges}


def test_large_scale_is_bounded_and_fast():
    graph = synthetic_graph(320, 200, ips_per_relation=3)   # >= 300 credentials x 200 APIs, ~3k+ distinct IPs
    assert len(graph['relations']) > 20000 and len({n['label'] for n in graph['nodes'].values()}) >= 1000
    started = time.time()
    view = project_flow(graph, [], [], 'prod', 'service', 's1', top=50)
    matrix = project_matrix(graph, [], [], 'prod', row_limit=200, col_limit=200)
    elapsed = time.time() - started
    columns = {n['kind'] for n in view['nodes']}
    assert all(sum(1 for n in view['nodes'] if n['kind'] == c) <= 51 for c in ('caller', 'credential', 'service', 'api'))
    assert len(view['links']) < 1500 and view['caps']['credential']['total'] == 320
    assert len(matrix['rows']) == 200 and len(matrix['cols']) == 200 and matrix['row_total'] == 320
    assert any(n['state'] == 'ghost' for n in view['nodes'])
    print('flow+matrix seconds', round(elapsed, 2))
    assert elapsed < 10


def test_access_endpoint_uses_only_snapshot_repository():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api import behavior
    graph = build(history())

    class Repo:
        def graph_state(self, source): return graph
        def items(self, kind, source=None): return []

    app = FastAPI(); app.include_router(behavior.router)
    app.dependency_overrides[behavior.repository] = lambda: Repo()
    client = TestClient(app)
    flow_response = client.get('/api/v1/behavior/access', params={'focus': 'payments', 'top': 5})
    assert flow_response.status_code == 200 and flow_response.json()['environment'] == 'prod'
    assert client.get('/api/v1/behavior/access', params={'view': 'flow'}).status_code == 422
    assert client.get('/api/v1/behavior/access', params={'view': 'matrix', 'row_limit': 500}).status_code == 422
    assert client.get('/api/v1/behavior/access', params={'view': 'matrix'}).json()['row_total'] == 1


def test_matrix_first_page_meets_its_own_columns():
    rows = []
    for i in range(6):
        for op in ('/a', '/b', '/c'):
            rows += history(principal=f'admin{i}', operation=op)[:5]
    for i in range(6):
        for op in ('/x', '/y', '/z'):
            rows += history(principal=f'user{i}', operation=op)[:5]
    m = project_matrix(build(rows), [], [], 'prod', row_limit=6, col_limit=3)
    assert len(m['cells']) == 18

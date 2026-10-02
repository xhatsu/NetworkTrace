import time
from backend.app.services.behavior_access import api_label, project_lists
from tests.test_behavior_access import BASE, BUCKET, DAY, build, history, row, synthetic_graph


def lists(graph, **kw):
    args = dict(environment='prod', service='payments')
    args.update(kw)
    return project_lists(graph, [], [], **args)


def names(view, column):
    return [r['name'] for r in view['columns'][column]['items']]


def usual_rows():
    rows = history()                                                   # robot via checkout -> /charge
    rows += history(principal='clerk', caller='backoffice', operation='/refund')
    rows += history(principal='clerk', caller='backoffice', operation='/charge')
    return rows


def test_columns_are_faceted_and_keep_siblings_of_the_selected_row():
    view = lists(build(usual_rows()))
    assert set(names(view, 'credential')) == {'robot', 'clerk'}
    assert set(names(view, 'api')) == {api_label('payments', '/charge'), api_label('payments', '/refund')}
    picked = lists(build(usual_rows()), filters={'credential': 'clerk'})
    assert set(names(picked, 'credential')) == {'robot', 'clerk'}      # own column ignores its own filter
    assert set(names(picked, 'caller')) == {'backoffice'}
    assert set(names(picked, 'api')) == {api_label('payments', '/charge'), api_label('payments', '/refund')}
    by_api = lists(build(usual_rows()), filters={'api': api_label('payments', '/refund')})
    assert names(by_api, 'credential') == ['clerk']


def test_bot_fanout_is_one_ranked_item_not_one_row_per_api():
    rows = usual_rows()
    end = BASE + 9 * DAY + 20 * BUCKET
    for i in range(8):                                                 # scanner hits 8 new APIs right now
        rows += [row(end + w * BUCKET, principal='scanner', caller='edge', operation=f'/scan{i}') for w in range(2)]
    view = lists(build(rows))
    first = view['unusual']['items'][0]
    assert first['reason'] == 'fanout' and first['credential'] == 'scanner'
    assert first['new_apis'] == 8 and first['usual_apis'] == 0
    assert not [i for i in view['unusual']['items'] if i['reason'] == 'new' and i['credential'] == 'scanner']
    cred = view['columns']['credential']['items']
    assert cred[0]['name'] == 'scanner' and cred[0]['unusual']        # unusual rows sort first
    assert all(r['unusual'] for r in view['columns']['api']['items'] if r['name'].startswith('payments → /scan'))


def test_new_relationship_and_silent_established_path():
    rows = usual_rows() + history(principal='legacy', operation='/export')[:185]  # established, quiet for the last ~1.3 h
    rows += history(principal='retired', operation='/old')[:160]                    # quiet for 2 days: not listed
    end = BASE + 9 * DAY + 20 * BUCKET
    rows += [row(end + w * BUCKET, principal='partner', operation='/charge') for w in range(2)]
    view = lists(build(rows))
    reasons = {(i['reason'], i['credential']) for i in view['unusual']['items']}
    assert ('new', 'partner') in reasons
    assert ('silent', 'legacy') in reasons
    assert not any(c in ('robot', 'retired') for _, c in reasons)             # usual traffic and old silences are not listed


def test_search_paging_and_selection_neighbours():
    rows = []
    for i in range(30):
        rows += history(principal=f'user{i:02}', operation=f'/op{i % 4}', caller=f'caller{i % 3}')[:4]
    graph = build(rows)
    page = lists(graph, limit=10)
    assert page['columns']['credential']['total'] == 30 and len(names(page, 'credential')) == 10
    second = lists(graph, limit=10, offsets={'credential': 10})
    assert not set(names(page, 'credential')) & set(names(second, 'credential'))
    found = lists(graph, search={'credential': 'user1'})
    assert set(names(found, 'credential')) == {f'user{i}' for i in range(10, 20)}
    sel = lists(graph, select_type='credential', select='user05')['selection']
    assert sel['name'] == 'user05' and sel['left']['column'] == 'caller' and sel['right']['column'] == 'api'
    assert [r['name'] for r in sel['left']['items']] == ['caller2']
    assert [r['name'] for r in sel['right']['items']] == [api_label('payments', '/op1')]
    assert sel['ips'] and sel['detail_id']
    api_sel = lists(graph, select_type='api', select=api_label('payments', '/op1'))['selection']
    users = [i for i in range(30) if i % 4 == 1]
    assert api_sel['left']['column'] == 'caller' and api_sel['right']['column'] == 'credential'
    assert {r['name'] for r in api_sel['left']['items']} == {f'caller{i % 3}' for i in users}
    assert api_sel['right']['total'] == len(users)
    caller_sel = lists(graph, select_type='caller', select='caller0')['selection']
    assert caller_sel['left']['column'] == 'credential' and caller_sel['right']['column'] == 'api'
    assert {r['name'] for r in caller_sel['right']['items']} == {api_label('payments', f'/op{i % 4}') for i in range(30) if i % 3 == 0}


def test_lists_scale_to_hundreds_of_credentials_and_apis():
    graph = synthetic_graph(900, 220, services=1, ips_per_relation=1)
    started = time.time()
    view = project_lists(graph, [], [], 'prod', 's0', limit=100, select_type='credential', select='cred7')
    elapsed = time.time() - started
    assert view['columns']['credential']['total'] == 900 and len(view['columns']['credential']['items']) == 100
    assert view['columns']['api']['total'] == 220 and view['selection']['right']['total'] > 0
    print('lists seconds', round(elapsed, 2), 'relations', len(graph['relations']))
    assert elapsed < 10


def test_lists_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api import behavior
    graph = build(usual_rows())

    class Repo:
        def graph_state(self, source): return graph
        def items(self, kind, source=None): return []

    app = FastAPI(); app.include_router(behavior.router)
    app.dependency_overrides[behavior.repository] = lambda: Repo()
    client = TestClient(app)
    assert client.get('/api/v1/behavior/access', params={'view': 'lists'}).status_code == 422
    body = client.get('/api/v1/behavior/access', params={'view': 'lists', 'service': 'payments', 'credential': 'clerk',
                                                          'select_type': 'credential', 'select': 'clerk'}).json()
    assert body['status'] == 'active' and body['selection']['name'] == 'clerk'
    assert {r['name'] for r in body['columns']['caller']['items']} == {'backoffice'}


def cross_service_rows():
    rows = usual_rows()                                                            # robot + clerk on payments
    rows += history(principal='clerk', caller='backoffice', target='ledger', operation='/post')
    rows += history(principal='robot', caller='checkout', target='ledger', operation='/read')
    return rows


def test_credential_scope_explores_one_user_across_services():
    view = lists(build(cross_service_rows()), service='', scope='credential', filters={'credential': 'clerk'},
                 select_type='credential', select='clerk')
    assert set(names(view, 'service')) == {'payments', 'ledger'}
    assert set(names(view, 'api')) == {api_label('payments', '/charge'), api_label('payments', '/refund'),
                                       api_label('ledger', '/post')}               # robot's ledger API is excluded
    assert names(view, 'caller') == ['backoffice']
    sel = view['selection']
    assert sel['left']['column'] == 'caller' and sel['right']['column'] == 'service'
    assert {r['name'] for r in sel['right']['items']} == {'payments', 'ledger'}
    # Choosing a Service narrows the APIs and the selection stays inside this user's relationships.
    narrowed = lists(build(cross_service_rows()), service='', scope='credential',
                     filters={'credential': 'clerk', 'service': 'ledger'}, select_type='service', select='ledger')
    assert names(narrowed, 'api') == [api_label('ledger', '/post')]
    assert set(names(narrowed, 'service')) == {'payments', 'ledger'}               # own column keeps siblings
    assert [r['name'] for r in narrowed['selection']['right']['items']] == [api_label('ledger', '/post')]
    assert [r['name'] for r in narrowed['selection']['left']['items']] == ['backoffice']


def test_service_scope_ignores_a_service_column_filter():
    view = lists(build(cross_service_rows()), filters={'service': 'ledger'})
    assert set(names(view, 'service')) == {'payments'}
    assert set(names(view, 'credential')) == {'robot', 'clerk'}


def test_credential_scope_endpoint_requires_a_credential():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.api import behavior
    graph = build(cross_service_rows())

    class Repo:
        def graph_state(self, source): return graph
        def items(self, kind, source=None): return []

    app = FastAPI(); app.include_router(behavior.router)
    app.dependency_overrides[behavior.repository] = lambda: Repo()
    client = TestClient(app)
    assert client.get('/api/v1/behavior/access', params={'view': 'lists', 'scope': 'credential'}).status_code == 422
    body = client.get('/api/v1/behavior/access', params={'view': 'lists', 'scope': 'credential', 'credential': 'robot',
                                                          'service': 'ledger', 'select_type': 'service', 'select': 'ledger'}).json()
    assert body['scope'] == 'credential' and body['selection']['name'] == 'ledger'
    assert {r['name'] for r in body['columns']['api']['items']} == {api_label('ledger', '/read')}

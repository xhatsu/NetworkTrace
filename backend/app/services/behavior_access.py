"""Joined learned + observed access projections for the Sankey and matrix views.

Reads only the persisted learned graph snapshot plus the profile/deviation read
models. Never reads raw traces or Elasticsearch, never invents callers or IPs.
Anonymous traffic keeps Service/API flows but never becomes a credential node.
"""
from __future__ import annotations
from collections import defaultdict
import time
from .behavior_graph import ALGORITHM, node_id, decayed_support, strength
from .learned_behavior import BUCKET, DAY, UNKNOWN, digest

COLUMNS = ('caller', 'credential', 'service', 'api', 'ip')
FOCUS_TYPES = set(COLUMNS)
MAX_TOP = 50
MAX_ROLE_IPS = 100
MAX_SIMILARITY_ITEMS = 1000
IP_ROLES = ('client', 'load_balancer', 'reverse_proxy', 'nat', 'infrastructure', 'unverified_peer')
ROLE_ALIAS = {'nat_gateway': 'nat', 'service_ingress': 'infrastructure', 'unknown': 'unverified_peer', 'load_balancer': 'load_balancer'}
# Most attention-worthy first; a merged ribbon shows its worst constituent.
STATE_RANK = {'deviating': 5, 'new': 4, 'emerging': 3, 'established': 2, 'dormant': 1, 'ghost': 0}
DEVIATION_KINDS = {'traffic_surge', 'contract_violation', 'graph_tps_shift'}


def _known(value):
    return str(value or '').lower() not in UNKNOWN


def _role(value):
    value = ROLE_ALIAS.get(value, value)
    return value if value in IP_ROLES else 'unverified_peer'


def api_label(target, operation):
    return f'{target} → {operation}'


def relation_facts(graph, profiles, deviations, environment, anchor, window_ms):
    """One record per learned relationship with its familiarity/deviation state."""
    start = anchor - window_ms
    familiarity = {p['id']: p['familiarity'] for p in profiles}
    flagged = defaultdict(set)
    for d in deviations:
        if d.get('status') != 'reviewed':
            flagged[d.get('relationship_id')].add(d.get('kind'))
    facts = []
    for rid, r in graph['relations'].items():
        if r['environment'] != environment:
            continue
        observed = r['last_seen'] >= start
        kinds = flagged.get(rid, set())
        score = r.get('last_score') or {}
        expected = r['mean_tps'] if r['rate_samples'] else None
        fam = familiarity.get(rid) or ('established' if r['observed_windows'] >= 5 and len(r['active_days']) >= 3
                                       and r['last_seen'] - r['first_seen'] >= 7 * DAY else 'emerging')
        if anchor - r['last_seen'] >= 7 * DAY:
            fam = 'dormant'
        if not observed:
            state = 'ghost'
        elif kinds & DEVIATION_KINDS or r.get('surge_streak', 0) >= 3 or (score.get('material_tps_surge') and score.get('at', 0) >= start):
            state = 'deviating'
        elif 'access_expansion' in kinds or r['first_seen'] >= start:
            state = 'new'
        else:
            state = fam
        observed_tps = r['last_tps'] if observed else 0.0
        width_expected = expected if expected is not None else r['last_tps']
        facts.append({
            'id': rid, 'caller': r['caller'], 'principal': r['principal'], 'target': r['target'],
            'operation': r['operation'], 'state': state, 'familiarity': fam,
            'observed_tps': observed_tps, 'expected_tps': expected, 'baseline_tps': width_expected,
            'first_seen_ms': r['first_seen'], 'last_seen_ms': r['last_seen'], 'observed': observed,
            'level_shift': bool(r.get('level_shift')), 'flags': sorted(k for k in kinds if k),
        })
    return facts


def _width(fact, basis):
    if basis == 'baseline' or not fact['observed']:
        return fact['baseline_tps']
    return fact['observed_tps']


def _worst(states):
    return max(states, key=lambda s: STATE_RANK[s])


class _Agg:
    __slots__ = ('key', 'kind', 'label', 'width', 'observed', 'expected', 'states', 'fams', 'last', 'first', 'count', 'extra')

    def __init__(self, key, kind, label):
        self.key, self.kind, self.label = key, kind, label
        self.width = self.observed = self.expected = 0.0
        self.states, self.fams = [], []
        self.last, self.first, self.count, self.extra = 0, 0, 0, {}

    def add(self, fact, basis, state=None, volume=True):
        if volume:
            self.width += _width(fact, basis)
            self.observed += fact['observed_tps']
            self.expected += fact['expected_tps'] or 0.0
        self.states.append(state or fact['state'])
        self.fams.append(fact['familiarity'])
        self.last = max(self.last, fact['last_seen_ms'])
        self.first = min(self.first or fact['first_seen_ms'], fact['first_seen_ms'])
        self.count += 1

    def view(self):
        state = _worst(self.states) if self.states else 'established'
        # A merged element is a ghost only when every constituent is missing.
        if state != 'ghost' and all(s == 'ghost' for s in self.states):
            state = 'ghost'
        return {'id': self.key, 'kind': self.kind, 'label': self.label, 'state': state,
                'familiarity': _worst(self.fams) if self.fams else 'emerging',
                'width_tps': round(self.width, 6), 'observed_tps': round(self.observed, 6),
                'expected_tps': round(self.expected, 6) if self.expected else None,
                'first_seen_ms': self.first, 'last_seen_ms': self.last, 'relationships': self.count, **self.extra}


def _match(fact, filters):
    api = api_label(fact['target'], fact['operation'])
    return ((not filters.get('service') or fact['target'] == filters['service'])
            and (not filters.get('api') or api == filters['api'])
            and (not filters.get('credential') or fact['principal'] == filters['credential'])
            and (not filters.get('caller') or fact['caller'] == filters['caller']))


def _column_values(fact):
    return {'caller': fact['caller'] if _known(fact['caller']) else None,
            'credential': fact['principal'] if _known(fact['principal']) else None,
            'service': fact['target'],
            'api': api_label(fact['target'], fact['operation'])}


def project_flow(graph, profiles, deviations, environment, focus_type, focus, filters=None, top=12,
                 window_minutes=60, basis='observed', ip_role='', ip_offset=0, ip_limit=12, now=None,
                 collapse_service=None):
    """Focused alluvial: Caller Service → Credential → Service → API → IP.

    Focus is one entity; upstream columns sit left of it, downstream right. Each
    column keeps its top ``top`` nodes and one "Other (k)" bucket.

    With a Service focus the Service column would be a single bar that merges every
    ribbon, hiding which credential reaches which API. It is dropped so ribbons run
    Credential -> API directly (``collapse_service``). Traffic without a credential
    still sizes the API bars; it adds no ribbon.
    """
    if collapse_service is None:
        collapse_service = focus_type == 'service'
    chain = tuple(c for c in COLUMNS[:4] if not (collapse_service and c == 'service'))
    top = max(1, min(top, MAX_TOP))
    filters = dict(filters or {})
    if focus_type in ('service', 'api', 'credential', 'caller') and focus:
        filters[focus_type] = focus
    result = {'status': 'learning', 'backend': 'learned_graph', 'source': (graph or {}).get('source'),
              'environment': environment, 'focus': {'type': focus_type, 'name': focus}, 'basis': basis,
              'columns': [*chain, 'ip'], 'nodes': [], 'links': [], 'top': top, 'caps': {},
              'ip': {'expanded_role': ip_role or None, 'roles': [], 'offset': ip_offset, 'limit': ip_limit, 'total': 0}}
    if not graph or graph.get('algorithm') != ALGORITHM:
        return result
    result['status'] = 'active'
    anchor = graph['through_ms'] or (now if now is not None else int(time.time() * 1000))
    window_ms = window_minutes * 60_000
    result.update(as_of_ms=anchor, window_ms=window_ms, window_start_ms=anchor - window_ms,
                  through_ms=graph['through_ms'], version=graph.get('version'))
    facts = [f for f in relation_facts(graph, profiles, deviations, environment, anchor, window_ms)]
    ip_edges = defaultdict(list)
    for edge in graph['edges'].values():
        if edge['kind'] == 'peer_on_call':
            ip = graph['nodes'].get(edge['from'])
            if ip:
                ip_edges[edge['relationship_id']].append((ip, edge))
    if focus_type == 'ip' and focus:
        facts = [f for f in facts if any(ip['label'] == focus for ip, _ in ip_edges.get(f['id'], []))]
        filters['ip'] = focus
    elif filters.get('ip'):
        facts = [f for f in facts if any(ip['label'] == filters['ip'] for ip, _ in ip_edges.get(f['id'], []))]
    facts = [f for f in facts if _match(f, filters)]
    result['relationships_total'] = len(facts)
    if not facts:
        return result

    node_key = lambda column, name: digest([column, name])
    nodes = {c: {} for c in chain}
    pairs = {}  # (chain index, name a, name b) -> _Agg
    for f in facts:
        values = _column_values(f)
        for column in chain:
            name = values[column]
            if name is None:
                continue
            agg = nodes[column].setdefault(name, _Agg(node_key(column, name), column, name))
            agg.add(f, basis)
        # A missing caller/credential contributes no ribbon on that side.
        for i in range(len(chain) - 1):
            a, b = values[chain[i]], values[chain[i + 1]]
            if a is None or b is None:
                continue
            key = (i, a, b)
            agg = pairs.setdefault(key, _Agg(digest(['link', *key]), 'link', ''))
            agg.add(f, basis)
            agg.extra.setdefault('_facts', []).append(f['id'])

    # Top-N per column, the rest folds into one "Other (k)" node.
    keep, other = {}, {}
    for column in chain:
        ordered = sorted(nodes[column].values(), key=lambda a: (-a.width, a.label))
        keep[column] = {a.label for a in ordered[:top]}
        rest = ordered[top:]
        result['caps'][column] = {'shown': min(top, len(ordered)), 'total': len(ordered)}
        if rest:
            agg = _Agg(node_key(column, '\0other'), column, 'Other')
            for a in rest:
                agg.width += a.width; agg.observed += a.observed; agg.expected += a.expected
                agg.states += a.states; agg.fams += a.fams; agg.count += a.count
                agg.last = max(agg.last, a.last); agg.first = min(agg.first or a.first, a.first)
            agg.extra.update(other=True, other_count=len(rest))
            other[column] = agg
    view_nodes = []
    for column in chain:
        for a in sorted(nodes[column].values(), key=lambda a: (-a.width, a.label)):
            if a.label in keep[column]:
                view_nodes.append(a.view())
        if column in other:
            view_nodes.append(other[column].view())
    result['nodes'] = view_nodes

    def endpoint(column, name):
        return node_key(column, name if name in keep[column] else '\0other')

    merged = {}
    for (i, a, b), agg in pairs.items():
        key = (i, endpoint(chain[i], a), endpoint(chain[i + 1], b))
        m = merged.setdefault(key, {'agg': _Agg(digest(['link', *key]), 'link', ''), 'names': (a, b), 'facts': []})
        m['agg'].width += agg.width; m['agg'].observed += agg.observed; m['agg'].expected += agg.expected
        m['agg'].states += agg.states; m['agg'].fams += agg.fams; m['agg'].count += agg.count
        m['agg'].last = max(m['agg'].last, agg.last); m['agg'].first = min(m['agg'].first or agg.first, agg.first)
        m['facts'] += agg.extra['_facts']
    links = []
    for (i, source, target), m in sorted(merged.items()):
        v = m['agg'].view()
        detail = _detail_id(graph, environment, (chain[i], chain[i + 1]), m['names'], facts, m['facts'])
        links.append({**v, 'source': source, 'target': target, 'from_column': chain[i], 'to_column': chain[i + 1],
                      'volume_known': True, 'detail_id': detail})
    result['links'] = links
    _project_ips(result, facts, ip_edges, keep, other, node_key, anchor - window_ms, ip_role, ip_offset, ip_limit)
    return result


def _detail_id(graph, environment, pair, names, facts, fact_ids):
    """Object accepted by /behavior/topology/detail whose series best matches a ribbon."""
    source = graph['source']
    if pair == ('service', 'api'):
        return node_id(source, environment, 'api', names[1])
    if pair == ('caller', 'credential'):
        return node_id(source, environment, 'credential', names[1])
    if pair[0] == 'credential':   # Credential -> Service, or Credential -> API when Service is collapsed
        return node_id(source, environment, 'credential', names[0])
    return None


def _project_ips(result, facts, ip_edges, keep, other, node_key, window_start, ip_role, offset, limit):
    """IP column: role groups by default; one role expands to paged individual IPs."""
    limit = max(1, min(limit, MAX_ROLE_IPS))
    by_role = defaultdict(dict)   # role -> address -> aggregate
    links = defaultdict(lambda: {'facts': set(), 'states': [], 'last': 0, 'first': 0})
    for f in facts:
        api = api_label(f['target'], f['operation'])
        api_key = node_key('api', api if api in keep['api'] else '\0other')
        for ip, edge in ip_edges.get(f['id'], []):
            role = _role(ip.get('role'))
            state = 'ghost' if edge['last_seen'] < window_start else 'new' if edge['first_seen'] >= window_start and f['state'] != 'new' else f['state']
            rec = by_role[role].setdefault(ip['label'], {'states': [], 'last': 0, 'first': 0, 'apis': set()})
            rec['states'].append(state); rec['last'] = max(rec['last'], edge['last_seen'])
            rec['first'] = min(rec['first'] or edge['first_seen'], edge['first_seen']); rec['apis'].add(api_key)
            target = ('ip', role, ip['label']) if ip_role == role else ('ip', role, None)
            link = links[(api_key, target)]
            link['facts'].add(f['id']); link['states'].append(state)
            link['last'] = max(link['last'], edge['last_seen']); link['first'] = min(link['first'] or edge['first_seen'], edge['first_seen'])
    roles = []
    for role in IP_ROLES:
        if role not in by_role:
            continue
        ips = by_role[role]
        states = [s for rec in ips.values() for s in rec['states']]
        roles.append({'role': role, 'count': len(ips), 'state': _worst(states), 'last_seen_ms': max(r['last'] for r in ips.values()),
                      'infrastructure': role in ('load_balancer', 'reverse_proxy', 'nat', 'infrastructure')})
    result['ip'].update(roles=roles, total=sum(r['count'] for r in roles))
    shown = {}
    if ip_role in by_role:
        ordered = sorted(by_role[ip_role].items(), key=lambda kv: (-kv[1]['last'], kv[0]))
        result['ip']['role_total'] = len(ordered)
        for address, rec in ordered[offset:offset + limit]:
            shown[address] = rec
    for role in roles:
        if role['role'] == ip_role:
            continue
        result['nodes'].append({'id': node_key('ip', role['role']), 'kind': 'ip', 'label': role['role'], 'group': True,
                                'state': role['state'], 'familiarity': 'emerging', 'width_tps': None, 'observed_tps': None,
                                'expected_tps': None, 'last_seen_ms': role['last_seen_ms'], 'first_seen_ms': 0,
                                'relationships': role['count'], 'ip_count': role['count'], 'role': role['role'],
                                'infrastructure': role['infrastructure']})
    for address, rec in shown.items():
        result['nodes'].append({'id': node_key('ip', ip_role + address), 'kind': 'ip', 'label': address, 'group': False,
                                'state': _worst(rec['states']), 'familiarity': 'emerging', 'width_tps': None,
                                'observed_tps': None, 'expected_tps': None, 'last_seen_ms': rec['last'],
                                'first_seen_ms': rec['first'], 'relationships': 1, 'role': ip_role,
                                'infrastructure': ip_role in ('load_balancer', 'reverse_proxy', 'nat', 'infrastructure')})
    for (api_key, target), link in sorted(links.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        _, role, address = target
        if address is not None and address not in shown:
            continue
        target_id = node_key('ip', ip_role + address) if address else node_key('ip', role)
        result['links'].append({'id': digest(['ip-link', api_key, target_id]), 'kind': 'link', 'label': '', 'source': api_key,
            'target': target_id, 'from_column': 'api', 'to_column': 'ip', 'state': _worst(link['states']),
            'familiarity': 'emerging', 'width_tps': None, 'observed_tps': None, 'expected_tps': None,
            'first_seen_ms': link['first'], 'last_seen_ms': link['last'], 'relationships': len(link['facts']),
            'volume_known': False, 'detail_id': None})


def project_matrix(graph, profiles, deviations, environment, service='', order='similarity', basis='observed',
                   row_offset=0, row_limit=50, col_offset=0, col_limit=50, window_minutes=60, now=None):
    """Credential × API grid. Rows are ordered so similar access sets are adjacent."""
    row_limit = max(1, min(row_limit, 200)); col_limit = max(1, min(col_limit, 200))
    result = {'status': 'learning', 'environment': environment, 'order': order, 'basis': basis,
              'rows': [], 'cols': [], 'cells': [], 'row_total': 0, 'col_total': 0, 'row_offset': row_offset,
              'col_offset': col_offset, 'row_limit': row_limit, 'col_limit': col_limit,
              'caps': {'similarity_items': MAX_SIMILARITY_ITEMS, 'max_page': 200}, 'similarity_capped': False}
    if not graph or graph.get('algorithm') != ALGORITHM:
        return result
    result['status'] = 'active'
    anchor = graph['through_ms'] or (now if now is not None else int(time.time() * 1000))
    window_ms = window_minutes * 60_000
    result.update(as_of_ms=anchor, window_ms=window_ms, version=graph.get('version'))
    cells = defaultdict(lambda: None)
    weights_row, weights_col = defaultdict(float), defaultdict(float)
    for f in relation_facts(graph, profiles, deviations, environment, anchor, window_ms):
        if service and f['target'] != service:
            continue
        if not _known(f['principal']):
            continue   # anonymous traffic is never a credential row
        col = api_label(f['target'], f['operation'])
        key = (f['principal'], col)
        agg = cells[key] or _Agg(digest(['cell', *key]), 'cell', '')
        agg.add(f, basis); cells[key] = agg
        weights_row[f['principal']] += _width(f, basis); weights_col[col] += _width(f, basis)
    rows = sorted(weights_row, key=lambda r: (-weights_row[r], r))
    cols = sorted(weights_col, key=lambda c: (-weights_col[c], c))
    by_row = defaultdict(set); by_col = defaultdict(set)
    for (r, c) in cells:
        by_row[r].add(c); by_col[c].add(r)
    result['row_total'], result['col_total'] = len(rows), len(cols)
    if order == 'similarity':
        rows, capped = _greedy_order(rows, by_row)
        # Columns follow the barycenter of the rows that use them, so role blocks
        # line up along the diagonal and a page of rows meets its own columns.
        position = {r: i for i, r in enumerate(rows)}
        traffic = {c: i for i, c in enumerate(cols)}
        cols = sorted(cols, key=lambda c: (sum(position[r] for r in by_col[c]) / len(by_col[c]), traffic[c]))
        result['similarity_capped'] = capped
    page_rows = rows[row_offset:row_offset + row_limit]
    page_cols = cols[col_offset:col_offset + col_limit]
    row_pos = {r: i for i, r in enumerate(page_rows)}; col_pos = {c: i for i, c in enumerate(page_cols)}
    result['rows'] = [{'name': r, 'requests_tps': round(weights_row[r], 6), 'apis': len(by_row[r])} for r in page_rows]
    result['cols'] = [{'name': c, 'requests_tps': round(weights_col[c], 6), 'credentials': len(by_col[c])} for c in page_cols]
    for (r, c), agg in cells.items():
        if r in row_pos and c in col_pos:
            v = agg.view()
            result['cells'].append({'row': row_pos[r], 'col': col_pos[c], 'state': v['state'], 'familiarity': v['familiarity'],
                                    'width_tps': v['width_tps'], 'observed_tps': v['observed_tps'], 'expected_tps': v['expected_tps'],
                                    'last_seen_ms': v['last_seen_ms'], 'first_seen_ms': v['first_seen_ms'], 'relationships': v['relationships']})
    result['cells'].sort(key=lambda c: (c['row'], c['col']))
    return result


LIST_COLUMNS = ('caller', 'credential', 'service', 'api')
LIST_MAX = 200
UNUSUAL_MAX = 100
NEIGHBOUR_MAX = 12
FANOUT_MIN_NEW = 3          # a credential reaching this many new APIs in the window is a fan-out
SILENT_RECENT_MS = DAY      # 'silent' lists only established paths that stopped within this long before the window
SEVERITY = {'fanout': 4, 'surge': 3, 'flag': 3, 'new': 2, 'silent': 1}


def _list_values(fact):
    values = _column_values(fact)
    return {c: values[c] for c in LIST_COLUMNS}


def _row(agg, unusual):
    v = agg.view()
    return {'name': v['label'], 'state': v['state'], 'familiarity': v['familiarity'], 'width_tps': v['width_tps'],
            'observed_tps': v['observed_tps'], 'expected_tps': v['expected_tps'], 'relationships': v['relationships'],
            'last_seen_ms': v['last_seen_ms'], 'first_seen_ms': v['first_seen_ms'], 'unusual': unusual}


def _unusual(facts, window_start):
    """Ranked exceptions: credential fan-out (bot-like), TPS surges/flags, new and silenced access."""
    by_cred = defaultdict(list)
    for f in facts:
        if _known(f['principal']):
            by_cred[f['principal']].append(f)
    items, folded = [], set()
    for cred, rel in by_cred.items():
        fresh = [f for f in rel if f['first_seen_ms'] >= window_start and f['observed']]
        if len(fresh) < FANOUT_MIN_NEW:
            continue
        usual = len({api_label(f['target'], f['operation']) for f in rel if f['first_seen_ms'] < window_start})
        folded.update(f['id'] for f in fresh)
        apis = sorted({api_label(f['target'], f['operation']) for f in fresh})
        items.append({'id': digest(['fanout', cred]), 'reason': 'fanout', 'state': 'deviating', 'credential': cred,
                      'caller': None, 'api': None, 'apis': apis[:20], 'new_apis': len(apis), 'usual_apis': usual,
                      'observed_tps': round(sum(f['observed_tps'] for f in fresh), 6), 'expected_tps': None,
                      'first_seen_ms': min(f['first_seen_ms'] for f in fresh), 'last_seen_ms': max(f['last_seen_ms'] for f in fresh),
                      'flags': []})
    for f in facts:
        if f['id'] in folded:
            continue
        if f['state'] == 'deviating':
            reason = 'flag' if f['flags'] and not (f['expected_tps'] and f['observed_tps'] > f['expected_tps']) else 'surge'
        elif f['state'] == 'new':
            reason = 'new'
        elif f['state'] == 'ghost' and f['familiarity'] == 'established' and f['last_seen_ms'] >= window_start - SILENT_RECENT_MS:
            # An established path that stopped within the last day. Older silences (batch paths, dormant
            # relationships) and still-learning paths would flood the list, so they are not listed.
            reason = 'silent'
        else:
            continue
        items.append({'id': f['id'], 'reason': reason, 'state': f['state'],
                      'credential': f['principal'] if _known(f['principal']) else None,
                      'caller': f['caller'] if _known(f['caller']) else None,
                      'api': api_label(f['target'], f['operation']), 'observed_tps': f['observed_tps'],
                      'expected_tps': f['expected_tps'], 'first_seen_ms': f['first_seen_ms'],
                      'last_seen_ms': f['last_seen_ms'], 'flags': f['flags']})
    items.sort(key=lambda i: (-SEVERITY[i['reason']], -(i['observed_tps'] or 0), -i['last_seen_ms'], i['id']))
    return items


def project_lists(graph, profiles, deviations, environment, service, filters=None, window_minutes=60,
                  basis='observed', search=None, offsets=None, limit=100, sort='tps', select_type='', select='', now=None,
                  scope='service'):
    """Faceted Caller / Credential / Service / API lists, unusual access first.

    ``scope='service'`` limits the relationships to one Service (``service``); ``scope='credential'``
    spans every Service and expects a ``credential`` filter, so one user's access can be explored
    across Services. Each column is computed from the relationships matching the filters on the
    OTHER columns, so a selected row keeps its siblings. Built for hundreds of credentials and
    APIs: nothing is drawn as a cross-product, every column is paged on the server.
    """
    filters = {k: v for k, v in (filters or {}).items() if v and k in LIST_COLUMNS}
    if scope == 'service':
        filters.pop('service', None)
    search = {k: (v or '').strip().casefold() for k, v in (search or {}).items()}
    offsets = offsets or {}
    limit = max(1, min(limit, LIST_MAX))
    result = {'status': 'learning', 'environment': environment, 'service': service, 'scope': scope, 'basis': basis,
              'columns': {c: {'items': [], 'total': 0, 'offset': offsets.get(c, 0), 'limit': limit} for c in LIST_COLUMNS},
              'unusual': {'items': [], 'total': 0}, 'selection': None}
    if not graph or graph.get('algorithm') != ALGORITHM:
        return result
    result['status'] = 'active'
    anchor = graph['through_ms'] or (now if now is not None else int(time.time() * 1000))
    window_ms = window_minutes * 60_000
    result.update(as_of_ms=anchor, window_ms=window_ms, window_start_ms=anchor - window_ms, version=graph.get('version'))
    facts = [f for f in relation_facts(graph, profiles, deviations, environment, anchor, window_ms)
             if scope == 'credential' or f['target'] == service]
    values = {f['id']: _list_values(f) for f in facts}
    matches = lambda f, skip='': all(values[f['id']][c] == v for c, v in filters.items() if c != skip)
    scoped = [f for f in facts if matches(f)]
    unusual = _unusual(scoped, anchor - window_ms)
    flagged = defaultdict(set)
    for item in unusual:
        for c in LIST_COLUMNS:
            if item.get(c):
                flagged[c].add(item[c])
        for api in item.get('apis', []):
            flagged['api'].add(api)
    result['unusual'] = {'items': unusual[:UNUSUAL_MAX], 'total': len(unusual)}
    result['relationships_total'] = len(scoped)

    for column in LIST_COLUMNS:
        aggs = {}
        for f in facts:
            name = values[f['id']][column]
            if name is None or not matches(f, column):
                continue
            aggs.setdefault(name, _Agg(digest(['list', column, name]), column, name)).add(f, basis)
        q = search.get(column, '')
        rows = [_row(a, a.label in flagged[column]) for a in aggs.values() if not q or q in a.label.casefold()]
        if sort == 'name':
            rows.sort(key=lambda r: r['name'].casefold())
        else:
            rows.sort(key=lambda r: (not r['unusual'], -r['width_tps'], r['name']))
        # The filtered row always stays visible, wherever it would sort.
        chosen = filters.get(column)
        if chosen and q and chosen.casefold().find(q) < 0 and chosen in aggs:
            rows.insert(0, _row(aggs[chosen], chosen in flagged[column]))
        off = max(0, offsets.get(column, 0))
        result['columns'][column] = {'items': rows[off:off + limit], 'total': len(rows), 'offset': off, 'limit': limit,
                                     'max_tps': max((r['width_tps'] for r in rows), default=0)}

    if select_type in LIST_COLUMNS and select:
        # In credential scope the selection stays inside that user's relationships; a Service page keeps the
        # selected entity's full neighbourhood within the Service.
        pool = [f for f in facts if matches(f, select_type)] if scope == 'credential' else facts
        result['selection'] = _selection(graph, environment, pool, values, select_type, select, basis, anchor - window_ms, scope)
    return result


def _selection(graph, environment, facts, values, kind, name, basis, window_start, scope='service'):
    """One entity with its direct neighbours on each side, IP evidence and a series object."""
    mine = [f for f in facts if values[f['id']][kind] == name]
    if not mine:
        return None
    # One centre and two direct fans; every pair is read from the full relationship records, so a
    # Caller -> API or API -> Caller side is exact, not inferred through the credentials.
    sides = {'caller': ('credential', 'api'), 'credential': ('caller', 'api'), 'service': ('caller', 'api'),
             'api': ('caller', 'credential')}[kind]
    if scope == 'credential':
        # One user across Services: its callers on the left, the Services (or, once a Service is
        # chosen, that Service's APIs) on the right; the credential itself is never a side.
        sides = {'credential': ('caller', 'service'), 'caller': ('service', 'api'), 'service': ('caller', 'api'),
                 'api': ('caller', 'service')}[kind]
    def side(column):
        if column is None:
            return None
        aggs = {}
        for f in mine:
            other = values[f['id']][column]
            if other is not None:
                aggs.setdefault(other, _Agg(digest(['nb', column, other]), column, other)).add(f, basis)
        rows = sorted((_row(a, False) for a in aggs.values()), key=lambda r: (-r['width_tps'], r['name']))
        return {'column': column, 'items': rows[:NEIGHBOUR_MAX], 'total': len(rows)}
    entity = _Agg(digest(['sel', kind, name]), kind, name)
    for f in mine:
        entity.add(f, basis)
    ips = {}
    ids = {f['id'] for f in mine}
    for edge in graph['edges'].values():
        if edge['kind'] == 'peer_on_call' and edge['relationship_id'] in ids:
            ip = graph['nodes'].get(edge['from'])
            if not ip:
                continue
            rec = ips.setdefault(ip['label'], {'ip': ip['label'], 'role': _role(ip.get('role')), 'last_seen_ms': 0})
            rec['last_seen_ms'] = max(rec['last_seen_ms'], edge['last_seen'])
    ip_rows = sorted(ips.values(), key=lambda r: (-r['last_seen_ms'], r['ip']))
    for r in ip_rows:
        r['state'] = 'ghost' if r['last_seen_ms'] < window_start else 'observed'
        r['infrastructure'] = r['role'] in ('load_balancer', 'reverse_proxy', 'nat', 'infrastructure')
    graph_kind = {'caller': 'service', 'credential': 'credential', 'service': 'service', 'api': 'api'}[kind]
    return {'type': kind, 'name': name, **{k: v for k, v in _row(entity, False).items() if k != 'name'},
            'left': side(sides[0]), 'right': side(sides[1]), 'ips': ip_rows[:NEIGHBOUR_MAX], 'ip_total': len(ip_rows),
            'detail_id': node_id(graph['source'], environment, graph_kind, name)}


def jaccard(a, b):
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _greedy_order(items, sets):
    """Greedy nearest-neighbour ordering by Jaccard similarity of access sets.

    Only the busiest MAX_SIMILARITY_ITEMS participate; the rest keep traffic order.
    """
    head, tail = items[:MAX_SIMILARITY_ITEMS], items[MAX_SIMILARITY_ITEMS:]
    if len(head) < 3:
        return items, False
    remaining = list(head[1:]); ordered = [head[0]]
    while remaining:
        last = sets[ordered[-1]]
        best = max(range(len(remaining)), key=lambda i: (jaccard(last, sets[remaining[i]]), -i))
        ordered.append(remaining.pop(best))
    return ordered + tail, bool(tail)

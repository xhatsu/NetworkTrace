"""Bounded behavioral snapshots. A commit marker makes partial writes invisible."""
from __future__ import annotations
import json
import time
import uuid
from collections import defaultdict
from backend.app.repositories.db_context import get_connection
from backend.app.services.learned_behavior import DAY, active_contract

LIMITS = {'max_execution_time': 10, 'max_memory_usage': 268435456, 'max_result_rows': 100001,
          'result_overflow_mode': 'throw'}
# The learning engine is intentionally metrics-only.  Raw APM documents and raw
# ClickHouse traces are not learning inputs; metric_buckets is the canonical
# replaceable five-minute observation source.
SOURCES = ('legacy_metrics',)


def stamp():
    return time.time_ns() // 1000


def encode(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


class BehaviorRepository:
    def __init__(self, db_path=None):
        self.db_path = db_path

    def query(self, sql, parameters=None):
        with get_connection(self.db_path) as db:
            result = db.client.query(sql, parameters=parameters or {}, settings=LIMITS)
            return [dict(zip(result.column_names, row)) for row in result.result_rows]

    def insert(self, table, rows):
        if not rows:
            return
        columns = list(rows[0])
        with get_connection(self.db_path) as db:
            db.client.insert(table, [[r[k] for k in columns] for r in rows], column_names=columns)

    def state(self, source):
        rows = self.query('SELECT data_json FROM behavior_state FINAL WHERE source={s:String}', {'s': source})
        return json.loads(rows[0]['data_json']) if rows else {}

    def save_state(self, source, state):
        self.insert('behavior_state', [{'source': source, 'data_json': encode(state), 'updated_at': stamp()}])

    def stage(self, source, day, generation, observations):
        from backend.app.services.learned_behavior import relationship_id
        version = stamp()
        self.insert('behavior_observations', [dict(source=source, day=day, generation=generation,
                    relationship_id=relationship_id(row), bucket_ms=row['bucket_ms'], data_json=encode(row), updated_at=version)
                    for row in observations])

    def staged(self, source, day, generation):
        rows = self.query('SELECT data_json FROM behavior_observations FINAL WHERE source={s:String} AND day={d:Int64} AND generation={g:String} LIMIT 100001',
                          {'s': source, 'd': day, 'g': generation})
        if len(rows) > 100000:
            raise ValueError('behavior day exceeds 100000 relationship windows')
        return [json.loads(r['data_json']) for r in rows]

    def committed_day(self, source, day):
        rows=self.query('SELECT generation FROM behavior_windows FINAL WHERE source={s:String} AND day={d:Int64}',{'s':source,'d':day})
        return self.staged(source,day,rows[0]['generation']) if rows else []

    def commit_day(self, source, day, generation, summaries, quality):
        version = stamp()
        self.insert('behavior_daily', [dict(source=source, day=day, generation=generation,
                    relationship_id=r['id'], data_json=encode(r), updated_at=version) for r in summaries])
        self.insert('behavior_windows', [dict(source=source, day=day, generation=generation,
                    data_json=encode(quality), updated_at=version)])

    def days(self, source):
        rows = self.query('''SELECT d.data_json FROM behavior_daily AS d FINAL
          INNER JOIN (SELECT source,day,generation FROM behavior_windows FINAL) AS w
          ON d.source=w.source AND d.day=w.day AND d.generation=w.generation
          WHERE d.source={s:String} AND d.day>={start:Int64} LIMIT 100001''',
          {'s': source, 'start': int(time.time()*1000)-90*DAY})
        if len(rows) > 100000:
            raise ValueError('behavior history exceeds 100000 relationship days')
        return [json.loads(r['data_json']) for r in rows]

    def contracts(self, rid=None):
        where = ' WHERE relationship_id={id:String}' if rid else ''
        rows = self.query('SELECT * FROM behavior_contracts'+where+' ORDER BY created_at DESC,event_id DESC LIMIT 10001', {'id': rid or ''})
        if len(rows) > 10000:
            raise ValueError('behavior contract history exceeds 10000 events')
        return rows

    def graph_state(self, source):
        version=self.state(source).get('graph_version')
        if not version:return None
        rows=self.query('SELECT data_json FROM behavior_graph_models FINAL WHERE source={s:String} AND version={v:String}',{'s':source,'v':version})
        return json.loads(rows[0]['data_json']) if rows else None

    def save_graph(self, graph):
        self.insert('behavior_graph_models',[{'source':graph['source'],'version':graph['version'],
                    'data_json':encode(graph),'updated_at':stamp()}])

    def publish(self, source, profiles, deviations, state):
        if len(profiles) > 5000:
            raise ValueError('behavior source exceeds 5000 relationships')
        generation, version = uuid.uuid4().hex, stamp()
        self.insert('behavior_profiles', [dict(source=source,generation=generation,relationship_id=r['id'],data_json=encode(r),updated_at=version) for r in profiles])
        self.insert('behavior_deviations', [dict(source=source,generation=generation,id=r['id'],relationship_id=r['relationship_id'],data_json=encode(r),updated_at=version) for r in deviations])
        self.save_state(source, {**state, 'published_generation': generation, 'published_at': version//1000,
                                 'profile_count': len(profiles), 'deviation_count': len(deviations), 'error': None})

    def items(self, kind, source=None):
        if kind not in {'profiles','deviations'}:
            raise ValueError('invalid collection')
        result = []
        events = defaultdict(list)
        for e in self.contracts():
            events[e['relationship_id']].append(e)
        now = int(time.time()*1000)
        for s in ([source] if source else SOURCES):
            generation = self.state(s).get('published_generation')
            if not generation:
                continue
            rows = self.query(f'SELECT data_json FROM behavior_{kind} FINAL WHERE source={{s:String}} AND generation={{g:String}} LIMIT 5001', {'s':s,'g':generation})
            if len(rows)>5000:
                raise ValueError('behavior snapshot exceeds display bound')
            for row in rows:
                item=json.loads(row['data_json'])
                item['contract']=active_contract(events[item.get('relationship_id',item['id'])],now)
                if kind=='deviations':
                    item['status']='reviewed' if item.get('kind') not in {'traffic_surge','graph_tps_shift'} and item['contract']['state'] in {'approved','temporary'} else 'unreviewed'
                result.append(item)
        return result

    def detail(self, rid):
        return next((r for r in self.items('profiles') if r['id']==rid),None)

    def series(self, rid):
        rows=self.query('''SELECT o.data_json FROM behavior_observations AS o FINAL
            INNER JOIN (SELECT source,day,generation FROM behavior_windows FINAL) AS w
            ON o.source=w.source AND o.day=w.day AND o.generation=w.generation
            WHERE o.relationship_id={id:String} AND o.bucket_ms>={start:Int64}
            ORDER BY o.bucket_ms DESC LIMIT 2016''', {'id':rid,'start':int(time.time()*1000)-7*DAY})
        return list(reversed([json.loads(r['data_json']) for r in rows]))

    def coverage(self):
        result=[]
        for source in SOURCES:
            rows=self.query('SELECT day,data_json FROM behavior_windows FINAL WHERE source={s:String} ORDER BY day',{'s':source})
            quality=[json.loads(r['data_json']) for r in rows]
            result.append({'source':source,**self.state(source),'materialized_days':len(rows),
                           'start':min((r['day'] for r in rows),default=None),
                           'requests':sum(r.get('requests',0) for r in quality),
                           'identified_requests':sum(r.get('identified_requests',0) for r in quality),
                           'caller_observed_requests':sum(r.get('caller_observed_requests',0) for r in quality),
                           'known_environment_requests':sum(r.get('known_environment_requests',0) for r in quality),
                           'collection_coverage':'unknown','sampling_ratio':None})
        return result


    def prune_obsolete_generations(self):
        """Asynchronously reclaim unpublished versions after a reader grace hour."""
        states=[self.state(source) for source in SOURCES]
        pending=[s['pending']['generation'] for s in states if s.get('pending')]
        published=[s['published_generation'] for s in states if s.get('published_generation')]
        graph_versions=[s['graph_version'] for s in states if s.get('graph_version')]
        params={'cutoff':stamp()-3600*1000000,'pending':pending,'published':published,'graphs':graph_versions}
        with get_connection(self.db_path) as db:
            db.client.command('ALTER TABLE behavior_graph_models DELETE WHERE updated_at<{cutoff:UInt64} AND version NOT IN {graphs:Array(String)} SETTINGS mutations_sync=0',parameters=params)
            for table in ('behavior_observations','behavior_daily'):
                db.client.command(f"""ALTER TABLE {table} DELETE WHERE updated_at<{{cutoff:UInt64}}
                    AND generation NOT IN {{pending:Array(String)}}
                    AND (source,day,generation) NOT IN (SELECT source,day,generation FROM behavior_windows FINAL)
                    SETTINGS mutations_sync=0""",parameters=params)
            for table in ('behavior_profiles','behavior_deviations'):
                db.client.command(f"""ALTER TABLE {table} DELETE WHERE updated_at<{{cutoff:UInt64}}
                    AND generation NOT IN {{published:Array(String)}} SETTINGS mutations_sync=0""",parameters=params)

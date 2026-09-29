"""Opt-in integration check creates and drops only its unique test database."""
import os
import time
import uuid
from pathlib import Path
import pytest

pytestmark=pytest.mark.skipif(os.getenv('OTEL_BEHAVIOR_STORAGE_TEST')!='true',reason='explicit isolated ClickHouse integration opt-in')


def test_snapshot_visibility_and_retry_replacement():
    from backend.app.repositories.clickhouse_migrator import get_clickhouse_client
    from backend.app.repositories.behavior_repository import BehaviorRepository
    from backend.app.services.learned_behavior import summarize_day,build_profiles
    from backend.app.services.behavior_sources import normalize
    c=get_clickhouse_client(); database='test_behavior_'+uuid.uuid4().hex[:12]
    c.command('CREATE DATABASE '+database)
    try:
        content=Path('backend/clickhouse_migrations/016_learned_behavior.sql').read_text()+'\n'+Path('backend/clickhouse_migrations/017_online_behavior_graph.sql').read_text()
        for stmt in content.split(';'):
            clean='\n'.join(l for l in stmt.splitlines() if not l.lstrip().startswith('--')).strip()
            if clean:c.command(clean.replace('IF NOT EXISTS behavior_','IF NOT EXISTS '+database+'.behavior_'))
        repo=BehaviorRepository(database);now=int(time.time()*1000);day=now//86400000*86400000
        row=normalize('legacy_metrics',dict(bucket_ms=day,requests=10,principal='synthetic',target='synthetic',operation='/synthetic',caller='synthetic'))
        repo.stage('legacy_metrics',day,'one',[row]);assert repo.days('legacy_metrics')==[]
        repo.commit_day('legacy_metrics',day,'one',summarize_day([row]),{'requests':10})
        assert len(repo.days('legacy_metrics'))==1
        repo.stage('legacy_metrics',day,'one',[row]);assert len(repo.staged('legacy_metrics',day,'one'))==1
        ps,ds=build_profiles(repo.days('legacy_metrics'),[],now)
        from backend.app.services.behavior_graph import advance_graph
        graph=advance_graph(None,repo.days('legacy_metrics'),'legacy_metrics')
        repo.save_graph(graph)
        repo.publish('legacy_metrics',ps,ds,{'mode':'test','graph_version':graph['version']})
        assert repo.graph_state('legacy_metrics')['version']==graph['version']
        assert len(repo.items('profiles'))==1
        assert len(repo.series(ps[0]['id']))==1
        assert repo.coverage()[0]['requests']==10
        repo.commit_day('legacy_metrics',day,'two',[],{'requests':0});assert repo.days('legacy_metrics')==[]
        repo.publish('legacy_metrics',[],[],{'mode':'test'});assert repo.items('profiles')==[]
        repo.prune_obsolete_generations()
        assert repo.items('profiles')==[]
    finally:
        c.command('DROP DATABASE '+database)

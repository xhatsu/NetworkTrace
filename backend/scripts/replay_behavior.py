"""Rebuild bounded shadow memory from retained source data; preserves contracts."""
from __future__ import annotations
import argparse
import fcntl
import json
import time
from pathlib import Path
from backend.config import settings
from backend.app.repositories.behavior_repository import BehaviorRepository, SOURCES
from backend.app.services.behavior_worker import run_source
from backend.app.services.learned_behavior import DAY


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',choices=SOURCES,required=True)
    parser.add_argument('--days',type=int,default=1)
    parser.add_argument('--budget-seconds',type=int,default=45)
    args=parser.parse_args()
    retention={'legacy_metrics':30,'elasticsearch':7,'clickhouse':1}[args.source]
    if not 1<=args.days<=retention or not 1<=args.budget_seconds<=55:
        parser.error(f'days must be 1..{retention}; budget-seconds must be 1..55')
    path=Path(settings.data_dir)/'behavior-learning.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.exit(1,'Behavior worker is active; retry between cycles.\n')
        repo=BehaviorRepository();state=repo.state(args.source)
        # Resume a pending page rather than abandoning it on every invocation.
        start=(int(time.time()*1000)-args.days*DAY+DAY-1)//DAY*DAY
        if not state.get('pending') and state.get('replay_start')!=start:
            repo.save_state(args.source,{**state,'next_day':start,'mode':'backfill','replay_start':start})
        started=time.monotonic()
        while time.monotonic()-started<args.budget_seconds:
            result=run_source(repo,args.source,int(time.time()*1000))
            print(json.dumps(result),flush=True)
            if result['status'] in {'live','current','not_configured','waiting'}:break


if __name__=='__main__':main()

from __future__ import annotations

import argparse
import json
import resource
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analytics import run_jobs
from .fixtures import synthetic_documents
from .ingest import import_documents
from .repository import SQLiteRepository


def timed(fn, repeats: int=9):
    values=[];result=None
    for _ in range(repeats):
        started=time.perf_counter();result=fn();values.append((time.perf_counter()-started)*1000)
    return {"median_ms":round(statistics.median(values),2),"p95_ms":round(sorted(values)[min(len(values)-1,int(len(values)*.95))],2),"result_size":len(json.dumps(result))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--events",type=int,default=2_000_000);parser.add_argument("--services",type=int,default=320);parser.add_argument("--db",type=Path,default=Path("data/benchmark-2m.db"));args=parser.parse_args()
    if args.db.exists(): raise SystemExit(f"Refusing to overwrite existing benchmark database: {args.db}")
    repo=SQLiteRepository(args.db);repo.migrate();anchor=datetime.now(timezone.utc).replace(second=0,microsecond=0)
    started=time.perf_counter();result=import_documents(repo,synthetic_documents(args.events,args.services,anchor),"benchmark-generator",5000);ingest_s=time.perf_counter()-started
    analytics_start=time.perf_counter();jobs=run_jobs(repo);analytics_s=time.perf_counter()-analytics_start
    start_ms=int((anchor-timedelta(hours=3)).timestamp()*1000);end_ms=int((anchor+timedelta(minutes=1)).timestamp()*1000)
    report={"generated_server_transactions":args.events+420,"imported_records_including_client_spans":result.inserted,"services":args.services,
        "ingestion_seconds":round(ingest_s,2),"ingestion_records_per_second":round(result.inserted/ingest_s,1),"analytics_seconds":round(analytics_s,2),
        "peak_process_rss_mb":round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),"sqlite_size_mb":round(sum(p.stat().st_size for p in args.db.parent.glob(args.db.name+'*'))/1024/1024,1),"worker":jobs,
        "queries":{"dashboard_summary":timed(lambda:repo.dashboard_summary(start_ms,end_ms,{})),"dashboard_series":timed(lambda:repo.dashboard_series(start_ms,end_ms,{})),"service_detail":timed(lambda:repo.service_detail("orders-001",start_ms,end_ms),3),"topology":timed(lambda:repo.topology(start_ms,end_ms),9)},
        "topology_render_note":"Browser frame timing must be measured in a graphical browser; API payload timing is reported here."}
    print(json.dumps(report,indent=2))


if __name__=="__main__": main()

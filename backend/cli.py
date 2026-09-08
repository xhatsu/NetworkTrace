from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .fixtures import synthetic_documents
from .repository import SQLiteRepository
from .worker import run_jobs
from .app.repositories.trace_repository import TraceRepository
from .app.services.normalization import normalize_otel_record
from .scripts.import_json import stream_records


def import_documents(
    documents: Iterable[dict], limit: int | None = None, batch_size: int = 2000
) -> dict[str, int]:
    repository = TraceRepository()
    batch = []
    totals = {"read": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
    for document in documents:
        if limit is not None and totals["read"] >= limit:
            break
        totals["read"] += 1
        trace = normalize_otel_record(document)
        if trace is None:
            totals["rejected"] += 1
            continue
        batch.append(trace)
        if len(batch) >= batch_size:
            inserted = repository.insert_traces(batch)
            totals["inserted"] += inserted
            totals["duplicates"] += len(batch) - inserted
            batch.clear()
    if batch:
        inserted = repository.insert_traces(batch)
        totals["inserted"] += inserted
        totals["duplicates"] += len(batch) - inserted
    return totals


def main() -> None:
    parser=argparse.ArgumentParser(description="TraceScope data tools")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("migrate")
    demo=sub.add_parser("demo"); demo.add_argument("--events",type=int,default=24_000); demo.add_argument("--services",type=int,default=36)
    imp=sub.add_parser("import-file"); imp.add_argument("path",type=Path); imp.add_argument("--batch-size",type=int,default=2000); imp.add_argument("--limit",type=int,default=None)
    sub.add_parser("sync-elasticsearch")
    sub.add_parser("analyze")
    args=parser.parse_args(); repo=SQLiteRepository(); repo.migrate()
    if args.command=="migrate": result={"status":"migrated"}
    elif args.command=="demo": result=import_documents(synthetic_documents(args.events,args.services))
    elif args.command=="import-file": result=import_documents(stream_records(args.path),args.limit,args.batch_size)
    elif args.command=="sync-elasticsearch":
        from .elasticsearch import ElasticsearchReader
        result=ElasticsearchReader().sync()
    else: result=run_jobs()
    print(json.dumps(result.__dict__ if hasattr(result,"__dict__") else result,indent=2))


if __name__ == "__main__": main()

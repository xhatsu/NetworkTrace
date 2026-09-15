from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .fixtures import synthetic_documents
from .repository import StorageRepository
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
    clean_logs = sub.add_parser("clean-system-logs")
    clean_logs.add_argument("--truncate", action="store_true", help="Truncate system log tables immediately")
    clean_logs.add_argument("--log-days", type=int, default=None, help="Retention days for general system logs")
    clean_logs.add_argument("--error-days", type=int, default=None, help="Retention days for error logs")
    purge_cmd = sub.add_parser("purge-non-agent-traces")
    purge_cmd.add_argument("--dry-run", action="store_true", help="Count non-agent traces without deleting")
    args=parser.parse_args(); repo=StorageRepository(); repo.migrate()
    if args.command=="migrate": result={"status":"migrated"}
    elif args.command=="demo": result=import_documents(synthetic_documents(args.events,args.services))
    elif args.command=="import-file": result=import_documents(stream_records(args.path),args.limit,args.batch_size)
    elif args.command=="clean-system-logs":
        from .app.repositories.clickhouse_migrator import configure_system_telemetry_retention, truncate_system_logs
        ttl_res = configure_system_telemetry_retention(log_retention_days=args.log_days, error_retention_days=args.error_days)
        trunc_res = truncate_system_logs() if args.truncate else {}
        result = {"ttl_configured": ttl_res, "truncated": trunc_res}
    elif args.command=="purge-non-agent-traces":
        from .app.repositories.db_context import get_connection
        with get_connection() as db:
            non_agent_where = (
                "identity_source != 'legacy_agent' AND "
                "(attributes_json IS NULL OR "
                "(attributes_json NOT LIKE '%capture_source%' AND attributes_json NOT LIKE '%source_probe%'))"
            )
            count = int(db.execute(f"SELECT count() FROM traces WHERE {non_agent_where}").fetchone()[0])
            total = int(db.execute("SELECT count() FROM traces").fetchone()[0])
            if args.dry_run:
                result = {"dry_run": True, "non_agent_traces_found": count, "total_traces": total}
            else:
                if count == total:
                    db.client.command(f"TRUNCATE TABLE {db.database}.traces")
                else:
                    db.client.command(f"ALTER TABLE {db.database}.traces DELETE WHERE {non_agent_where} SETTINGS mutations_sync = 1")
                result = {"purged_non_agent_traces": count, "total_traces_before": total, "total_traces_after": total - count}
    elif args.command=="sync-elasticsearch":
        from .elasticsearch import ElasticsearchReader
        result=ElasticsearchReader().sync()
    else: result=run_jobs()
    print(json.dumps(result.__dict__ if hasattr(result,"__dict__") else result,indent=2))


if __name__ == "__main__": main()

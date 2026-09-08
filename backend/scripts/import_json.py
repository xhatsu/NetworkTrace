#!/usr/bin/env python3
from __future__ import annotations
import argparse
import gzip
import json
import sys
import time
from pathlib import Path
from typing import Iterator

# add parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.services.normalization import normalize_otel_record
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces


def expand_record(obj: dict) -> Iterator[dict]:
    """Unwrap a NetworkTracing shipper envelope, or yield a normal record."""
    events = obj.get("events")
    if not isinstance(events, list):
        yield obj
        return
    node = obj.get("node")
    for event in events:
        if not isinstance(event, dict):
            continue
        if node and "host" not in event:
            event = {**event, "host": node}
        yield event

def stream_records(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        first = f.read(1)
        f.seek(0)
        if first == "[":
            data = json.load(f)
            for obj in data:
                if isinstance(obj, dict):
                    yield from expand_record(obj)
            return
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "hits" in obj and isinstance(obj["hits"], dict):
                    yield from obj["hits"].get("hits", [])
                else:
                    yield from expand_record(obj)
            except Exception:
                continue

def main():
    parser = argparse.ArgumentParser(description="Import trace files into OTel Observability Platform")
    parser.add_argument("path", type=Path, help="Path to JSON, NDJSON, or JSON.GZ file")
    parser.add_argument("--limit", type=int, default=None, help="Max records to import")
    parser.add_argument("--batch-size", type=int, default=2000, help="Batch insertion size")
    args = parser.parse_args()

    repo = TraceRepository()
    batch = []
    total_read = 0
    total_inserted = 0
    min_ts = None
    max_ts = None

    t0 = time.time()
    for doc in stream_records(args.path):
        total_read += 1
        t = normalize_otel_record(doc)
        if t:
            batch.append(t)
            min_ts = min(min_ts, t.timestamp_ms) if min_ts else t.timestamp_ms
            max_ts = max(max_ts, t.timestamp_ms) if max_ts else t.timestamp_ms

        if len(batch) >= args.batch_size:
            total_inserted += repo.insert_traces(batch)
            batch.clear()

        if args.limit and total_read >= args.limit:
            break

    if batch:
        total_inserted += repo.insert_traces(batch)
        batch.clear()

    elapsed = round(time.time() - t0, 2)
    print(f"Imported {total_inserted}/{total_read} traces in {elapsed}s")

    if min_ts and max_ts:
        print("Running aggregation over ingested time window...")
        res = aggregate_traces(min_ts, max_ts + 60_000)
        print(f"Aggregation result: {res}")

if __name__ == "__main__":
    main()

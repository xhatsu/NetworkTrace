#!/usr/bin/env python3
"""
send_traces.py

Sender tool to transmit generated OTel ELK APM trace datasets from the data folder
to the TraceScope platform or OTLP collector.

Modes:
  1. HTTP Mode (--mode http, default):
     Streams and batches records, sending via HTTP POST to /api/v1/ingest.
     Works against local or remote instances, with customizable batch size, limit,
     and delay.
  2. Direct Fast-Import Mode (--mode direct):
     Uses TraceScope's internal repository for high-throughput direct bulk database
     loading and aggregation (ideal for multi-hundred-thousand or million record files).
"""

from __future__ import annotations
import argparse
import gzip
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterator, List, Dict, Any

# Attempt import of TraceScope internals for direct mode
TRACESCOPE_AVAILABLE = False
try:
    project_root = Path(__file__).resolve().parent.parent / "OtelTrace"
    if project_root.exists():
        sys.path.insert(0, str(project_root))
        from backend.app.services.normalization import normalize_otel_record
        from backend.app.repositories.trace_repository import TraceRepository
        from backend.app.services.aggregation import aggregate_traces
        TRACESCOPE_AVAILABLE = True
except Exception:
    TRACESCOPE_AVAILABLE = False


def stream_records(path: str | Path) -> Iterator[Dict[str, Any]]:
    """Yields parsed JSON dictionary records from a .json, .jsonl, or .gz file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt", encoding="utf-8") as f:
        first_char = f.read(1)
        f.seek(0)
        if first_char == "[":
            # JSON array
            data = json.load(f)
            for item in data:
                yield item
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
                    yield obj
            except Exception:
                continue


def send_http_batch(url: str, batch: List[Dict[str, Any]], api_key: str = "") -> Dict[str, Any]:
    """Posts a JSON batch to the ingestion endpoint."""
    payload = json.dumps(batch).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(payload)),
        "User-Agent": "TraceScope-DataSender/1.0"
    }
    if api_key:
        headers["X-API-Key"] = api_key

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        try:
            return json.loads(body)
        except Exception:
            return {"status": "ok", "raw": body}


def run_http_mode(args: argparse.Namespace):
    print("=" * 80)
    print(" TraceScope Trace Sender (HTTP Ingestion Mode)")
    print(f" Target Endpoint:   {args.url}")
    print(f" Source File:       {args.input}")
    print(f" Batch Size:        {args.batch_size:,} records")
    if args.limit:
        print(f" Record Limit:      {args.limit:,}")
    if args.delay:
        print(f" Inter-batch Delay: {args.delay}s")
    print("=" * 80)

    total_read = 0
    total_sent = 0
    total_inserted = 0
    total_rejected = 0
    batch = []
    t0 = time.time()

    for doc in stream_records(args.input):
        total_read += 1
        batch.append(doc)

        if len(batch) >= args.batch_size:
            try:
                res = send_http_batch(args.url, batch, args.api_key)
                inserted = res.get("inserted", len(batch))
                rejected = res.get("rejected", 0)
                total_sent += len(batch)
                total_inserted += inserted
                total_rejected += rejected
            except urllib.error.HTTPError as he:
                err_text = he.read().decode("utf-8", "ignore")
                print(f"\n[!] HTTP Error {he.code}: {err_text[:200]}", file=sys.stderr)
            except Exception as ex:
                print(f"\n[!] Connection Error: {ex}", file=sys.stderr)

            batch.clear()

            elapsed = max(0.001, time.time() - t0)
            rate = total_sent / elapsed
            print(f"\r Sent: {total_sent:>8,} records ({total_inserted:>8,} inserted) | {rate:,.0f} rec/s | Elapsed: {elapsed:.1f}s", end="", flush=True)

            if args.delay > 0:
                time.sleep(args.delay)

        if args.limit and total_read >= args.limit:
            break

    if batch:
        try:
            res = send_http_batch(args.url, batch, args.api_key)
            inserted = res.get("inserted", len(batch))
            rejected = res.get("rejected", 0)
            total_sent += len(batch)
            total_inserted += inserted
            total_rejected += rejected
        except Exception as ex:
            print(f"\n[!] Final Batch Error: {ex}", file=sys.stderr)
        batch.clear()

    total_time = max(0.001, time.time() - t0)
    print("\n" + "-" * 80)
    print(" Transmission Summary:")
    print(f"   - Total Processed:   {total_read:,}")
    print(f"   - Total Sent:        {total_sent:,}")
    print(f"   - Server Inserted:   {total_inserted:,}")
    print(f"   - Server Rejected:   {total_rejected:,}")
    print(f"   - Total Time:        {total_time:.2f}s ({total_sent / total_time:,.0f} rec/s)")
    print("=" * 80)


def run_direct_mode(args: argparse.Namespace):
    if not TRACESCOPE_AVAILABLE:
        print("[!] Direct mode requires TraceScope backend installed in ~/Viettel/OtelTrace.", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print(" TraceScope Trace Sender (Direct Database Bulk Import Mode)")
    print(f" Source File:       {args.input}")
    print(f" Batch Insertion:   {args.batch_size:,} records")
    if args.limit:
        print(f" Record Limit:      {args.limit:,}")
    print("=" * 80)

    db_file = str(project_root / "data" / "tracescope.db")
    repo = TraceRepository(db_path=db_file)
    batch = []
    total_read = 0
    total_inserted = 0
    min_ts = None
    max_ts = None
    t0 = time.time()

    for doc in stream_records(args.input):
        total_read += 1
        t = normalize_otel_record(doc)
        if t:
            batch.append(t)
            min_ts = min(min_ts, t.timestamp_ms) if min_ts is not None else t.timestamp_ms
            max_ts = max(max_ts, t.timestamp_ms) if max_ts is not None else t.timestamp_ms

        if len(batch) >= args.batch_size:
            ins = repo.insert_traces(batch)
            total_inserted += ins
            batch.clear()
            elapsed = max(0.001, time.time() - t0)
            rate = total_inserted / elapsed
            print(f"\r Imported: {total_inserted:>8,} / {total_read:>8,} traces | {rate:,.0f} rec/s | Elapsed: {elapsed:.1f}s", end="", flush=True)

        if args.limit and total_read >= args.limit:
            break

    if batch:
        ins = repo.insert_traces(batch)
        total_inserted += ins
        batch.clear()

    total_time = max(0.001, time.time() - t0)
    print("\n" + "-" * 80)
    print(f" Bulk import complete: {total_inserted:,} / {total_read:,} traces inserted in {total_time:.2f}s ({total_inserted / total_time:,.0f} traces/sec)")

    if min_ts and max_ts and not args.no_aggregate:
        print(f" Computing analytical rollups over window [{min_ts} -> {max_ts}]...")
        res = aggregate_traces(min_ts, max_ts + 60_000)
        print(f" Aggregation result: {res}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Send OTel ELK APM traces from the data folder to TraceScope")
    parser.add_argument("--input", "-i", type=str, default="/home/ubuntu/Viettel/Data/otel_elk_traces_2m.jsonl.gz", help="Path to .jsonl.gz, .jsonl, or .json file")
    parser.add_argument("--mode", "-m", choices=["http", "direct"], default="http", help="Ingestion mode: 'http' (API endpoint) or 'direct' (SQLite fast bulk loader)")
    parser.add_argument("--url", "-u", type=str, default="http://127.0.0.1:30102/api/v1/ingest", help="HTTP Ingestion endpoint URL (for --mode http)")
    parser.add_argument("--api-key", type=str, default="", help="Optional API key header value")
    parser.add_argument("--batch-size", "-b", type=int, default=500, help="Batch size per transmission or insertion")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Max records to send (e.g. 10000 for quick test)")
    parser.add_argument("--delay", "-d", type=float, default=0.0, help="Inter-batch delay in seconds (for rate control)")
    parser.add_argument("--no-aggregate", action="store_true", help="Skip rollup aggregation step in direct mode")
    args = parser.parse_args()

    if args.mode == "http":
        run_http_mode(args)
    else:
        if args.batch_size == 500:
            args.batch_size = 5000
        run_direct_mode(args)


if __name__ == "__main__":
    main()

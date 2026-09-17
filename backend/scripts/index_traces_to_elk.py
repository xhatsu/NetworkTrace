#!/usr/bin/env python3
"""Index generated 1-month traces dataset into Elasticsearch."""
from __future__ import annotations
import gzip
import json
import time
import urllib.request
import sys

ES_URL = "http://127.0.0.1:32073"
INDEX_NAME = "apm-7.17.24-transaction-000001"
FILE_PATH = "/home/ubuntu/Viettel/Data/otel_elk_traces_1month.jsonl.gz"

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else FILE_PATH
    print(f"Streaming from {path} to Elasticsearch ({ES_URL}/{INDEX_NAME})...")
    t0 = time.time()
    batch = []
    total = 0
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            doc = data.get("_source", data)
            doc_id = data.get("_id")
            action = {"index": {"_index": INDEX_NAME}}
            if doc_id:
                action["index"]["_id"] = str(doc_id).replace(":", "_")
            batch.append(json.dumps(action))
            batch.append(json.dumps(doc))
            total += 1
            if len(batch) >= 4000: # 2,000 docs
                payload = "\n".join(batch) + "\n"
                req = urllib.request.Request(
                    f"{ES_URL}/_bulk",
                    data=payload.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    if res.get("errors"):
                        print(f"\nErrors at {total}:", res.get("items", [])[:1], file=sys.stderr)
                batch.clear()
                print(f"\r Indexed {total:,} records...", end="", flush=True)

        if batch:
            payload = "\n".join(batch) + "\n"
            req = urllib.request.Request(
                f"{ES_URL}/_bulk",
                data=payload.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                pass
            batch.clear()

    elapsed = max(0.001, time.time() - t0)
    print(f"\nIndexed {total:,} records in {elapsed:.2f}s ({total / elapsed:,.0f} rec/s).")
    refresh_req = urllib.request.Request(f"{ES_URL}/{INDEX_NAME}/_refresh", method="POST")
    with urllib.request.urlopen(refresh_req, timeout=15):
        pass
    print(f"Refreshed index {INDEX_NAME} successfully.")

if __name__ == "__main__":
    main()

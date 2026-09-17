#!/usr/bin/env python3
"""Synthetic dashboard dataset generator and ClickHouse injector for TraceScope.

Generates a bounded, realistic observability dataset with services, principals,
operations, call graphs, varied latencies, and anomaly patterns.
Injects data via TraceScope's live HTTP ingest API route, backed by ClickHouse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Configuration defaults
DEFAULT_ENDPOINT = os.getenv("OTEL_INGEST_ENDPOINT", "http://127.0.0.1:30102")
DEFAULT_PREFIX = "syn"
DEFAULT_TOTAL_RECORDS = 7200
DEFAULT_BATCH_SIZE = 200
DEFAULT_SEED = 42

SERVICES = [
    "frontend-gateway",
    "auth-service",
    "user-service",
    "order-service",
    "inventory-service",
    "payment-service",
    "billing-service",
    "notification-service",
    "shipping-service",
    "analytics-service",
    "recommendation-service",
    "search-service",
]

PRINCIPALS = [
    "alice",
    "bob",
    "charlie",
    "david",
    "emma",
    "frank",
    "grace",
    "heidi",
    "ivan",
    "judy",
    "mallory",
    "oscar",
    "peggy",
    "trent",
]

OPERATIONS_BY_SERVICE: Dict[str, List[Dict[str, Any]]] = {
    "frontend-gateway": [
        {"op": "GatewayService/route", "method": "GET", "base_lat": 15.0, "lat_std": 5.0},
        {"op": "GatewayService/health", "method": "GET", "base_lat": 4.0, "lat_std": 1.0},
    ],
    "auth-service": [
        {"op": "AuthService/login", "method": "POST", "base_lat": 45.0, "lat_std": 12.0},
        {"op": "AuthService/verifyToken", "method": "POST", "base_lat": 12.0, "lat_std": 3.0},
        {"op": "AuthService/refreshToken", "method": "POST", "base_lat": 25.0, "lat_std": 6.0},
    ],
    "user-service": [
        {"op": "UserService/getProfile", "method": "GET", "base_lat": 22.0, "lat_std": 6.0},
        {"op": "UserService/updateProfile", "method": "PUT", "base_lat": 55.0, "lat_std": 15.0},
    ],
    "order-service": [
        {"op": "OrderService/createOrder", "method": "POST", "base_lat": 85.0, "lat_std": 20.0},
        {"op": "OrderService/getOrder", "method": "GET", "base_lat": 28.0, "lat_std": 8.0},
        {"op": "OrderService/listOrders", "method": "GET", "base_lat": 65.0, "lat_std": 18.0},
        {"op": "OrderService/cancelOrder", "method": "POST", "base_lat": 70.0, "lat_std": 15.0},
    ],
    "inventory-service": [
        {"op": "InventoryService/checkStock", "method": "GET", "base_lat": 18.0, "lat_std": 4.0},
        {"op": "InventoryService/reserveStock", "method": "POST", "base_lat": 38.0, "lat_std": 9.0},
        {"op": "InventoryService/releaseStock", "method": "POST", "base_lat": 32.0, "lat_std": 8.0},
    ],
    "payment-service": [
        {"op": "PaymentService/chargeCard", "method": "POST", "base_lat": 95.0, "lat_std": 25.0},
        {"op": "PaymentService/refund", "method": "POST", "base_lat": 80.0, "lat_std": 20.0},
    ],
    "billing-service": [
        {"op": "BillingService/generateInvoice", "method": "POST", "base_lat": 50.0, "lat_std": 12.0},
        {"op": "BillingService/getInvoice", "method": "GET", "base_lat": 24.0, "lat_std": 6.0},
    ],
    "notification-service": [
        {"op": "NotificationService/sendEmail", "method": "POST", "base_lat": 40.0, "lat_std": 10.0},
        {"op": "NotificationService/sendSMS", "method": "POST", "base_lat": 35.0, "lat_std": 8.0},
    ],
    "shipping-service": [
        {"op": "ShippingService/createShipment", "method": "POST", "base_lat": 65.0, "lat_std": 15.0},
        {"op": "ShippingService/trackPackage", "method": "GET", "base_lat": 20.0, "lat_std": 5.0},
    ],
    "analytics-service": [
        {"op": "AnalyticsService/recordEvent", "method": "POST", "base_lat": 14.0, "lat_std": 3.0},
    ],
    "recommendation-service": [
        {"op": "RecommendationService/getPersonalized", "method": "GET", "base_lat": 75.0, "lat_std": 18.0},
    ],
    "search-service": [
        {"op": "SearchService/queryCatalog", "method": "GET", "base_lat": 90.0, "lat_std": 22.0},
    ],
}

CALL_FLOWS = [
    # (caller, target, list of target op names)
    (None, "frontend-gateway", ["GatewayService/route", "GatewayService/health"]),
    ("frontend-gateway", "auth-service", ["AuthService/login", "AuthService/verifyToken", "AuthService/refreshToken"]),
    ("frontend-gateway", "user-service", ["UserService/getProfile", "UserService/updateProfile"]),
    ("frontend-gateway", "order-service", ["OrderService/createOrder", "OrderService/getOrder", "OrderService/listOrders", "OrderService/cancelOrder"]),
    ("frontend-gateway", "search-service", ["SearchService/queryCatalog"]),
    ("frontend-gateway", "recommendation-service", ["RecommendationService/getPersonalized"]),
    ("order-service", "inventory-service", ["InventoryService/checkStock", "InventoryService/reserveStock", "InventoryService/releaseStock"]),
    ("order-service", "payment-service", ["PaymentService/chargeCard", "PaymentService/refund"]),
    ("order-service", "shipping-service", ["ShippingService/createShipment", "ShippingService/trackPackage"]),
    ("order-service", "notification-service", ["NotificationService/sendEmail", "NotificationService/sendSMS"]),
    ("order-service", "analytics-service", ["AnalyticsService/recordEvent"]),
    ("payment-service", "billing-service", ["BillingService/generateInvoice", "BillingService/getInvoice"]),
    ("user-service", "notification-service", ["NotificationService/sendEmail"]),
]


def generate_trace_id(prefix: str, index: int) -> str:
    h = hashlib.sha256(f"{prefix}-trace-{index}".encode()).hexdigest()[:24]
    return f"{prefix}-{h}"


def generate_span_id(prefix: str, trace_idx: int, span_idx: int) -> str:
    h = hashlib.sha256(f"{prefix}-span-{trace_idx}-{span_idx}".encode()).hexdigest()[:12]
    return f"{prefix}-{h}"


def build_synthetic_records(
    total_records: int,
    prefix: str,
    seed: int,
    reference_time: Optional[int] = None,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    now_sec = reference_time or int(time.time())

    # Time boundaries:
    # 40% in recent dashboard window: [now - 7200s, now - 60s]
    # 60% in historical baseline window: [now - 86400s, now - 7200s]
    recent_cutoff = now_sec - 7200
    baseline_start = now_sec - 86400
    degraded_start = now_sec - 2700  # 45m ago
    degraded_end = now_sec - 900    # 15m ago

    recent_quota = int(total_records * 0.40)
    baseline_quota = total_records - recent_quota

    # Map flow lookup for quick access
    op_meta_by_name = {}
    for svc, op_list in OPERATIONS_BY_SERVICE.items():
        for item in op_list:
            op_meta_by_name[item["op"]] = item

    records: List[Dict[str, Any]] = []
    record_idx = 0

    def create_event(
        trace_idx: int,
        span_idx: int,
        parent_span_id: Optional[str],
        caller: Optional[str],
        target: str,
        op_name: str,
        principal: str,
        ts: int,
        is_degraded: bool,
    ) -> Dict[str, Any]:
        meta = op_meta_by_name[op_name]
        base_lat = meta["base_lat"]
        lat_std = meta["lat_std"]

        # Latency distribution (log-normal approximation)
        if is_degraded and target == "payment-service":
            # Significant tail latency shift for degraded payment service
            lat = rng.uniform(700.0, 2200.0)
            # Higher error rate in degraded window (25%)
            err_roll = rng.random()
            if err_roll < 0.20:
                status = 500
            elif err_roll < 0.25:
                status = 503
            else:
                status = 200
        else:
            lat = max(2.0, rng.gauss(base_lat, lat_std))
            err_roll = rng.random()
            if err_roll < 0.02:
                status = 400
            elif err_roll < 0.035:
                status = 404
            elif err_roll < 0.05:
                status = 500
            else:
                status = 200

        full_service = f"{prefix}-{target}"
        full_caller = f"{prefix}-{caller}" if caller else None
        full_principal = f"{prefix}_user_{principal}"
        trace_id = generate_trace_id(prefix, trace_idx)
        span_id = generate_span_id(prefix, trace_idx, span_idx)

        return {
            "ts": ts,
            "service": full_service,
            "caller_service": full_caller,
            "user": full_principal,
            "path": op_name,
            "method": meta["method"],
            "status": status,
            "duration_ms": round(lat, 2),
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "src": "agent",
            "source": "agent",
            "scheme": "wsse",
        }

    # Generate baseline records
    for i in range(baseline_quota):
        ts = rng.randint(baseline_start, recent_cutoff)
        principal = rng.choice(PRINCIPALS)
        flow = rng.choice(CALL_FLOWS)
        caller, target, op_choices = flow
        op_name = rng.choice(op_choices)

        # Standalone or trace chain
        trace_idx = record_idx
        root_span_id = generate_span_id(prefix, trace_idx, 0)
        parent_id = None if caller == "frontend-gateway" else root_span_id

        evt = create_event(
            trace_idx=trace_idx,
            span_idx=1 if parent_id else 0,
            parent_span_id=parent_id,
            caller=caller,
            target=target,
            op_name=op_name,
            principal=principal,
            ts=ts,
            is_degraded=False,
        )
        records.append(evt)
        record_idx += 1

    # Generate recent records (including degraded anomaly window)
    for i in range(recent_quota):
        ts = rng.randint(recent_cutoff, now_sec - 60)
        is_degraded = degraded_start <= ts <= degraded_end
        principal = rng.choice(PRINCIPALS)

        if is_degraded and rng.random() < 0.45:
            # Bias towards payment service during degraded window to simulate traffic incident
            caller = "order-service"
            target = "payment-service"
            op_name = "PaymentService/chargeCard"
        else:
            flow = rng.choice(CALL_FLOWS)
            caller, target, op_choices = flow
            op_name = rng.choice(op_choices)

        trace_idx = record_idx
        root_span_id = generate_span_id(prefix, trace_idx, 0)
        parent_id = None if caller == "frontend-gateway" else root_span_id

        evt = create_event(
            trace_idx=trace_idx,
            span_idx=1 if parent_id else 0,
            parent_span_id=parent_id,
            caller=caller,
            target=target,
            op_name=op_name,
            principal=principal,
            ts=ts,
            is_degraded=is_degraded,
        )
        records.append(evt)
        record_idx += 1

    # Sort records by timestamp for natural ingestion order
    records.sort(key=lambda r: r["ts"])
    return records


def send_batch(
    endpoint: str,
    batch_id: str,
    node: str,
    records: List[Dict[str, Any]],
    timeout_sec: float = 30.0,
) -> Dict[str, Any]:
    url = f"{endpoint.rstrip('/')}/api/v1/ingest"
    payload = {
        "node": node,
        "events": records,
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Batch-Id": batch_id,
            "User-Agent": "TraceScope-SyntheticGenerator/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        code = resp.getcode()
        raw_resp = resp.read().decode("utf-8")
        parsed = json.loads(raw_resp)
        parsed["http_status_code"] = code
        return parsed


def cleanup_synthetic_data(prefix: str) -> Dict[str, Any]:
    """Delete synthetic traces and batches from ClickHouse directly."""
    try:
        from backend.app.repositories.db_context import get_connection
    except ImportError:
        # Fallback if running outside backend path
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from backend.app.repositories.db_context import get_connection

    with get_connection() as db:
        # Check current counts
        trace_cnt = db.client.query(
            "SELECT count() FROM tracescope.traces WHERE service_name LIKE {pat:String} OR ingest_batch_id LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        ).result_rows[0][0]

        batch_cnt = db.client.query(
            "SELECT count() FROM tracescope.ingest_batches WHERE batch_id LIKE {pat:String} OR node LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        ).result_rows[0][0]

        # Execute mutations
        db.client.command(
            "DELETE FROM tracescope.traces WHERE service_name LIKE {pat:String} OR ingest_batch_id LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        )
        db.client.command(
            "DELETE FROM tracescope.ingest_batches WHERE batch_id LIKE {pat:String} OR node LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        )
        # Also clean up metric_buckets and edges if populated
        db.client.command(
            "DELETE FROM tracescope.metric_buckets WHERE target_service LIKE {pat:String} OR caller_service LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        )
        db.client.command(
            "DELETE FROM tracescope.service_edges WHERE target_service LIKE {pat:String} OR caller_service LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        )
        db.client.command(
            "DELETE FROM tracescope.principal_edges WHERE principal_name LIKE {pat:String}",
            parameters={"pat": f"{prefix}%"},
        )

    return {"deleted_traces": trace_cnt, "deleted_batches": batch_cnt}


def verify_dashboard_data(endpoint: str, prefix: str) -> Dict[str, Any]:
    """Verify live API endpoints and ClickHouse records for synthetic namespace."""
    results: Dict[str, Any] = {}

    def fetch_api(path: str) -> Optional[Dict[str, Any]]:
        url = f"{endpoint.rstrip('/')}{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TraceScope-Verifier/1.0"})
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"error": str(exc)}

    results["health"] = fetch_api("/api/v1/health")
    results["overview"] = fetch_api("/api/v1/overview")
    results["services"] = fetch_api("/api/v1/services")
    results["principals"] = fetch_api("/api/v1/principals")
    results["topology"] = fetch_api("/api/v1/topology")
    results["anomalies"] = fetch_api("/api/v1/anomalies")

    # Direct ClickHouse check
    try:
        from backend.app.repositories.db_context import get_connection
        with get_connection() as db:
            ch_traces = db.client.query(
                "SELECT count(), min(timestamp_ms), max(timestamp_ms) FROM tracescope.traces WHERE service_name LIKE {pat:String}",
                parameters={"pat": f"{prefix}-%"},
            ).result_rows[0]
            ch_services = db.client.query(
                "SELECT DISTINCT service_name FROM tracescope.traces WHERE service_name LIKE {pat:String}",
                parameters={"pat": f"{prefix}-%"},
            ).result_rows
            ch_principals = db.client.query(
                "SELECT DISTINCT principal_name FROM tracescope.traces WHERE principal_name LIKE {pat:String}",
                parameters={"pat": f"{prefix}_user_%"},
            ).result_rows
            results["clickhouse"] = {
                "trace_count": ch_traces[0],
                "min_timestamp_ms": ch_traces[1],
                "max_timestamp_ms": ch_traces[2],
                "service_count": len(ch_services),
                "principal_count": len(ch_principals),
                "services": [r[0] for r in ch_services],
                "principals": [r[0] for r in ch_principals],
            }
    except Exception as exc:
        results["clickhouse"] = {"error": str(exc)}

    return results


def run_worker_cycle() -> Dict[str, Any]:
    """Run one aggregation cycle to populate metric_buckets and baselines."""
    try:
        from backend.worker import run_jobs
        return run_jobs()
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="TraceScope synthetic dashboard data generator")
    parser.add_argument("--mode", choices=["dry-run", "execute", "cleanup", "verify", "aggregate"], default="dry-run")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"TraceScope endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Records per batch (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--total-records", type=int, default=DEFAULT_TOTAL_RECORDS, help=f"Total records (default: {DEFAULT_TOTAL_RECORDS})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed for deterministic generation")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"Namespace prefix (default: {DEFAULT_PREFIX})")
    parser.add_argument("--pacing-ms", type=int, default=50, help="Pacing between batches in milliseconds")
    parser.add_argument("--node", default="syn-agent-probe-01", help="Agent node name for batch envelope")
    parser.add_argument("--trigger-worker", action="store_true", help="Trigger worker cycle after injection")

    args = parser.parse_args()

    # Bound dataset size strictly between 5,000 and 10,000
    total_records = max(5000, min(10000, args.total_records))
    batch_size = max(50, min(1000, args.batch_size))

    if args.mode == "cleanup":
        print(f"=== CLEANUP SYNTHETIC DATA (Prefix: {args.prefix}) ===")
        res = cleanup_synthetic_data(args.prefix)
        print(f"Cleanup result: {json.dumps(res, indent=2)}")
        return

    if args.mode == "aggregate":
        print("=== TRIGGERING ANALYTICAL WORKER CYCLE ===")
        res = run_worker_cycle()
        print(f"Worker cycle result: {json.dumps(res, indent=2)}")
        return

    if args.mode == "verify":
        print(f"=== VERIFYING DASHBOARD DATA (Prefix: {args.prefix}) ===")
        res = verify_dashboard_data(args.endpoint, args.prefix)
        print(json.dumps(res, indent=2, default=str))
        return

    print(f"=== GENERATING SYNTHETIC DATASET ===")
    print(f"Target records : {total_records}")
    print(f"Batch size     : {batch_size}")
    print(f"Seed           : {args.seed}")
    print(f"Prefix         : {args.prefix}")
    print(f"Endpoint       : {args.endpoint}")
    print(f"Mode           : {args.mode}")

    records = build_synthetic_records(
        total_records=total_records,
        prefix=args.prefix,
        seed=args.seed,
    )

    services_seen = sorted({r["service"] for r in records})
    principals_seen = sorted({r["user"] for r in records})
    operations_seen = sorted({r["path"] for r in records})
    min_ts = min(r["ts"] for r in records)
    max_ts = max(r["ts"] for r in records)
    status_counts: Dict[int, int] = {}
    for r in records:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    print("\n--- Dataset Summary ---")
    print(f"Generated records  : {len(records)}")
    print(f"Unique services    : {len(services_seen)} (Required >= 10)")
    print(f"Unique principals  : {len(principals_seen)} (Required >= 12)")
    print(f"Unique operations  : {len(operations_seen)} (Required >= 20)")
    print(f"Time span (sec)    : {max_ts - min_ts} s (~{(max_ts - min_ts)/3600:.1f} hours)")
    print(f"Status breakdown   : {status_counts}")
    print(f"First timestamp    : {min_ts} ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(min_ts))})")
    print(f"Last timestamp     : {max_ts} ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(max_ts))})")

    if args.mode == "dry-run":
        print("\n[DRY-RUN] Validation passed. Payload not sent to live endpoint.")
        print("To execute injection, rerun with --mode execute")
        return

    # Execute injection
    print(f"\n=== INJECTING TO {args.endpoint}/api/v1/ingest ===")
    batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    print(f"Total batches: {len(batches)}")

    total_accepted = 0
    total_inserted = 0
    total_duplicates = 0
    start_time = time.monotonic()

    for idx, batch in enumerate(batches, 1):
        batch_id = f"{args.prefix}-batch-{args.seed:04d}-{idx:04d}"
        try:
            resp = send_batch(
                endpoint=args.endpoint,
                batch_id=batch_id,
                node=args.node,
                records=batch,
            )
            inserted = int(resp.get("inserted", 0))
            received = int(resp.get("received", 0))
            duplicate = bool(resp.get("duplicate", False))
            total_accepted += received
            total_inserted += inserted
            if duplicate:
                total_duplicates += 1

            print(
                f"Batch {idx:03d}/{len(batches):03d} | "
                f"ID: {batch_id} | "
                f"Status: {resp.get('http_status_code', 200)} | "
                f"Received: {received} | "
                f"Inserted: {inserted} | "
                f"Duplicate: {duplicate}"
            )
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            print(f"ERROR Batch {idx:03d}/{len(batches):03d} failed with HTTP {exc.code}: {err_body}")
            sys.exit(1)
        except Exception as exc:
            print(f"ERROR Batch {idx:03d}/{len(batches):03d} failed: {exc}")
            sys.exit(1)

        if args.pacing_ms > 0:
            time.sleep(args.pacing_ms / 1000.0)

    elapsed = round(time.monotonic() - start_time, 2)
    print("\n--- Injection Results ---")
    print(f"Total batches sent : {len(batches)}")
    print(f"Total rows accepted: {total_accepted}")
    print(f"Total rows inserted: {total_inserted}")
    print(f"Duplicate batches  : {total_duplicates}")
    print(f"Elapsed time       : {elapsed} s ({round(total_accepted / max(0.01, elapsed), 1)} rows/s)")

    if args.trigger_worker:
        print("\n=== TRIGGERING WORKER AGGREGATION CYCLE ===")
        worker_res = run_worker_cycle()
        print(f"Worker aggregation complete: {json.dumps(worker_res, indent=2)}")

    print("\n=== RUNNING VERIFICATION ===")
    v_res = verify_dashboard_data(args.endpoint, args.prefix)
    print(json.dumps(v_res, indent=2, default=str))


if __name__ == "__main__":
    main()

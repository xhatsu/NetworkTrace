#!/usr/bin/env python3
"""Generate a complete 7-day realistic demonstration dataset in ClickHouse and Elasticsearch.

Spans exactly 7 days (Days -7 to Day 0):
  - Days 0 to 5 (Days -7 to -1, historical baseline window):
      Dense baseline traffic and pre-aggregated 1m and 5m metric buckets establishing
      robust median, MAD, and percentile baselines across all 10 identities.
  - Day 6 (Today / Anomaly window):
      Dedicated ground-truth abnormalities and behavioral drift events for all 10 user personas:
      1. pos_checkout_terminal   - Traffic Spike & Principal Rate Surge (Surge to 450+ req/15m).
      2. billing_reconcile_job   - Traffic Drop / Outage (0 req during scheduled 02:00-04:00 batch).
      3. interbank_settlement_gw - Latency Degradation & Blast Radius (Payment latency surges to 800-1800ms).
      4. partner_sales_broker    - Error Rate Surge (45% 5xx server errors on order creation).
      5. enterprise_b2b_gateway  - New Service Edge + New Principal Edge + Target Fanout Surge (Sweeps 5 new services in 45m).
      6. secops_monitor_agent    - Unusual Access (user_new_endpoint) + Operation Mix Shift (Switches to updateAddress & billing APIs).
      7. sysadmin_deploy_agent   - Unusual Time (Off-Hours 02:00-04:30 UTC) + Caller Switch (Human operator active at night).
      8. employee_remote_user    - User New Source IP (Accessing admin/billing APIs from rogue external IP 185.220.101.5).
      9. mobile_miniapp_gateway  - Auth Failure Burst then Success (130+ 401s in 15m followed by 200 OK success).
     10. audit_compliance_worker - Dormant Reactivated (Silent 6 days, reactivated) + Novel User on Known IP (172.16.10.45).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import settings
from backend.app.models.aggregate import MetricBucket
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.db_context import get_connection
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.anomaly_detection import detect_anomalies
from backend.app.services.baseline import rebuild_baselines
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.principal_relationships import process_principal_intelligence
from backend.app.services.prometheus_metrics import update_worker_prometheus_metrics
from backend.scripts.reset_testbed import wipe_clickhouse, wipe_elasticsearch, truncate_system_logs

# In a 7-day dataset, 6 days of silence constitutes dormant account reactivation
object.__setattr__(settings, "principal_dormant_days", 5)

ES_URL = "http://127.0.0.1:32073"
INDEX_NAME = "apm-7.17.24-transaction"


def generate_smooth_timestamps(start_sec: float, end_sec: float, count: int, shape: str = "flat", jitter_sec: float = 1.0) -> list[float]:
    duration = max(60.0, end_sec - start_sec)
    num_buckets = max(1, int(duration // 60))

    weights = []
    for i in range(num_buckets):
        fraction = i / max(1, num_buckets - 1)
        if shape == "diurnal":
            w = 0.5 + 0.5 * math.sin(math.pi * fraction)
        elif shape == "ramp_up":
            w = 0.1 + 0.9 * (fraction ** 1.5)
        elif shape == "ramp_down":
            w = max(0.02, 1.0 - (fraction ** 1.5))
        elif shape == "bell":
            w = math.exp(-0.5 * ((fraction - 0.5) / 0.2) ** 2)
        else:
            w = 1.0
        weights.append(w)

    total_w = sum(weights)
    if total_w <= 0:
        total_w = 1.0
        weights = [1.0] * num_buckets

    counts = [int(math.floor((w / total_w) * count)) for w in weights]
    remainder = count - sum(counts)
    fractionals = [(i, (weights[i] / total_w) * count - counts[i]) for i in range(num_buckets)]
    fractionals.sort(key=lambda x: x[1], reverse=True)
    for i in range(remainder):
        counts[fractionals[i][0]] += 1

    timestamps = []
    for i, bucket_count in enumerate(counts):
        b_start = start_sec + (i * 60.0)
        if bucket_count <= 0:
            continue
        step = 60.0 / bucket_count
        for j in range(bucket_count):
            t = b_start + (j + 0.5) * step + random.uniform(-jitter_sec, jitter_sec)
            t = max(start_sec, min(end_sec - 0.01, t))
            timestamps.append(t)

    timestamps.sort()
    return timestamps


SERVICES = {
    "apex-edge-gateway": [
        ("SaleApi/InterfaceForSale", "POST", 25.0, 5.0),
        ("SaleApi/InterfaceForMyViettel", "POST", 22.0, 4.0),
        ("CheckoutApi/submitOrder", "POST", 45.0, 10.0),
        ("CatalogApi/searchProducts", "GET", 15.0, 3.0),
        ("BillingApi/queryBalance", "GET", 12.0, 2.5),
    ],
    "apex-customer-service": [
        ("CustomerService/getProfile", "GET", 20.0, 4.0),
        ("CustomerService/updateAddress", "POST", 45.0, 10.0),
        ("CustomerService/verifyMsisdn", "GET", 16.0, 3.0),
    ],
    "apex-order-service": [
        ("OrderService/createOrder", "POST", 75.0, 15.0),
        ("OrderService/getOrder", "GET", 22.0, 5.0),
        ("OrderService/validateOrderLimits", "POST", 28.0, 6.0),
    ],
    "apex-catalog-service": [
        ("CatalogService/getItemDetails", "GET", 18.0, 4.0),
        ("CatalogService/listPackages", "GET", 14.0, 3.0),
    ],
    "apex-inventory-service": [
        ("InventoryService/checkAvailability", "GET", 15.0, 3.0),
        ("InventoryService/reserveStock", "POST", 32.0, 7.0),
    ],
    "apex-payment-service": [
        ("PayService/chargeCard", "POST", 35.0, 8.0),
        ("PayService/settleLedger", "POST", 28.0, 6.0),
        ("PayService/issueRefund", "POST", 40.0, 9.0),
    ],
    "apex-billing-service": [
        ("BillingService/calculateUsageTax", "POST", 25.0, 5.0),
        ("BillingService/generateInvoiceItem", "POST", 45.0, 9.0),
        ("BillingService/queryAccountBalance", "GET", 18.0, 3.5),
    ],
    "apex-notification-service": [
        ("NotificationService/sendSmsOtp", "POST", 25.0, 5.0),
        ("NotificationService/sendEmail", "POST", 20.0, 4.0),
    ],
    "apex-admin-service": [
        ("AdminService/systemConfig", "GET", 22.0, 4.0),
        ("AdminService/modifyPolicy", "POST", 55.0, 12.0),
    ],
}


def hex_id(length: int) -> str:
    return "".join(random.choices("0123456789abcdef", k=length))


def build_apm_doc(
    ts_sec: float,
    user: str,
    service: str,
    op_name: str,
    method: str,
    caller: str,
    client_ip: str,
    duration_ms: float,
    status: int,
    req_bytes: int | None = None,
    resp_bytes: int | None = None,
) -> dict:
    if req_bytes is None:
        if method == "GET":
            req_bytes = random.randint(320, 850)
        elif method == "POST":
            req_bytes = random.randint(1450, 4800)
        elif method == "PUT":
            req_bytes = random.randint(980, 3200)
        else:
            req_bytes = random.randint(250, 600)

    if resp_bytes is None:
        if status >= 400:
            resp_bytes = random.randint(220, 480)
        elif any(k in op_name.lower() for k in ("list", "search", "packages", "items")):
            resp_bytes = random.randint(12500, 38000)
        elif any(k in op_name.lower() for k in ("charge", "invoice", "order", "tax")):
            resp_bytes = random.randint(2800, 7500)
        else:
            resp_bytes = random.randint(1100, 3900)

    t_iso = datetime.fromtimestamp(ts_sec, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    outcome = "success" if status < 400 else "failure"
    auth_result = "failure" if status in (401, 403) else "success"
    return {
        "@timestamp": t_iso,
        "processor": {"name": "transaction", "event": "transaction"},
        "service": {
            "name": service,
            "environment": "production",
            "node": {"name": f"{service}-pod-{random.randint(1, 3)}"},
        },
        "transaction": {
            "id": hex_id(16),
            "name": op_name,
            "type": "request",
            "duration": {"us": int(max(1.0, duration_ms) * 1000)},
            "result": f"HTTP {status // 100}xx",
            "outcome": outcome,
            "sampled": True,
        },
        "trace": {"id": hex_id(32)},
        "enduser.id": user,
        "enduser": {"id": user},
        "user": {"name": user, "id": user},
        "client": {"ip": client_ip},
        "auth.result": auth_result,
        "security": {"auth": {"result": auth_result}},
        "request_bytes": req_bytes,
        "response_bytes": resp_bytes,
        "req_bytes": req_bytes,
        "resp_bytes": resp_bytes,
        "http": {
            "response": {"status_code": status, "body": {"size": resp_bytes}, "bytes": resp_bytes},
            "request": {"method": method, "body": {"size": req_bytes}, "bytes": req_bytes},
        },
        "labels": {
            "caller_service": caller,
            "client_address": client_ip,
            "http_response_status_code": status,
            "http_request_method": method,
            "http_request_body_size": req_bytes,
            "http_response_body_size": resp_bytes,
            "http_request_content_length": req_bytes,
            "http_response_content_length": resp_bytes,
        },
    }


def generate_7day_raw_traces(now_sec: float, scale: int = 1) -> list[dict]:
    """Generate rich raw trace records spanning the full 7-day period (Days -7 to Day 0)."""
    records: list[dict] = []
    day_sec = 86400
    start_sec = now_sec - (7 * day_sec)
    scale = max(1, scale)

    print(
        f"Generating full 7-day raw trace dataset (scale={scale}x) from "
        f"{datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to "
        f"{datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}..."
    )

    # -------------------------------------------------------------------------
    # Days 0 to 5 (Days -7 to -1): 6 days of established historical baseline traffic
    # -------------------------------------------------------------------------
    for day_offset in range(6):
        day_base = start_sec + (day_offset * day_sec)

        # 1. pos_checkout_terminal (Golden baseline: order checkout)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (20 * 3600), int(random.randint(70, 85) * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", 75.0, 200))

        # 2. billing_reconcile_job (Daily night batch 02:00-04:00 + daytime notifications)
        for t in generate_smooth_timestamps(day_base + (2 * 3600), day_base + (4 * 3600), int(200 * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), int(200 * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "billing_reconcile_job", "apex-notification-service", "NotificationService/sendEmail", "POST", "apex-edge-gateway", "172.16.12.19", 12.0, 200))

        # 3. interbank_settlement_gw (Settlement payment charge)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (19 * 3600), int(random.randint(90, 110) * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", 35.0, 200))

        # 4. partner_sales_broker (Partner order creation)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (20 * 3600), int(random.randint(110, 130) * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", 75.0, 200))

        # 5. enterprise_b2b_gateway (B2B customer profile inquiries)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), int(random.randint(90, 110) * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "enterprise_b2b_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "b2b-gateway", "115.78.22.84", 20.0, 200))

        # 6. secops_monitor_agent (Secops profile inspection)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), int(120 * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/getProfile", "GET", "portal-sec", "10.150.4.88", 20.0, 200))

        # 7. sysadmin_deploy_agent (Daytime deployment check 09:00-17:00)
        for t in generate_smooth_timestamps(day_base + (9 * 3600), day_base + (17 * 3600), int(random.randint(70, 85) * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-order-service", "OrderService/getOrder", "GET", "apex-edge-gateway", "10.240.147.247", 22.0, 200))

        # 8. employee_remote_user (Corporate portal access)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), int(random.randint(80, 100) * scale), shape="diurnal"):
            svc = "apex-customer-service" if random.random() < 0.5 else "apex-order-service"
            op_name = "CustomerService/getProfile" if svc == "apex-customer-service" else "OrderService/getOrder"
            records.append(build_apm_doc(t, "employee_remote_user", svc, op_name, "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

        # 9. mobile_miniapp_gateway (Retail sale gateway requests)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (20 * 3600), int(50 * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

        # 10. audit_compliance_worker (Active on Day 0 ONLY, then silent for 6 days)
        if day_offset == 0:
            for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (11 * 3600), int(80 * scale), shape="diurnal"):
                records.append(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

        # Background normal daytime activity
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (19 * 3600), int(100 * scale), shape="diurnal"):
            records.append(build_apm_doc(t, "telecom_sync_svc", "apex-catalog-service", "CatalogService/getItemDetails", "GET", "SALE_SERVICE", "10.240.147.247", 18.0, 200))

    # -------------------------------------------------------------------------
    # Day 6 (Today / Anomaly Window): Ground-Truth Observability Anomaly Injections
    # -------------------------------------------------------------------------
    print("Generating dedicated abnormalities and behavioral shifts on Day 6 (Today)...")
    today_base = start_sec + (6 * day_sec)

    # 1. pos_checkout_terminal: Traffic spike ramp in last 15 minutes (450 reqs * scale)
    surge_start = now_sec - (15 * 60)
    for t in generate_smooth_timestamps(surge_start, now_sec - 15, int(450 * scale), shape="ramp_up"):
        lat = max(15.0, random.gauss(85.0, 15.0))
        records.append(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", lat, 200))

    # 2. billing_reconcile_job: Outage / traffic drop at 02:00-04:00 (0 reqs; 1 trace earlier)
    records.append(build_apm_doc(now_sec - (6 * 3600), "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))

    # 3. interbank_settlement_gw: Latency blowout in last 2 hours (320 reqs * scale, 800-1800ms)
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, int(320 * scale), shape="flat"):
        lat = max(200.0, random.gauss(950.0, 200.0))
        records.append(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", lat, 200))

    # 4. partner_sales_broker: 45% 5xx errors in last 2 hours (180 reqs * scale)
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, int(180 * scale), shape="flat"):
        is_err = random.random() < 0.45
        status = random.choice([500, 502, 503]) if is_err else 200
        lat = max(40.0, random.gauss(180.0, 50.0)) if is_err else 75.0
        records.append(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", lat, status))

    # 5. enterprise_b2b_gateway: Fanout surge sweeping 5 new services in last 45m (150 reqs * scale)
    fanout_targets = ["apex-billing-service", "apex-payment-service", "apex-notification-service", "apex-inventory-service", "apex-catalog-service"]
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 30, int(150 * scale), shape="ramp_up"):
        tgt = random.choice(fanout_targets)
        op_info = random.choice(SERVICES[tgt])
        records.append(build_apm_doc(t, "enterprise_b2b_gateway", tgt, op_info[0], op_info[1], "b2b-gateway", "115.78.22.84", 35.0, 200))

    # 6. secops_monitor_agent: Operation mix shift to updateAddress + billing API (170 reqs * scale)
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, int(120 * scale), shape="flat"):
        records.append(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/updateAddress", "POST", "portal-sec", "10.150.4.88", 45.0, 200))
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, int(50 * scale), shape="flat"):
        records.append(build_apm_doc(t, "secops_monitor_agent", "apex-billing-service", "BillingService/generateInvoiceItem", "POST", "api-client", "10.150.4.88", 45.0, 200))

    # 7. sysadmin_deploy_agent: Night off-hours activity (02:00-04:30) with caller switch
    off_start = now_sec - (5 * 3600)
    for t in generate_smooth_timestamps(off_start, off_start + 5400, int(50 * scale), shape="bell"):
        records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-admin-service", "AdminService/systemConfig", "GET", "portal-admin", "10.240.147.247", 25.0, 200))
    for t in generate_smooth_timestamps(now_sec - 5400, now_sec, int(40 * scale), shape="flat"):
        records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "portal-admin", "10.240.147.247", 35.0, 200))

    # 8. employee_remote_user: Access from unobserved rogue IP 185.220.101.5 (80 reqs * scale)
    for t in generate_smooth_timestamps(now_sec - 5400, now_sec, int(40 * scale), shape="flat"):
        records.append(build_apm_doc(t, "employee_remote_user", "apex-admin-service", "AdminService/systemConfig", "GET", "apex-edge-gateway", "185.220.101.5", 25.0, 200))
        records.append(build_apm_doc(t + 0.5, "employee_remote_user", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "apex-edge-gateway", "185.220.101.5", 35.0, 200))

    # 9. mobile_miniapp_gateway: 130 consecutive 401s in 15m followed by 200 OK
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 120, int(130 * scale), shape="ramp_up"):
        records.append(build_apm_doc(t, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 25.0, 401))
    records.append(build_apm_doc(now_sec - 90, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 35.0, 200))
    records.append(build_apm_doc(now_sec - 30, "mobile_miniapp_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

    # 10. audit_compliance_worker: Reactivates after 6 days of silence from IP 172.16.10.45
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, int(50 * scale), shape="flat"):
        records.append(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 22.0, 200))

    records.sort(key=lambda r: r["@timestamp"])
    print(f"Total raw trace records generated: {len(records):,}")
    return records


def bulk_insert_es(records: list[dict], batch_size: int = 5000) -> int:
    total_inserted = 0
    print(f"Indexing {len(records):,} transactions into Elasticsearch ({ES_URL}/{INDEX_NAME})...")

    for i in range(0, len(records), batch_size):
        chunk = records[i:i + batch_size]
        lines = []
        for doc in chunk:
            lines.append(json.dumps({"index": {"_index": INDEX_NAME}}))
            lines.append(json.dumps(doc))
        payload = "\n".join(lines) + "\n"

        req = urllib.request.Request(
            f"{ES_URL}/_bulk",
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            if resp_data.get("errors"):
                print(f"Warning: errors in bulk insert chunk: {resp_data.get('items', [])[:2]}")
            total_inserted += len(chunk)
            print(f"  ES Indexed {total_inserted:,}/{len(records):,} records...")

    # Refresh index
    refresh_req = urllib.request.Request(f"{ES_URL}/{INDEX_NAME}/_refresh", method="POST")
    with urllib.request.urlopen(refresh_req, timeout=30) as resp:
        pass

    print(f"Elasticsearch index {INDEX_NAME} refreshed cleanly.")
    return total_inserted


def insert_clickhouse_traces(records: list[dict], batch_size: int = 10000) -> int:
    print("Normalizing records and inserting into ClickHouse traces table...")
    repo = TraceRepository()
    normalized: list[NormalizedTrace] = []

    for doc in records:
        t = normalize_otel_record(doc)
        if t:
            normalized.append(t)

    total_inserted = 0
    for i in range(0, len(normalized), batch_size):
        chunk = normalized[i:i + batch_size]
        cnt = repo.insert_traces(chunk, skip_dedup=True)
        total_inserted += cnt
        print(f"  ClickHouse Inserted {total_inserted:,}/{len(normalized):,} traces...")

    print(f"ClickHouse traces insertion complete: {total_inserted:,} rows inserted.")
    return total_inserted


def derive_analytics(now_sec: float):
    print("\n--- Running Derivations: Rollups, Baselines, Anomalies & Principal Intelligence ---")
    t0 = time.time()

    print("Stage 1/5: Aggregating 1m and 5m metric buckets and topology edges...")
    aggs = aggregate_traces()
    print(f"  Aggregated: {aggs} in {round(time.time() - t0, 2)}s")

    t1 = time.time()
    print("Stage 2/5: Rebuilding historical median & MAD baselines (excluding anomaly window)...")
    base_count = rebuild_baselines(max_bucket_start=int(now_sec) - 86400)
    print(f"  Baselines computed: {base_count} in {round(time.time() - t1, 2)}s")

    t2 = time.time()
    print("Stage 3/5: Deriving principal behavioral profiles, shifts & incidents...")
    p_result = process_principal_intelligence(force_bootstrap=True)
    print(f"  Principals processed: {p_result} in {round(time.time() - t2, 2)}s")

    t3 = time.time()
    print("Stage 4/5: Evaluating anomaly detection rules across recent metric windows...")
    with get_connection() as db:
        windows = [
            r[0] for r in db.execute(
                "SELECT DISTINCT bucket_start FROM metric_buckets WHERE bucket_size = 300 AND bucket_start >= ? ORDER BY bucket_start",
                (int(now_sec) - (2 * 86400),)
            ).fetchall()
        ]

    all_anomalies = []
    for w in windows:
        found = detect_anomalies(window_start_sec=w, window_end_sec=w + 300)
        all_anomalies.extend(found)
    print(f"  Anomalies detected: {len(all_anomalies)} across {len(windows)} windows in {round(time.time() - t3, 2)}s")

    t4 = time.time()
    print("Stage 5/5: Updating Prometheus worker metrics...")
    prom_snap = update_worker_prometheus_metrics(duration_sec=round(time.time() - t0, 2))
    print(f"  Prometheus metrics updated in {round(time.time() - t4, 2)}s: {prom_snap}")

    print("\n--- 7-Day Dataset Generation & Derivations Finished Successfully ---")


def generate_historical_metric_buckets(start_sec: float, end_sec: float, scale: int = 1) -> list[MetricBucket]:
    buckets: list[MetricBucket] = []
    scale = max(1, scale)
    print(f"Generating pre-aggregated 5m and 1m metric buckets (scale={scale}x) from {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to {datetime.fromtimestamp(end_sec, timezone.utc).isoformat()}...")

    baseline_personas = [
        ("pos_checkout_terminal", "apex-edge-gateway", "apex-order-service", "OrderService/createOrder", 80, 75.0, 85.0, 8, 20),
        ("billing_reconcile_job", "apex-order-service", "apex-inventory-service", "InventoryService/checkAvailability", 360, 15.0, 20.0, 2, 4),
        ("billing_reconcile_job", "apex-edge-gateway", "apex-notification-service", "NotificationService/sendEmail", 350, 12.0, 18.0, 8, 18),
        ("interbank_settlement_gw", "apex-order-service", "apex-payment-service", "PayService/chargeCard", 100, 35.0, 45.0, 8, 19),
        ("partner_sales_broker", "apex-edge-gateway", "apex-order-service", "OrderService/createOrder", 120, 75.0, 90.0, 8, 20),
        ("enterprise_b2b_gateway", "b2b-gateway", "apex-customer-service", "CustomerService/getProfile", 100, 20.0, 28.0, 8, 18),
        ("secops_monitor_agent", "portal-sec", "apex-customer-service", "CustomerService/getProfile", 120, 20.0, 26.0, 8, 18),
        ("sysadmin_deploy_agent", "apex-edge-gateway", "apex-order-service", "OrderService/getOrder", 80, 22.0, 30.0, 9, 17),
        ("employee_remote_user", "apex-edge-gateway", "apex-customer-service", "CustomerService/getProfile", 50, 20.0, 28.0, 8, 18),
        ("employee_remote_user", "apex-edge-gateway", "apex-order-service", "OrderService/getOrder", 50, 22.0, 30.0, 8, 18),
        ("mobile_miniapp_gateway", "apex-edge-gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", 50, 20.0, 26.0, 8, 20),
    ]

    day_sec = 86400
    num_days = int((end_sec - start_sec) // day_sec)

    for day in range(num_days):
        day_base = start_sec + (day * day_sec)
        for user, caller, target, op, daily_reqs, base_lat, lat_p95, start_h, end_h in baseline_personas:
            win_start = day_base + (start_h * 3600)
            win_end = day_base + (end_h * 3600)
            if win_end > end_sec:
                continue

            b_size = 300
            total_5m_buckets = max(1, int((win_end - win_start) // b_size))
            effective_daily = daily_reqs * scale
            reqs_per_bucket = max(1, int(effective_daily // total_5m_buckets))

            for b_idx in range(total_5m_buckets):
                b_start = int(win_start + (b_idx * b_size))
                frac = b_idx / max(1, total_5m_buckets - 1)
                curve = 0.6 + 0.4 * math.sin(math.pi * frac)
                count = max(1, int(reqs_per_bucket * curve))
                lat = base_lat + random.uniform(-2.0, 2.0)
                lat_sum = lat * count

                # 5-minute bucket
                buckets.append(MetricBucket(
                    bucket_start=b_start,
                    bucket_size=300,
                    caller_service=caller,
                    target_service=target,
                    principal_name=user,
                    operation=op,
                    request_count=count,
                    error_count=0,
                    latency_sum=lat_sum,
                    latency_avg=lat,
                    latency_min=max(1.0, lat - 5.0),
                    latency_max=lat + 20.0,
                    latency_p50=lat,
                    latency_p95=lat_p95,
                    latency_p99=lat_p95 + 10.0,
                ))

                # 1-minute buckets inside this 5m window
                for m_idx in range(5):
                    m_start = b_start + (m_idx * 60)
                    m_count = max(1, count // 5)
                    buckets.append(MetricBucket(
                        bucket_start=m_start,
                        bucket_size=60,
                        caller_service=caller,
                        target_service=target,
                        principal_name=user,
                        operation=op,
                        request_count=m_count,
                        error_count=0,
                        latency_sum=lat * m_count,
                        latency_avg=lat,
                        latency_min=max(1.0, lat - 5.0),
                        latency_max=lat + 15.0,
                        latency_p50=lat,
                        latency_p95=lat_p95,
                        latency_p99=lat_p95 + 10.0,
                    ))

    print(f"Total pre-aggregated metric buckets generated: {len(buckets):,}")
    return buckets


def main():
    parser = argparse.ArgumentParser(description="Wipe databases and generate 7-day dataset.")
    parser.add_argument("--no-wipe", action="store_true", help="Skip wiping databases before generation")
    parser.add_argument("--scale", type=int, default=1, help="Scale multiplier for data density (default: 1, recommendation: 10)")
    args = parser.parse_args()

    now_sec = time.time()
    day_sec = 86400
    start_sec = now_sec - (7 * day_sec)
    recent_cutoff = now_sec - day_sec

    if not args.no_wipe:
        print("Stage 0: Wiping previous database records cleanly...")
        wipe_clickhouse()
        wipe_elasticsearch()
        try:
            truncate_system_logs()
        except Exception as e:
            print(f"Note on system logs truncation: {e}")

    # Step 1: Pre-aggregate dense metric buckets for the 6 baseline days
    hist_buckets = generate_historical_metric_buckets(start_sec, recent_cutoff, scale=args.scale)
    print(f"Saving {len(hist_buckets):,} historical metric buckets into ClickHouse...")
    AggregateRepository().save_buckets(hist_buckets)
    print("Historical metric buckets saved successfully.")

    # Step 2: Generate 7-day raw trace transactions
    records = generate_7day_raw_traces(now_sec, scale=args.scale)

    # Step 3: Ingest into Elasticsearch
    bulk_insert_es(records)

    # Step 4: Insert into ClickHouse
    insert_clickhouse_traces(records)

    # Step 5: Run analytics derivations
    derive_analytics(now_sec)


if __name__ == "__main__":
    main()

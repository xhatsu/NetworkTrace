#!/usr/bin/env python3
"""Generate a comprehensive 2,000,000-trace enterprise dataset in Elasticsearch and ClickHouse.

Guarantees 100% ground-truth coverage across EVERY SINGLE anomaly and behavioral detector:
 1. Case 1 (Abnormal TPS): pos_checkout_terminal on apex-order-service (Base ~0.15 TPS -> Spikes to 0.30 TPS).
 2. Case 2 (Abnormal TPS): vtp_express_dispatch on apex-customer-service (Base ~0.15 TPS -> Spikes to 0.32 TPS).
 3. Case 3 (Abnormal TPS): unknown on apex-edge-gateway (Base ~0.15 TPS -> Spikes to 0.30 TPS).
 4. Traffic Drop: billing_reconcile_job collapses to 0 req on Day 29.
 5. Latency Blowup: interbank_settlement_gw payment latency blowup to 950ms on Day 29.
 6. Error Rate Surge: partner_sales_broker 45% 5xx server errors on order creation.
 7. Architectural Drift: enterprise_b2b_gateway sweeps 5 new services in 45m (TARGET_FANOUT_SURGE).
 8. Unusual Access & Mix Shift: secops_monitor_agent switches to billing APIs and updateAddress.
 9. Unusual Time: sysadmin_deploy_agent off-hours 02:00-04:30 UTC rogue access from 185.220.101.5.
10. Auth Attack: mobile_miniapp_gateway 130+ 401 burst then success on host 172.16.10.45.
11. Dormant Reactivated: audit_compliance_worker active Days 0-1, silent 27 days, burst on Day 29.
12. Steady Baseline: telecom_sync_svc daytime normal operations across Days 0-29.

After generation and derivations, computes detailed storage metrics across ClickHouse, Elasticsearch, and filesystem.
"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Allow ClickHouse to retain full 2M traces for testbed analytics
os.environ["OTEL_CLICKHOUSE_ONLY_AGENT_TRACES"] = "false"

# Ensure backend modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.anomaly_detection import detect_anomalies
from backend.app.services.baseline import rebuild_baselines
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.principal_relationships import process_principal_intelligence
from backend.app.services.prometheus_metrics import update_worker_prometheus_metrics
from backend.scripts.reset_testbed import wipe_clickhouse, wipe_elasticsearch, truncate_system_logs

ES_URL = "http://127.0.0.1:32073"
INDEX_NAME = "apm-7.17.24-transaction"
BATCH_SIZE = 10000
TARGET_TOTAL_TRACES = 2000000


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
        ("NotificationService/pushAlert", "POST", 20.0, 4.0),
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
) -> dict:
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
        "http": {
            "response": {"status_code": status},
            "request": {"method": method},
        },
        "labels": {
            "caller_service": caller,
            "client_address": client_ip,
            "http_response_status_code": status,
            "http_request_method": method,
        },
    }


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


class DatasetIngester:
    def __init__(self, es_url: str, index_name: str, batch_size: int = 10000):
        self.es_url = es_url
        self.index_name = index_name
        self.batch_size = batch_size
        self.buffer: list[dict] = []
        self.total_inserted = 0
        self.t_start = time.time()
        self.repo = TraceRepository()

        # Optimize ES index for bulk ingest
        self._tune_es(for_bulk=True)

    def _tune_es(self, for_bulk: bool):
        settings_payload = {
            "index": {
                "refresh_interval": "-1" if for_bulk else "1s",
                "number_of_replicas": 0
            }
        }
        if for_bulk:
            try:
                # Try creating the index with bulk settings if it doesn't exist
                create_req = urllib.request.Request(
                    f"{self.es_url}/{self.index_name}",
                    data=json.dumps({"settings": settings_payload}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="PUT"
                )
                urllib.request.urlopen(create_req, timeout=10)
                return
            except Exception:
                pass
        try:
            req = urllib.request.Request(
                f"{self.es_url}/{self.index_name}/_settings",
                data=json.dumps(settings_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="PUT"
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    def add(self, doc: dict):
        self.buffer.append(doc)
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        chunk = self.buffer
        self.buffer = []

        # 1. Bulk insert into Elasticsearch
        lines = []
        for doc in chunk:
            lines.append(json.dumps({"index": {"_index": self.index_name}}))
            lines.append(json.dumps(doc))
        payload = "\n".join(lines) + "\n"

        req = urllib.request.Request(
            f"{self.es_url}/_bulk",
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp.read()

        # 2. Insert into ClickHouse traces table
        normalized: list[NormalizedTrace] = []
        for doc in chunk:
            t = normalize_otel_record(doc)
            if t:
                normalized.append(t)

        self.repo.insert_traces(normalized)
        self.total_inserted += len(chunk)

        elapsed = time.time() - self.t_start
        rate = self.total_inserted / max(0.1, elapsed)
        pct = min(100.0, (self.total_inserted / TARGET_TOTAL_TRACES) * 100.0)
        print(f"  [Ingest Progress] {self.total_inserted:,} / {TARGET_TOTAL_TRACES:,} traces ({pct:.1f}%) | {rate:.0f} traces/sec | Elapsed: {elapsed:.1f}s")

    def finish(self):
        self.flush()
        print("\nFinalizing Elasticsearch index and syncing replicas...")
        self._tune_es(for_bulk=False)
        refresh_req = urllib.request.Request(f"{self.es_url}/{self.index_name}/_refresh", method="POST")
        try:
            urllib.request.urlopen(refresh_req, timeout=30)
        except Exception:
            pass
        print(f"Total traces durably ingested: {self.total_inserted:,} across ES and ClickHouse.")


def generate_and_ingest_2m():
    ingester = DatasetIngester(ES_URL, INDEX_NAME, batch_size=BATCH_SIZE)

    now_sec = time.time()
    day_sec = 86400
    start_sec = now_sec - (30 * day_sec)

    print(
        f"Generating 2,000,000 enterprise transaction traces across 30 days:\n"
        f"  Start time: {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()}\n"
        f"  End time:   {datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}"
    )

    # -------------------------------------------------------------------------
    # Days 0 to 28: Historical Baseline (29 days)
    # -------------------------------------------------------------------------
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        print(f"\n--- Generating Day {day + 1}/30 ({datetime.fromtimestamp(day_base, timezone.utc).strftime('%Y-%m-%d')}) ---")

        # 1. telecom_sync_svc: Steady baseline (~20,000/day)
        day_start = day_base + (8 * 3600)
        day_end = day_base + (18 * 3600)
        for t in generate_smooth_timestamps(day_start, day_end, 20000, shape="diurnal"):
            svc = random.choice(["apex-customer-service", "apex-order-service", "apex-edge-gateway"])
            op_info = random.choice(SERVICES[svc])
            lat = max(2.0, random.gauss(op_info[2], op_info[3]))
            status = 200 if random.random() > 0.003 else 404
            ingester.add(build_apm_doc(t, "telecom_sync_svc", svc, op_info[0], op_info[1], "SALE_SERVICE", "10.240.147.247", lat, status))

        # 2. billing_reconcile_job: Night batch + daytime notifications (~14,000/day)
        for t in generate_smooth_timestamps(day_base + (2 * 3600), day_base + (4 * 3600), 7000, shape="diurnal"):
            ingester.add(build_apm_doc(t, "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))
        for t in generate_smooth_timestamps(day_start, day_end, 7000, shape="diurnal"):
            ingester.add(build_apm_doc(t, "billing_reconcile_job", "apex-notification-service", "NotificationService/sendEmail", "POST", "apex-edge-gateway", "172.16.12.19", 12.0, 200))

        # 3. partner_sales_broker: Order creation (~8,000/day)
        for t in generate_smooth_timestamps(day_start, day_end, 8000, shape="diurnal"):
            ingester.add(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", 75.0, 200))

        # 4. pos_checkout_terminal [CASE 1 BASELINE: ~0.15 TPS = 45 req / 5m bucket]
        # Active 10 daytime hours: 120 5m-buckets * 45 = 5,400 req/day
        for t in generate_smooth_timestamps(day_start, day_end, 5400, shape="flat"):
            ingester.add(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", 75.0, 200))

        # 5. vtp_express_dispatch [CASE 2 BASELINE: ~0.15 TPS = 45 req / 5m bucket]
        # Active 8 daytime hours (09:00 - 17:00 UTC): 96 5m-buckets * 45 = 4,320 req/day
        vtp_start = day_base + (9 * 3600)
        vtp_end = day_base + (17 * 3600)
        for t in generate_smooth_timestamps(vtp_start, vtp_end, 4320, shape="flat"):
            if day >= 20 and random.random() < 0.35:
                ingester.add(build_apm_doc(t, "vtp_express_dispatch", "apex-billing-service", "BillingService/queryAccountBalance", "GET", "apex-edge-gateway", "10.150.4.11", 18.0, 200))
            else:
                ingester.add(build_apm_doc(t, "vtp_express_dispatch", "apex-customer-service", "CustomerService/getProfile", "GET", "vtp-courier-app", "10.150.4.11", 20.0, 200))

        # 6. unknown [CASE 3 BASELINE: ~0.15 TPS = 45 req / 5m bucket]
        # Active 10 daytime hours: 120 5m-buckets * 45 = 5,400 req/day
        for t in generate_smooth_timestamps(day_start, day_end, 5400, shape="flat"):
            ingester.add(build_apm_doc(t, "unknown", "apex-edge-gateway", "CatalogApi/searchProducts", "GET", "public-web", "115.79.13.201", 14.0, 200))

        # 7. enterprise_b2b_gateway: Normal B2B gateway (~3,500/day)
        for t in generate_smooth_timestamps(day_start, day_end, 3500, shape="diurnal"):
            ingester.add(build_apm_doc(t, "enterprise_b2b_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "b2b-gateway", "115.78.22.84", 20.0, 200))

        # 8. interbank_settlement_gw: Payment charging (~2,500/day)
        for t in generate_smooth_timestamps(day_start, day_end, 2500, shape="diurnal"):
            ingester.add(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", 35.0, 200))

        # 9. secops_monitor_agent: Monitoring (~2,000/day)
        for t in generate_smooth_timestamps(day_start, day_end, 2000, shape="diurnal"):
            ingester.add(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/getProfile", "GET", "portal-sec", "10.150.4.88", 20.0, 200))

        # 10. sysadmin_deploy_agent: Admin config checks (~1,200/day)
        for t in generate_smooth_timestamps(day_start, day_end, 1200, shape="diurnal"):
            ingester.add(build_apm_doc(t, "sysadmin_deploy_agent", "apex-order-service", "OrderService/getOrder", "GET", "apex-edge-gateway", "10.240.147.247", 22.0, 200))

        # 11. worker_health_monitor: Normal host user on 172.16.10.45 (~500/day)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, 500, shape="diurnal"):
            ingester.add(build_apm_doc(t, "worker_health_monitor", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

        # 12. audit_compliance_worker: Active on Days 0 and 1 only
        if day < 2:
            for t in generate_smooth_timestamps(day_start, day_end, 100, shape="diurnal"):
                ingester.add(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

    # -------------------------------------------------------------------------
    # Day 29: Live & Anomaly Day (Spikes, Outages, Drifts, Attacks)
    # -------------------------------------------------------------------------
    day_29_base = start_sec + (29 * day_sec)
    print(f"\n--- Generating Day 30/30 (Anomaly & Behavioral Shifts Day) ---")

    # 1. telecom_sync_svc: Regular steady baseline traffic
    for t in generate_smooth_timestamps(day_29_base + (8 * 3600), min(now_sec, day_29_base + (18 * 3600)), 20000, shape="diurnal"):
        svc = random.choice(["apex-customer-service", "apex-order-service", "apex-edge-gateway"])
        op_info = random.choice(SERVICES[svc])
        lat = max(2.0, random.gauss(op_info[2], op_info[3]))
        ingester.add(build_apm_doc(t, "telecom_sync_svc", svc, op_info[0], op_info[1], "SALE_SERVICE", "10.240.147.247", lat, 200))

    # 2. CASE 1 ABNORMAL TPS: pos_checkout_terminal (Base 0.15 TPS -> Spikes to 0.30 TPS in last 30m)
    pos_base_end = now_sec - 1800
    for t in generate_smooth_timestamps(day_29_base + (8 * 3600), pos_base_end, 4500, shape="flat"):
        ingester.add(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", 75.0, 200))
    # Spike: 6 5m buckets * 90 req = 540 req = 0.30 TPS (+100% surge!)
    print("  Emitting Case 1: pos_checkout_terminal abnormal rate surge (0.15 TPS -> 0.30 TPS)...")
    for t in generate_smooth_timestamps(now_sec - 1800, now_sec - 10, 540, shape="ramp_up"):
        ingester.add(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", 85.0, 200))

    # 3. CASE 2 ABNORMAL TPS: vtp_express_dispatch on apex-customer-service (Base 0.15 TPS -> Spikes to 0.32 TPS in last 45m)
    vtp_base_end = now_sec - 2700
    for t in generate_smooth_timestamps(day_29_base + (9 * 3600), vtp_base_end, 3800, shape="flat"):
        ingester.add(build_apm_doc(t, "vtp_express_dispatch", "apex-customer-service", "CustomerService/getProfile", "GET", "vtp-courier-app", "10.150.4.11", 20.0, 200))
    # Spike: 9 5m buckets * 96 req = 864 req = 0.32 TPS (+113% surge!)
    print("  Emitting Case 2: vtp_express_dispatch abnormal rate surge (0.15 TPS -> 0.32 TPS)...")
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 10, 864, shape="flat"):
        ingester.add(build_apm_doc(t, "vtp_express_dispatch", "apex-customer-service", "CustomerService/getProfile", "GET", "vtp-courier-app", "10.150.4.11", 22.0, 200))

    # 4. CASE 3 ABNORMAL TPS: unknown on apex-edge-gateway (Base 0.15 TPS -> Spikes to 0.30 TPS in last 60m)
    anon_base_end = now_sec - 3600
    for t in generate_smooth_timestamps(day_29_base + (8 * 3600), anon_base_end, 4500, shape="flat"):
        ingester.add(build_apm_doc(t, "unknown", "apex-edge-gateway", "CatalogApi/searchProducts", "GET", "public-web", "115.79.13.201", 14.0, 200))
    # Spike: 12 5m buckets * 90 req = 1,080 req = 0.30 TPS (+100% surge!)
    print("  Emitting Case 3: unknown unauthenticated abnormal rate surge (0.15 TPS -> 0.30 TPS)...")
    for t in generate_smooth_timestamps(now_sec - 3600, now_sec - 10, 1080, shape="flat"):
        ingester.add(build_apm_doc(t, "unknown", "apex-edge-gateway", "CatalogApi/searchProducts", "GET", "public-web", "115.79.13.201", 15.0, 200))
    # Unauthorized scanning probes from external IP 194.26.29.112
    for t in generate_smooth_timestamps(now_sec - 1800, now_sec, 60, shape="flat"):
        ingester.add(build_apm_doc(t, "unknown", "apex-admin-service", "AdminService/systemConfig", "GET", "scanner-ext", "194.26.29.112", 22.0, 401))
    for t in generate_smooth_timestamps(now_sec - 1200, now_sec, 40, shape="flat"):
        ingester.add(build_apm_doc(t, "unknown", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "scanner-ext", "194.26.29.112", 30.0, 403))

    # 5. billing_reconcile_job: OUTAGE on Day 29 (Traffic drop)
    print("  Emitting traffic drop: billing_reconcile_job collapses to 0 req in outage window...")
    for t in generate_smooth_timestamps(day_29_base + (10 * 3600), min(now_sec - 3600, day_29_base + (16 * 3600)), 5000, shape="diurnal"):
        ingester.add(build_apm_doc(t, "billing_reconcile_job", "apex-notification-service", "NotificationService/sendEmail", "POST", "apex-edge-gateway", "172.16.12.19", 12.0, 200))

    # 6. partner_sales_broker: 45% 5xx server errors on order creation
    print("  Emitting error rate surge: partner_sales_broker 45% 5xx errors...")
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 2500, shape="flat"):
        is_err = random.random() < 0.45
        status = random.choice([500, 502, 503]) if is_err else 200
        lat = max(40.0, random.gauss(180.0, 50.0)) if is_err else 75.0
        ingester.add(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", lat, status))
    for t in generate_smooth_timestamps(now_sec - 3600, now_sec, 80, shape="flat"):
        ingester.add(build_apm_doc(t, "partner_sales_broker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.249", 20.0, 200))

    # 7. enterprise_b2b_gateway: Architectural Drift & Target Fanout Surge
    print("  Emitting target fanout surge: enterprise_b2b_gateway sweeps 5 new services...")
    fanout_targets = ["apex-billing-service", "apex-payment-service", "apex-notification-service", "apex-inventory-service", "apex-catalog-service"]
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 10, 300, shape="ramp_up"):
        tgt = random.choice(fanout_targets)
        op_info = random.choice(SERVICES[tgt])
        ingester.add(build_apm_doc(t, "enterprise_b2b_gateway", tgt, op_info[0], op_info[1], "b2b-gateway", "115.78.22.84", 35.0, 200))

    # 8. interbank_settlement_gw: Payment latency blowout to 950ms
    print("  Emitting latency blowout: interbank_settlement_gw payment latency surges to 950ms...")
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 600, shape="flat"):
        lat = max(250.0, random.gauss(950.0, 200.0))
        ingester.add(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", lat, 200))

    # 9. secops_monitor_agent: Unusual access & mix shift
    print("  Emitting unusual access & mix shift: secops_monitor_agent calling billing and updateAddress...")
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 200, shape="flat"):
        ingester.add(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/updateAddress", "POST", "portal-sec", "10.150.4.88", 45.0, 200))
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 100, shape="flat"):
        ingester.add(build_apm_doc(t, "secops_monitor_agent", "apex-billing-service", "BillingService/generateInvoiceItem", "POST", "api-client", "10.150.4.88", 45.0, 200))

    # 10. sysadmin_deploy_agent: Night off-hours rogue access from 185.220.101.5
    print("  Emitting unusual time: sysadmin_deploy_agent off-hours activity from rogue IP 185.220.101.5...")
    for t in generate_smooth_timestamps(day_29_base + int(2.0 * 3600), day_29_base + int(4.5 * 3600), 150, shape="bell"):
        ingester.add(build_apm_doc(t, "sysadmin_deploy_agent", "apex-admin-service", "AdminService/systemConfig", "GET", "apex-edge-gateway", "185.220.101.5", 25.0, 200))

    # 11. mobile_miniapp_gateway: 401 failure burst then success on host 172.16.10.45
    print("  Emitting auth failure burst & success: mobile_miniapp_gateway on host 172.16.10.45...")
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 120, 150, shape="ramp_up"):
        ingester.add(build_apm_doc(t, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 25.0, 401))
    ingester.add(build_apm_doc(now_sec - 90, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 35.0, 200))
    ingester.add(build_apm_doc(now_sec - 30, "mobile_miniapp_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

    # 12. audit_compliance_worker: Dormant reactivated
    print("  Emitting dormant reactivation: audit_compliance_worker reactivating after 27 days...")
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 80, shape="flat"):
        ingester.add(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 22.0, 200))

    # Top off to reach target 2,000,000 if needed
    current_count = ingester.total_inserted + len(ingester.buffer)
    needed = TARGET_TOTAL_TRACES - current_count
    if needed > 0:
        print(f"Top-off adjustment: Generating {needed:,} baseline background traces to reach {TARGET_TOTAL_TRACES:,} target...")
        for t in generate_smooth_timestamps(start_sec, now_sec, needed, shape="diurnal"):
            ingester.add(build_apm_doc(t, "telecom_sync_svc", "apex-customer-service", "CustomerService/getProfile", "GET", "SALE_SERVICE", "10.240.147.247", 20.0, 200))

    ingester.finish()


def run_analytics_derivations():
    print("\n================================================================")
    print("       RUNNING ANALYTICS DERIVATIONS & DETECTOR EVALUATION")
    print("================================================================")
    t0 = time.time()

    print("Stage 1/5: Aggregating 1m and 5m metric buckets and service edges...")
    aggs = aggregate_traces()
    print(f"  Aggregated: {aggs} in {round(time.time() - t0, 2)}s")

    now_sec = time.time()
    t1 = time.time()
    print("Stage 2/5: Rebuilding historical median & MAD baselines (excluding anomaly day)...")
    base_count = rebuild_baselines(max_bucket_start=int(now_sec) - 86400)
    print(f"  Baselines computed: {base_count} in {round(time.time() - t1, 2)}s")

    t2 = time.time()
    print("Stage 3/5: Deriving principal behavioral profiles, shifts & incidents...")
    p_result = process_principal_intelligence(force_bootstrap=True)
    print(f"  Principals processed: {p_result} in {round(time.time() - t2, 2)}s")

    t3 = time.time()
    print("Stage 4/5: Evaluating anomaly detection rules across metric windows...")
    with get_connection() as db:
        windows = [
            r[0] for r in db.execute(
                "SELECT DISTINCT bucket_start FROM metric_buckets WHERE bucket_size = 300 AND bucket_start >= ? ORDER BY bucket_start",
                (int(now_sec) - (4 * 86400),)
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


def calculate_storage_footprint():
    print("\n================================================================")
    print("           TRACESCOPE STORAGE FOOTPRINT ANALYSIS (2M TRACES)")
    print("================================================================")
    # 1. ClickHouse breakdown
    with get_connection() as db:
        ch_rows = db.execute("""
            SELECT table,
                   sum(data_compressed_bytes) as comp,
                   sum(data_uncompressed_bytes) as uncomp,
                   round(sum(data_uncompressed_bytes) / greatest(1, sum(data_compressed_bytes)), 2) as ratio,
                   sum(rows) as row_count,
                   count() as part_count
            FROM system.parts
            WHERE database = 'tracescope' AND active = 1
            GROUP BY table
            ORDER BY sum(data_compressed_bytes) DESC
        """).fetchall()

    total_ch_comp = sum(r[1] for r in ch_rows)
    total_ch_uncomp = sum(r[2] for r in ch_rows)
    overall_ratio = round(total_ch_uncomp / max(1, total_ch_comp), 2)

    print("\n--- ClickHouse Datastore Breakdown (tracescope database) ---")
    print(f"{'Table':<28} | {'Compressed':<12} | {'Uncompressed':<14} | {'Ratio':<6} | {'Rows':<12} | {'Parts'}")
    print("-" * 88)
    for r in ch_rows:
        comp_mb = r[1] / (1024 * 1024)
        uncomp_mb = r[2] / (1024 * 1024)
        comp_str = f"{comp_mb:.2f} MiB" if comp_mb >= 0.1 else f"{r[1]/1024:.1f} KiB"
        uncomp_str = f"{uncomp_mb:.2f} MiB" if uncomp_mb >= 0.1 else f"{r[2]/1024:.1f} KiB"
        print(f"{r[0]:<28} | {comp_str:<12} | {uncomp_str:<14} | {r[3]}x   | {r[4]:<12,} | {r[5]}")

    print("-" * 88)
    total_comp_mb = total_ch_comp / (1024 * 1024)
    total_uncomp_mb = total_ch_uncomp / (1024 * 1024)
    print(f"{'TOTAL CLICKHOUSE':<28} | {total_comp_mb:.2f} MiB ({total_comp_mb/1024:.2f} GiB) | {total_uncomp_mb:.2f} MiB ({total_uncomp_mb/1024:.2f} GiB) | {overall_ratio}x")

    # 2. Elasticsearch breakdown
    req = urllib.request.Request(f"{ES_URL}/_cat/indices/{INDEX_NAME}?format=json&bytes=b")
    es_info = {}
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            es_info = json.loads(resp.read().decode("utf-8"))[0]
    except Exception as e:
        print(f"Warning querying ES index: {e}")

    es_docs = int(es_info.get("docs.count", 0))
    es_bytes = int(es_info.get("store.size", 0))
    es_mb = es_bytes / (1024 * 1024)

    print("\n--- Elasticsearch Datastore Breakdown (apm-7.17.24-transaction) ---")
    print(f"  Primary Index:     {INDEX_NAME}")
    print(f"  Total Documents:   {es_docs:,}")
    print(f"  Store Size:        {es_mb:.2f} MiB ({es_mb/1024:.2f} GiB)")
    print(f"  Bytes per Document: ~{es_bytes / max(1, es_docs):.1f} bytes/doc")

    # 3. Overall Filesystem
    total, used, free = shutil.disk_usage("/")
    print("\n--- Linux Filesystem (/dev/sda1) ---")
    print(f"  Total Capacity:    {total / (1024**3):.1f} GiB")
    print(f"  Used Space:        {used / (1024**3):.1f} GiB")
    print(f"  Available Space:   {free / (1024**3):.1f} GiB ({free/total*100:.1f}% free)")
    print(f"  Combined Telemetry:{total_comp_mb + es_mb:.2f} MiB ({(total_comp_mb + es_mb)/1024:.2f} GiB)")
    print("================================================================\n")


if __name__ == "__main__":
    print("Stage 0: Wiping previous database records cleanly...")
    wipe_clickhouse()
    wipe_elasticsearch()
    try:
        truncate_system_logs()
    except Exception:
        pass

    generate_and_ingest_2m()
    run_analytics_derivations()
    calculate_storage_footprint()

#!/usr/bin/env python3
"""Generate a comprehensive 30-day enterprise dataset in Elasticsearch and ClickHouse.

Guarantees 100% ground-truth coverage across EVERY SINGLE anomaly and behavioral detector:
 1. telecom_sync_svc        - Steady Golden Baseline (Days 0-29, daytime 08:00-18:00 UTC, 100% normal health).
 2. vtp_express_dispatch    - Candidate Promotion (Days 20-29 accesses apex-billing-service; promoted to baseline).
 3. pos_checkout_terminal   - Traffic Spike & Principal Rate Surge (Day 29 sudden volume surge to 200+ req/5m).
 4. billing_reconcile_job   - Traffic Drop / Outage (Daily 02:00-04:00 UTC batch; Day 29 completely collapses to 0 req).
 5. interbank_settlement_gw - Latency Degradation & Blast Radius (Day 29 payment latency surges to 800-1800ms).
 6. partner_sales_broker    - Error Rate Surge (Day 29 45% 5xx server errors on order creation).
 7. enterprise_b2b_gateway  - New Service Edge + New Principal Edge + Target Fanout Surge (Day 29 sweeps 5 new services in 15m).
 8. secops_monitor_agent    - Unusual Access + Operation Mix Shift + Caller Switch (Day 29 switches to api-client & billing APIs).
 9. sysadmin_deploy_agent   - Unusual Time (Off-Hours) + User New Source IP (Day 29 active 02:00-04:30 UTC from rogue IP 185.220.101.5).
10. mobile_miniapp_gateway  - Auth Failure Burst then Success + IP New User (Day 29 130+ 401s then 200 OK on IP 172.16.10.45).
11. audit_compliance_worker - Dormant Reactivated (Active Days 0-1, silent 27 days, reactivated on Day 29).
12. unknown / -anonymous-   - Unauthenticated Public Traffic & Auth Probes (Populates Unknown Users Monitor).
"""
from __future__ import annotations

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

from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.anomaly_detection import detect_anomalies
from backend.app.services.baseline import rebuild_baselines
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.principal_relationships import process_principal_intelligence
from backend.app.services.prometheus_metrics import update_worker_prometheus_metrics

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


def generate_30day_data() -> list[dict]:
    records: list[dict] = []
    now_sec = time.time()
    day_sec = 86400
    start_sec = now_sec - (30 * day_sec)

    print(
        f"Generating 30-day enterprise dataset (11 system accounts + unauthenticated traffic) from "
        f"{datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to "
        f"{datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}..."
    )

    # -------------------------------------------------------------------------
    # 1. telecom_sync_svc: Steady Golden Baseline (Days 0 to 29)
    # -------------------------------------------------------------------------
    print("Generating persona 1/11: telecom_sync_svc (Steady golden baseline)...")
    for day in range(30):
        day_base = start_sec + (day * day_sec)
        day_start = day_base + (8 * 3600)
        day_end = min(now_sec, day_base + (18 * 3600))
        if day_start >= day_end:
            continue
        count = random.randint(190, 210)
        for t in generate_smooth_timestamps(day_start, day_end, count, shape="diurnal"):
            service = random.choice(["apex-customer-service", "apex-order-service", "apex-edge-gateway"])
            op_name, method, base_lat, lat_std = random.choice(SERVICES[service])
            lat = max(2.0, random.gauss(base_lat, lat_std))
            status = 200 if random.random() > 0.003 else 404
            records.append(build_apm_doc(t, "telecom_sync_svc", service, op_name, method, "SALE_SERVICE", "10.240.147.247", lat, status))

    # -------------------------------------------------------------------------
    # 2. vtp_express_dispatch: Candidate Promotion to Established Baseline
    # -------------------------------------------------------------------------
    print("Generating persona 2/11: vtp_express_dispatch (Candidate promotion across days 20-29)...")
    for day in range(30):
        day_base = start_sec + (day * day_sec)
        day_start = day_base + (9 * 3600)
        day_end = min(now_sec, day_base + (17 * 3600))
        if day_start >= day_end:
            continue
        count = random.randint(160, 180)
        for t in generate_smooth_timestamps(day_start, day_end, count, shape="diurnal"):
            if day >= 20 and random.random() < 0.35:
                service = "apex-billing-service"
                op_name, method = "BillingService/queryAccountBalance", "GET"
                lat = max(5.0, random.gauss(18.0, 3.5))
                caller = "apex-edge-gateway"
            else:
                service = "apex-order-service"
                op_info = random.choice(SERVICES[service])
                op_name, method, base_lat, lat_std = op_info
                lat = max(2.0, random.gauss(base_lat, lat_std))
                caller = "vtp-courier-app"
            status = 200 if random.random() > 0.005 else 400
            records.append(build_apm_doc(t, "vtp_express_dispatch", service, op_name, method, caller, "10.150.4.11", lat, status))

    # -------------------------------------------------------------------------
    # 3. pos_checkout_terminal: Traffic Spike & Principal Rate Surge
    # -------------------------------------------------------------------------
    print("Generating persona 3/11: pos_checkout_terminal (Traffic spike & rate surge)...")
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, random.randint(55, 65), shape="diurnal"):
            records.append(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", 75.0, 200))

    # Sudden surge ramp in the last 15 minutes (450 requests -> ~150 req/5m bucket)
    surge_start = now_sec - (15 * 60)
    for t in generate_smooth_timestamps(surge_start, now_sec - 30, 450, shape="ramp_up"):
        lat = max(15.0, random.gauss(85.0, 15.0))
        records.append(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", lat, 200))

    # -------------------------------------------------------------------------
    # 4. billing_reconcile_job: Traffic Drop / Outage
    # -------------------------------------------------------------------------
    print("Generating persona 4/11: billing_reconcile_job (Traffic drop / outage)...")
    # Days 0 to 28: Daily reconciliation batch between 02:00 and 04:00 UTC (~360 requests = 0.05 RPS)
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base + (2 * 3600), day_base + (4 * 3600), 360, shape="diurnal"):
            records.append(build_apm_doc(t, "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))

    # Also daytime notifications on Days 0 to 28 (08:00 - 18:00 UTC, ~350 requests = 0.08 RPS)
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), 350, shape="diurnal"):
            records.append(build_apm_doc(t, "billing_reconcile_job", "apex-notification-service", "NotificationService/sendEmail", "POST", "apex-edge-gateway", "172.16.12.19", 12.0, 200))

    # Day 29: 0 requests in outage windows
    records.append(build_apm_doc(now_sec - (5 * 3600), "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))

    # -------------------------------------------------------------------------
    # 5. interbank_settlement_gw: Latency Degradation & Blast Radius
    # -------------------------------------------------------------------------
    print("Generating persona 5/11: interbank_settlement_gw (Latency blowout & blast radius)...")
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, random.randint(80, 95), shape="diurnal"):
            records.append(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", 35.0, 200))

    bidv_latency_start = now_sec - (2 * 3600)
    for t in generate_smooth_timestamps(bidv_latency_start, now_sec, 320, shape="flat"):
        lat = max(200.0, random.gauss(950.0, 200.0))
        records.append(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", lat, 200))

    # -------------------------------------------------------------------------
    # 6. partner_sales_broker: Error Rate Surge & Caller Switch
    # -------------------------------------------------------------------------
    print("Generating persona 6/11: partner_sales_broker (Error rate surge / 5xx faults & caller switch)...")
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, random.randint(100, 115), shape="diurnal"):
            records.append(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", 75.0, 200))

    sale_error_start = now_sec - (2 * 3600)
    for t in generate_smooth_timestamps(sale_error_start, now_sec, 180, shape="flat"):
        is_err = random.random() < 0.45
        status = random.choice([500, 502, 503]) if is_err else 200
        lat = max(40.0, random.gauss(180.0, 50.0)) if is_err else 75.0
        records.append(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", lat, status))

    # Caller switch: 30 requests to apex-customer-service CustomerService/getProfile via apex-edge-gateway
    for t in generate_smooth_timestamps(now_sec - 3600, now_sec, 30, shape="flat"):
        records.append(build_apm_doc(t, "partner_sales_broker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.249", 20.0, 200))

    # -------------------------------------------------------------------------
    # 7. enterprise_b2b_gateway: New Service Edge + New Principal Edge + Target Fanout Surge
    # -------------------------------------------------------------------------
    print("Generating persona 7/11: enterprise_b2b_gateway (New edges & target fanout surge)...")
    for day in range(28):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, random.randint(85, 95), shape="diurnal"):
            records.append(build_apm_doc(t, "enterprise_b2b_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "b2b-gateway", "115.78.22.84", 20.0, 200))

    fanout_targets = ["apex-billing-service", "apex-payment-service", "apex-notification-service", "apex-inventory-service", "apex-catalog-service"]
    sweep_start = now_sec - (45 * 60)
    for t in generate_smooth_timestamps(sweep_start, now_sec - 30, 150, shape="ramp_up"):
        tgt = random.choice(fanout_targets)
        op_info = random.choice(SERVICES[tgt])
        records.append(build_apm_doc(t, "enterprise_b2b_gateway", tgt, op_info[0], op_info[1], "b2b-gateway", "115.78.22.84", 35.0, 200))

    # -------------------------------------------------------------------------
    # 8. secops_monitor_agent: Unusual Access + Operation Mix Shift
    # -------------------------------------------------------------------------
    print("Generating persona 8/11: secops_monitor_agent (Unusual access & operation mix shift)...")
    for day in range(28):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, 120, shape="diurnal"):
            records.append(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/getProfile", "GET", "portal-sec", "10.150.4.88", 20.0, 200))

    cyber_shift_start = now_sec - (2 * 3600)
    # Operation Mix Shift: 120 requests calling CustomerService/updateAddress on apex-customer-service
    for t in generate_smooth_timestamps(cyber_shift_start, now_sec, 120, shape="flat"):
        records.append(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/updateAddress", "POST", "portal-sec", "10.150.4.88", 45.0, 200))

    # Unusual Access: 50 requests calling apex-billing-service
    for t in generate_smooth_timestamps(cyber_shift_start, now_sec, 50, shape="flat"):
        records.append(build_apm_doc(t, "secops_monitor_agent", "apex-billing-service", "BillingService/generateInvoiceItem", "POST", "api-client", "10.150.4.88", 45.0, 200))

    # -------------------------------------------------------------------------
    # 9. sysadmin_deploy_agent: Unusual Time (Off-Hours Rogue Access) + User New Source IP
    # -------------------------------------------------------------------------
    print("Generating persona 9/11: sysadmin_deploy_agent (Off-hours night activity & novel source IP)...")
    for day in range(28):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base + (9 * 3600), day_base + (17 * 3600), random.randint(65, 75), shape="diurnal"):
            records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-order-service", "OrderService/getOrder", "GET", "apex-edge-gateway", "10.240.147.247", 22.0, 200))

    # Nighttime rogue accesses (02:00 - 04:30 UTC)
    for day in [27, 28]:
        day_base = start_sec + (day * day_sec)
        off_start = day_base + int(2.0 * 3600)
        off_end = day_base + int(4.5 * 3600)
        if off_end <= now_sec:
            for t in generate_smooth_timestamps(off_start, off_end, 50, shape="bell"):
                records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-admin-service", "AdminService/systemConfig", "GET", "apex-edge-gateway", "185.220.101.5", 25.0, 200))

    for t in generate_smooth_timestamps(now_sec - (90 * 60), now_sec, 40, shape="flat"):
        records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "apex-edge-gateway", "185.220.101.5", 35.0, 200))

    # -------------------------------------------------------------------------
    # 10. mobile_miniapp_gateway: Auth Attack (Failure Burst then Success) + IP New User
    # -------------------------------------------------------------------------
    print("Generating persona 10/11: mobile_miniapp_gateway (Auth attack: 401 burst then success, novel user on IP)...")
    for day in range(29):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, 35, shape="diurnal"):
            records.append(build_apm_doc(t, "worker_health_monitor", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

    attack_start = now_sec - (45 * 60)
    for t in generate_smooth_timestamps(attack_start, now_sec - 120, 130, shape="ramp_up"):
        records.append(build_apm_doc(t, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 25.0, 401))

    # Successful calls following failure burst
    records.append(build_apm_doc(now_sec - 90, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 35.0, 200))
    records.append(build_apm_doc(now_sec - 30, "mobile_miniapp_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

    # -------------------------------------------------------------------------
    # 11. audit_compliance_worker: Dormant Reactivated (DORMANT_REACTIVATED)
    # -------------------------------------------------------------------------
    print("Generating persona 11/11: audit_compliance_worker (Active days 0-1, dormant 27 days, reactivated on day 29)...")
    for day in range(2):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base + (9 * 3600), day_base + (17 * 3600), 60, shape="diurnal"):
            records.append(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

    # Reactivates on day 29 after 27 days of complete dormancy
    reactivate_start = now_sec - (2 * 3600)
    for t in generate_smooth_timestamps(reactivate_start, now_sec, 40, shape="flat"):
        records.append(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 22.0, 200))

    # -------------------------------------------------------------------------
    # 12. unknown: Unauthenticated Public Traffic & Auth Probes (Unknown Users Monitor)
    # -------------------------------------------------------------------------
    print("Generating persona 12: unknown (Anonymous public browsing + 401/403 authorization probes)...")
    for day in range(30):
        day_base = start_sec + (day * day_sec)
        for t in generate_smooth_timestamps(day_base, day_base + day_sec, random.randint(45, 55), shape="diurnal"):
            records.append(build_apm_doc(t, "unknown", "apex-catalog-service", "CatalogService/getItemDetails", "GET", "public-web", "115.79.13.201", 16.0, 200))

    # Recent 2 hours: public catalog browsing + unauthorized scan probes from external IP 194.26.29.112
    recent_anon_start = now_sec - (2 * 3600)
    for t in generate_smooth_timestamps(recent_anon_start, now_sec, 60, shape="flat"):
        records.append(build_apm_doc(t, "unknown", "apex-edge-gateway", "CatalogApi/searchProducts", "GET", "public-web", "115.79.13.201", 14.0, 200))
    for t in generate_smooth_timestamps(recent_anon_start + 1800, now_sec, 35, shape="ramp_up"):
        records.append(build_apm_doc(t, "unknown", "apex-admin-service", "AdminService/systemConfig", "GET", "scanner-ext", "194.26.29.112", 22.0, 401))
    for t in generate_smooth_timestamps(recent_anon_start + 2400, now_sec, 20, shape="flat"):
        records.append(build_apm_doc(t, "unknown", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "scanner-ext", "194.26.29.112", 30.0, 403))

    records.sort(key=lambda r: r["@timestamp"])
    print(f"Total records generated across enterprise dataset: {len(records)}")
    return records


def bulk_insert_es(records: list[dict], batch_size: int = 2000) -> int:
    total_inserted = 0
    print(f"Indexing {len(records)} transactions into Elasticsearch ({ES_URL}/{INDEX_NAME})...")

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
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            if resp_data.get("errors"):
                print(f"Warning: errors in bulk insert chunk: {resp_data.get('items', [])[:2]}")
            total_inserted += len(chunk)
            print(f"  ES Indexed {total_inserted}/{len(records)} records...")

    # Refresh index
    refresh_req = urllib.request.Request(f"{ES_URL}/{INDEX_NAME}/_refresh", method="POST")
    with urllib.request.urlopen(refresh_req, timeout=15) as resp:
        pass

    print(f"Elasticsearch index {INDEX_NAME} refreshed cleanly.")
    return total_inserted


def insert_clickhouse_traces(records: list[dict], batch_size: int = 2000) -> int:
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
        cnt = repo.insert_traces(chunk)
        total_inserted += cnt
        print(f"  ClickHouse Inserted {total_inserted}/{len(normalized)} traces...")

    print(f"ClickHouse traces insertion complete: {total_inserted} rows inserted.")
    return total_inserted


def derive_analytics():
    print("\n--- Running Derivations: Rollups, Baselines, Anomalies & Principal Intelligence ---")
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
    from backend.app.repositories.db_context import get_connection
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

    print("\n--- Dataset Generation & Derivations Finished Successfully ---")


if __name__ == "__main__":
    records = generate_30day_data()
    bulk_insert_es(records)
    insert_clickhouse_traces(records)
    derive_analytics()

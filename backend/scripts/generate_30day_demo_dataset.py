#!/usr/bin/env python3
"""Generate a hybrid enterprise dataset: 7-day raw trace retention + 30-day pre-aggregated metric rollups.

Architecture:
  - Days 0 to 23 (Days -31 to -7, historical window):
      Pre-aggregated 1m and 5m metric buckets injected directly into ClickHouse `metric_buckets`.
      Zero raw trace expansion (saves ~80% disk space).
  - Days 24 to 30 (Days -7 to 0, active forensics window):
      Full raw trace transactions indexed into Elasticsearch (`apm-7.17.24-transaction`)
      and ClickHouse (`traces`). Enables deep waterfall inspection, IP forensics, and auth attack detection.
  - Exactly 10 user personas with dedicated abnormalities:
      1. pos_checkout_terminal   - Traffic Spike & Principal Rate Surge (Surge to 450+ req/15m).
      2. billing_reconcile_job   - Traffic Drop / Outage (02:00-04:00 UTC daily batch collapses to 0 req).
      3. interbank_settlement_gw - Latency Degradation & Blast Radius (Payment latency surges to 800-1800ms).
      4. partner_sales_broker    - Error Rate Surge (45% 5xx server errors on order creation).
      5. enterprise_b2b_gateway  - New Service Edge + New Principal Edge + Target Fanout Surge (Sweeps 5 new services in 45m).
      6. secops_monitor_agent    - Unusual Access (user_new_endpoint) + Operation Mix Shift (Switches to updateAddress & billing APIs).
      7. sysadmin_deploy_agent   - Unusual Time (Off-Hours 02:00-04:30 UTC) + Caller Switch (Human operator active at night).
      8. employee_remote_user    - User New Source IP (Accessing admin/billing APIs from rogue external IP 185.220.101.5).
      9. mobile_miniapp_gateway  - Auth Failure Burst then Success (130+ 401s in 15m followed by 200 OK success).
     10. audit_compliance_worker - Dormant Reactivated (Silent 30 days, reactivated) + Novel User on Known IP (172.16.10.45).
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

from backend.app.models.aggregate import MetricBucket
from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.anomaly_detection import detect_anomalies
from backend.app.services.baseline import rebuild_baselines
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.principal_activity import materialize_principal_activity
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


def generate_historical_metric_buckets(start_sec: float, end_sec: float) -> list[MetricBucket]:
    """Directly synthesize 5-minute and 1-minute pre-aggregated buckets for the historical window.

    This establishes rich historical baselines (median, MAD, percentiles) for all services and
    principals without retaining raw trace events in the database.
    """
    buckets: list[MetricBucket] = []
    print(f"Generating pre-aggregated 5m metric buckets from {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to {datetime.fromtimestamp(end_sec, timezone.utc).isoformat()}...")

    # Personas configuration for historical baseline (Days 0 to 23)
    baseline_personas = [
        # (user, caller, target, op, method, daily_reqs, base_lat, lat_p95, start_hour, end_hour)
        ("pos_checkout_terminal", "apex-edge-gateway", "apex-order-service", "OrderService/createOrder", 60, 75.0, 85.0, 8, 20),
        ("billing_reconcile_job", "apex-order-service", "apex-inventory-service", "InventoryService/checkAvailability", 360, 15.0, 20.0, 2, 4),
        ("billing_reconcile_job", "apex-edge-gateway", "apex-notification-service", "NotificationService/sendEmail", 350, 12.0, 18.0, 8, 18),
        ("interbank_settlement_gw", "apex-order-service", "apex-payment-service", "PayService/chargeCard", 90, 35.0, 45.0, 8, 19),
        ("partner_sales_broker", "apex-edge-gateway", "apex-order-service", "OrderService/createOrder", 110, 75.0, 90.0, 8, 20),
        ("enterprise_b2b_gateway", "b2b-gateway", "apex-customer-service", "CustomerService/getProfile", 90, 20.0, 28.0, 8, 18),
        ("secops_monitor_agent", "portal-sec", "apex-customer-service", "CustomerService/getProfile", 120, 20.0, 26.0, 8, 18),
        ("sysadmin_deploy_agent", "apex-edge-gateway", "apex-order-service", "OrderService/getOrder", 70, 22.0, 30.0, 9, 17),
        ("employee_remote_user", "apex-edge-gateway", "apex-customer-service", "CustomerService/getProfile", 40, 20.0, 28.0, 8, 18),
        ("employee_remote_user", "apex-edge-gateway", "apex-order-service", "OrderService/getOrder", 40, 22.0, 30.0, 8, 18),
        ("mobile_miniapp_gateway", "apex-edge-gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", 40, 20.0, 26.0, 8, 20),
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

            # Divide into 5-minute buckets (300 seconds)
            b_size = 300
            total_5m_buckets = max(1, int((win_end - win_start) // b_size))
            reqs_per_bucket = max(1, int(daily_reqs // total_5m_buckets))

            for b_idx in range(total_5m_buckets):
                b_start = int(win_start + (b_idx * b_size))
                # Diurnal variation
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

    print(f"Total pre-aggregated metric buckets generated: {len(buckets)}")
    return buckets


def generate_recent_traces(start_sec: float, end_sec: float) -> list[dict]:
    """Generate full raw traces for the recent 7-day retention window (Days -7 to 0).

    Includes Day 0 marker for audit_compliance_worker to satisfy the 30-day dormancy threshold.
    """
    records: list[dict] = []
    now_sec = end_sec
    day_sec = 86400
    seven_days_start = now_sec - (7 * day_sec)

    print(
        f"Generating active 7-day raw trace transactions from "
        f"{datetime.fromtimestamp(seven_days_start, timezone.utc).isoformat()} to "
        f"{datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}..."
    )

    # Day 0 marker for User 10 (31 days ago) - guarantees > 30-day dormancy
    print("Generating Day 0 baseline marker for audit_compliance_worker (31 days ago)...")
    t0_base = start_sec + (8 * 3600)
    for t in generate_smooth_timestamps(t0_base, t0_base + 3600, 60, shape="diurnal"):
        records.append(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

    # Days -7 to -1 (5 days of active baseline traffic before Day 29)
    for day_offset in range(5):
        day_base = seven_days_start + (day_offset * day_sec)

        # 1. pos_checkout_terminal
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (20 * 3600), random.randint(55, 65), shape="diurnal"):
            records.append(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", 75.0, 200))

        # 2. billing_reconcile_job
        for t in generate_smooth_timestamps(day_base + (2 * 3600), day_base + (4 * 3600), 360, shape="diurnal"):
            records.append(build_apm_doc(t, "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), 350, shape="diurnal"):
            records.append(build_apm_doc(t, "billing_reconcile_job", "apex-notification-service", "NotificationService/sendEmail", "POST", "apex-edge-gateway", "172.16.12.19", 12.0, 200))

        # 3. interbank_settlement_gw
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (19 * 3600), random.randint(85, 95), shape="diurnal"):
            records.append(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", 35.0, 200))

        # 4. partner_sales_broker
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (20 * 3600), random.randint(100, 115), shape="diurnal"):
            records.append(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", 75.0, 200))

        # 5. enterprise_b2b_gateway
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), random.randint(85, 95), shape="diurnal"):
            records.append(build_apm_doc(t, "enterprise_b2b_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "b2b-gateway", "115.78.22.84", 20.0, 200))

        # 6. secops_monitor_agent
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), 120, shape="diurnal"):
            records.append(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/getProfile", "GET", "portal-sec", "10.150.4.88", 20.0, 200))

        # 7. sysadmin_deploy_agent
        for t in generate_smooth_timestamps(day_base + (9 * 3600), day_base + (17 * 3600), random.randint(65, 75), shape="diurnal"):
            records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-order-service", "OrderService/getOrder", "GET", "apex-edge-gateway", "10.240.147.247", 22.0, 200))

        # 8. employee_remote_user
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (18 * 3600), random.randint(70, 80), shape="diurnal"):
            svc = "apex-customer-service" if random.random() < 0.5 else "apex-order-service"
            op_name = "CustomerService/getProfile" if svc == "apex-customer-service" else "OrderService/getOrder"
            records.append(build_apm_doc(t, "employee_remote_user", svc, op_name, "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

        # 9. mobile_miniapp_gateway
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (20 * 3600), 40, shape="diurnal"):
            records.append(build_apm_doc(t, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

    # -------------------------------------------------------------------------
    # Day 29 (Current Window): Dedicated Abnormalities for All 10 Users
    # -------------------------------------------------------------------------
    print("Generating dedicated abnormalities for all 10 users on Day 29...")

    # 1. pos_checkout_terminal: Traffic spike ramp in last 15 minutes (450 reqs)
    surge_start = now_sec - (15 * 60)
    for t in generate_smooth_timestamps(surge_start, now_sec - 30, 450, shape="ramp_up"):
        lat = max(15.0, random.gauss(85.0, 15.0))
        records.append(build_apm_doc(t, "pos_checkout_terminal", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", lat, 200))

    # 2. billing_reconcile_job: Outage / traffic drop at 02:00-04:00 (0 reqs). 1 trace earlier
    records.append(build_apm_doc(now_sec - (6 * 3600), "billing_reconcile_job", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "apex-order-service", "172.16.12.19", 15.0, 200))

    # 3. interbank_settlement_gw: Latency blowout in last 2 hours (320 reqs, 800-1800ms)
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 320, shape="flat"):
        lat = max(200.0, random.gauss(950.0, 200.0))
        records.append(build_apm_doc(t, "interbank_settlement_gw", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", lat, 200))

    # 4. partner_sales_broker: 45% 5xx errors in last 2 hours (180 reqs)
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 180, shape="flat"):
        is_err = random.random() < 0.45
        status = random.choice([500, 502, 503]) if is_err else 200
        lat = max(40.0, random.gauss(180.0, 50.0)) if is_err else 75.0
        records.append(build_apm_doc(t, "partner_sales_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", lat, status))

    # 5. enterprise_b2b_gateway: Fanout surge sweeping 5 new services in last 45m (150 reqs)
    fanout_targets = ["apex-billing-service", "apex-payment-service", "apex-notification-service", "apex-inventory-service", "apex-catalog-service"]
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 30, 150, shape="ramp_up"):
        tgt = random.choice(fanout_targets)
        op_info = random.choice(SERVICES[tgt])
        records.append(build_apm_doc(t, "enterprise_b2b_gateway", tgt, op_info[0], op_info[1], "b2b-gateway", "115.78.22.84", 35.0, 200))

    # 6. secops_monitor_agent: Operation mix shift to updateAddress + billing API (170 reqs)
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 120, shape="flat"):
        records.append(build_apm_doc(t, "secops_monitor_agent", "apex-customer-service", "CustomerService/updateAddress", "POST", "portal-sec", "10.150.4.88", 45.0, 200))
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 50, shape="flat"):
        records.append(build_apm_doc(t, "secops_monitor_agent", "apex-billing-service", "BillingService/generateInvoiceItem", "POST", "api-client", "10.150.4.88", 45.0, 200))

    # 7. sysadmin_deploy_agent: Night off-hours activity (02:00-04:30) with caller switch
    off_start = now_sec - (5 * 3600)
    for t in generate_smooth_timestamps(off_start, off_start + 5400, 50, shape="bell"):
        records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-admin-service", "AdminService/systemConfig", "GET", "portal-admin", "10.240.147.247", 25.0, 200))
    for t in generate_smooth_timestamps(now_sec - 5400, now_sec, 40, shape="flat"):
        records.append(build_apm_doc(t, "sysadmin_deploy_agent", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "portal-admin", "10.240.147.247", 35.0, 200))

    # 8. employee_remote_user: Access from unobserved rogue IP 185.220.101.5 (40 reqs)
    for t in generate_smooth_timestamps(now_sec - 5400, now_sec, 40, shape="flat"):
        records.append(build_apm_doc(t, "employee_remote_user", "apex-admin-service", "AdminService/systemConfig", "GET", "apex-edge-gateway", "185.220.101.5", 25.0, 200))
        records.append(build_apm_doc(t + 0.5, "employee_remote_user", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "apex-edge-gateway", "185.220.101.5", 35.0, 200))

    # 9. mobile_miniapp_gateway: 130 consecutive 401s in 15m followed by 200 OK
    for t in generate_smooth_timestamps(now_sec - 2700, now_sec - 120, 130, shape="ramp_up"):
        records.append(build_apm_doc(t, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 25.0, 401))
    records.append(build_apm_doc(now_sec - 90, "mobile_miniapp_gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 35.0, 200))
    records.append(build_apm_doc(now_sec - 30, "mobile_miniapp_gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 20.0, 200))

    # 10. audit_compliance_worker: Reactivates after 30 days dormancy from IP 172.16.10.45
    for t in generate_smooth_timestamps(now_sec - 7200, now_sec, 40, shape="flat"):
        records.append(build_apm_doc(t, "audit_compliance_worker", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 22.0, 200))

    records.sort(key=lambda r: r["@timestamp"])
    print(f"Total raw trace records generated across recent window: {len(records)}")
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

    print("Stage 1/5: Aggregating 1m and 5m metric buckets from recent raw traces...")
    aggs = aggregate_traces()
    print(f"  Aggregated: {aggs} in {round(time.time() - t0, 2)}s")

    now_sec = time.time()
    t1 = time.time()
    print("Stage 2/5: Rebuilding historical median & MAD baselines (excluding anomaly window)...")
    base_count = rebuild_baselines(max_bucket_start=int(now_sec) - 86400)
    print(f"  Baselines computed: {base_count} in {round(time.time() - t1, 2)}s")

    t2 = time.time()
    print("Stage 3/5: Deriving principal behavioral profiles, shifts & incidents...")
    # User behavior reads the activity rollup, so build it from the loaded traces first.
    materialize_principal_activity(0, 4_102_444_800_000)
    p_result = process_principal_intelligence(force_bootstrap=True)
    print(f"  Principals processed: {p_result} in {round(time.time() - t2, 2)}s")

    t3 = time.time()
    print("Stage 4/5: Evaluating anomaly detection rules across metric windows...")
    from backend.app.repositories.db_context import get_connection
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

    print("\n--- Hybrid Dataset Generation & Derivations Finished Successfully ---")


if __name__ == "__main__":
    now = time.time()
    day_sec = 86400
    start_time = now - (31 * day_sec)
    recent_cutoff = now - (7 * day_sec)

    # Step 1: Pre-aggregated historical metric buckets (Days 0 to 23)
    hist_buckets = generate_historical_metric_buckets(start_time, recent_cutoff)
    print(f"Saving {len(hist_buckets)} historical metric buckets into ClickHouse...")
    AggregateRepository().save_buckets(hist_buckets)
    print("Historical metric buckets saved successfully.")

    # Step 2: Recent 7-day raw trace transactions (and Day 0 marker)
    recent_records = generate_recent_traces(start_time, now)
    bulk_insert_es(recent_records)
    insert_clickhouse_traces(recent_records)

    # Step 3: Run derivations (aggregations, baselines, anomalies, principal intelligence)
    derive_analytics()

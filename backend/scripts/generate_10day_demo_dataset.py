#!/usr/bin/env python3
"""Generate a complete 10-day realistic demonstration dataset in ClickHouse and Elasticsearch.

Key Enhancements:
  - 10-day Timespan (Days -10 to Day 0) with zero dead hours:
      Every single hour (0 to 23 UTC) across all 10 days has continuous, smooth baseline traffic.
      Uses smooth 24-hour diurnal wave formulation so charts look completely smooth without
      jagged step-changes.
  - Fresh Enterprise Usernames (Completely different from raw PCAP usernames):
      1. svc_checkout_gateway        (Replaces pos terminal / checkout gateway -> surges to ~22 TPS on anomaly day)
      2. batch_settlement_reconciler  (Replaces billing_reconcile_job)
      3. payment_clearing_engine      (Replaces interbank_settlement_gw)
      4. partner_order_broker         (Replaces partner_sales_broker)
      5. enterprise_sync_agent        (Replaces enterprise_b2b_gateway)
      6. secops_audit_scanner         (Replaces secops_monitor_agent)
      7. devops_release_operator      (Replaces sysadmin_deploy_agent)
      8. remote_workplace_client      (Replaces employee_remote_user)
      9. retail_miniapp_client        (Replaces mobile_miniapp_gateway)
     10. compliance_vault_auditor     (Replaces audit_compliance_worker)
     11. catalog_discovery_sync       (Replaces telecom_sync_svc)
     12. customer_support_bot         (Replaces chatbot)
     13. logistics_fulfillment_svc    (Replaces vtp)
     14. omnichannel_pos_terminal     (Retail point-of-sale)
     15. mobile_banking_gateway       (Consumer mobile banking)
  - Spike ONLY at Abnormality:
      Normal hourly traffic is kept steady, gentle, and smooth (~0.1 - 0.4 TPS per persona).
      The only intense traffic spike on the entire 10-day chart is the dedicated surge anomaly
      on Day 9 (peaking at ~22 TPS in a 1-minute bucket).
  - Randomized Abnormalities on the Last 3 Days (Days 7, 8, and 9):
      Days 0 to 6 (7 days) form a rock-solid, clean baseline.
      Days 7, 8, and 9 contain distinct abnormalities randomized across each day.
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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure backend modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import settings
from collections import defaultdict
from backend.app.models.aggregate import MetricBucket
from backend.app.models.trace import NormalizedTrace
from backend.app.models.topology import ServiceEdge, PrincipalServiceEdge
from backend.app.repositories.aggregate_repository import AggregateRepository
from backend.app.repositories.topology_repository import TopologyRepository
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.db_context import get_connection
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.anomaly_detection import detect_anomalies
from backend.app.services.baseline import rebuild_baselines
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.principal_relationships import process_principal_intelligence
from backend.app.services.prometheus_metrics import update_worker_prometheus_metrics
from backend.app.repositories.interactive_topology_repository import (
    canonical_service,
    canonical_principal,
    canonical_api,
)
from backend.app.services.normalization import classify_source_ip_role
from backend.scripts.reset_testbed import wipe_clickhouse, wipe_elasticsearch, truncate_system_logs

# In a 10-day dataset, 6+ days of silence constitutes dormant account reactivation
object.__setattr__(settings, "principal_dormant_days", 5)

ES_URL = "http://127.0.0.1:32073"
INDEX_NAME = "apm-7.17.24-transaction"


def get_diurnal_factor(hour_of_day: float) -> float:
    """Return a smooth, continuous 24-hour diurnal scaling factor between 0.3 and 1.0.

    Peak occurs around 14:00-16:00 UTC (1.0), trough around 03:00-04:00 UTC (0.3).
    Continuous everywhere with zero abrupt step-changes.
    """
    fraction = ((hour_of_day - 4.0) % 24.0) / 24.0
    return 0.30 + 0.70 * (math.sin(math.pi * fraction) ** 2)


def generate_smooth_timestamps(start_sec: float, end_sec: float, count: int, shape: str = "flat", jitter_sec: float = 1.0) -> list[float]:
    duration = max(60.0, end_sec - start_sec)
    num_buckets = max(1, int(duration // 60))

    weights = []
    for i in range(num_buckets):
        fraction = i / max(1, num_buckets - 1)
        if shape == "diurnal":
            weights.append(0.5 + 0.5 * math.sin(math.pi * fraction))
        elif shape == "ramp_up":
            weights.append(0.1 + 0.9 * (fraction ** 1.5))
        elif shape == "ramp_down":
            weights.append(max(0.02, 1.0 - (fraction ** 1.5)))
        elif shape == "bell":
            weights.append(math.exp(-0.5 * ((fraction - 0.5) / 0.2) ** 2))
        else:
            weights.append(1.0)

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
        ("CustomerService/InterfaceForViettelApp", "POST", 25.0, 5.0),
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
        ("NotificationService/InterfaceForChatBot", "POST", 22.0, 4.5),
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


# ==============================================================================
# FRESH PERSONA CATALOG (Zero overlap with raw PCAP usernames)
# ==============================================================================
# Format: (user, caller, target, op, method, client_ip, base_reqs_per_hour, base_lat, lat_p95)
ENTERPRISE_PERSONAS = [
    # 1. svc_checkout_gateway: steady normal checkout (~200% surge ONLY during anomaly)
    ("svc_checkout_gateway", "apex-edge-gateway", "apex-order-service", "OrderService/createOrder", "POST", "10.240.147.247", 18, 75.0, 85.0),
    # 2. payment_clearing_engine: payment processing
    ("payment_clearing_engine", "apex-order-service", "apex-payment-service", "PayService/chargeCard", "POST", "10.150.4.11", 16, 35.0, 45.0),
    # 3. partner_order_broker: partner order intake
    ("partner_order_broker", "apex-edge-gateway", "apex-order-service", "OrderService/createOrder", "POST", "10.240.147.249", 15, 75.0, 90.0),
    # 4. enterprise_sync_agent: B2B profile integration
    ("enterprise_sync_agent", "b2b-gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "115.78.22.84", 20, 20.0, 28.0),
    # 5. secops_audit_scanner: continuous security audit
    ("secops_audit_scanner", "portal-sec", "apex-customer-service", "CustomerService/getProfile", "GET", "10.150.4.88", 14, 20.0, 26.0),
    # 6. devops_release_operator: configuration inspection
    ("devops_release_operator", "apex-edge-gateway", "apex-order-service", "OrderService/getOrder", "GET", "10.240.147.247", 12, 22.0, 30.0),
    # 7. remote_workplace_client: employee portal
    ("remote_workplace_client", "apex-edge-gateway", "apex-customer-service", "CustomerService/getProfile", "GET", "10.240.147.247", 12, 20.0, 28.0),
    # 8. retail_miniapp_client: retail mini-app operations
    ("retail_miniapp_client", "apex-edge-gateway", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "172.16.10.45", 14, 20.0, 26.0),
    # 9. catalog_discovery_sync: 24/7 background catalog catalog cache refresher
    ("catalog_discovery_sync", "SALE_SERVICE", "apex-catalog-service", "CatalogService/getItemDetails", "GET", "10.240.147.247", 10, 18.0, 22.0),
    # 10. customer_support_bot: 24/7 notification and support bot
    ("customer_support_bot", "portal-sec", "apex-notification-service", "NotificationService/InterfaceForChatBot", "POST", "10.150.4.88", 10, 22.0, 28.0),
    # 11. logistics_fulfillment_svc: order validation and logistics
    ("logistics_fulfillment_svc", "apex-edge-gateway", "apex-order-service", "OrderService/validateOrderLimits", "POST", "10.240.147.249", 14, 28.0, 35.0),
    # 12. mobile_banking_gateway: mobile banking balance inquiry
    ("mobile_banking_gateway", "apex-edge-gateway", "apex-edge-gateway", "BillingApi/queryBalance", "GET", "10.240.147.249", 16, 12.0, 18.0),
    # 13. batch_settlement_reconciler: nightly reconciliation
    ("batch_settlement_reconciler", "apex-order-service", "apex-inventory-service", "InventoryService/checkAvailability", "GET", "172.16.12.19", 25, 15.0, 20.0),
]


def generate_hourly_baseline_traces_for_day(day_base: float, day_offset: int, scale: int, now_sec: float) -> list[dict]:
    """Generate smooth authentic microservice transactions across all 24 hours of a single day."""
    traces: list[dict] = []

    for h in range(24):
        h_start = day_base + (h * 3600)
        h_end = h_start + 3600
        if h_start >= now_sec:
            continue
        if h_end > now_sec:
            h_end = now_sec

        dt = datetime.fromtimestamp(h_start, timezone.utc)
        df = get_diurnal_factor(dt.hour)

        for user, caller, target, op, method, client_ip, base_reqs, base_lat, _ in ENTERPRISE_PERSONAS:
            # Special schedule for nightly batch reconciler: heavier at 02:00-05:00 UTC, light keepalive elsewhere
            if user == "batch_settlement_reconciler":
                req_count = int(base_reqs * 2.5 * scale) if dt.hour in (2, 3, 4) else int(max(1, base_reqs * 0.2 * scale))
            else:
                # All other personas scale smoothly with the diurnal curve
                req_count = max(1, int(base_reqs * df * scale))

            fraction = (h_end - h_start) / 3600.0
            req_count = max(1, int(req_count * fraction))

            for t in generate_smooth_timestamps(h_start, h_end, req_count, shape="flat"):
                lat = max(5.0, random.gauss(base_lat, base_lat * 0.12))
                traces.append(build_apm_doc(t, user, target, op, method, caller, client_ip, lat, 200))

    # compliance_vault_auditor: Active on Day 0 ONLY, then silent for 8+ days (dormant)
    if day_offset == 0:
        for t in generate_smooth_timestamps(day_base + (8 * 3600), day_base + (12 * 3600), int(60 * scale), shape="diurnal"):
            traces.append(build_apm_doc(t, "compliance_vault_auditor", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "10.240.147.247", 20.0, 200))

    return traces



# ==============================================================================
# ANOMALY GENERATOR FACTORY FOR THE LAST 3 DAYS
# ==============================================================================

def inject_traffic_spike_anomaly(day_base: float, scale: int, peak_hour_offset: float = 14.0) -> list[dict]:
    """Inject traffic surge ramping up to ~0.60-0.75 TPS (~200% increase over baseline for svc_checkout_gateway)."""
    docs = []
    spike_start = day_base + (peak_hour_offset * 3600)
    spike_end = spike_start + (15 * 60)  # 15 minutes
    # 32 * scale over 15m produces ~320 requests, ramping from ~0.20 TPS baseline up to ~0.60-0.75 TPS (+200% spike)
    surge_count = int(32 * scale)
    for t in generate_smooth_timestamps(spike_start, spike_end, surge_count, shape="ramp_up"):
        lat = max(15.0, random.gauss(85.0, 15.0))
        docs.append(build_apm_doc(t, "svc_checkout_gateway", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.247", lat, 200))
    return docs


def inject_latency_anomaly(day_base: float, scale: int, start_hour_offset: float = 10.0) -> list[dict]:
    """Inject payment latency blowout (800-1800ms) for 2 hours."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 7200
    for t in generate_smooth_timestamps(win_start, win_end, int(250 * scale), shape="flat"):
        lat = max(200.0, random.gauss(950.0, 200.0))
        docs.append(build_apm_doc(t, "payment_clearing_engine", "apex-payment-service", "PayService/chargeCard", "POST", "apex-order-service", "10.150.4.11", lat, 200))
    return docs


def inject_error_rate_anomaly(day_base: float, scale: int, start_hour_offset: float = 15.0) -> list[dict]:
    """Inject 45% 5xx server errors for 2 hours."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 7200
    for t in generate_smooth_timestamps(win_start, win_end, int(180 * scale), shape="flat"):
        is_err = random.random() < 0.45
        status = random.choice([500, 502, 503]) if is_err else 200
        lat = max(40.0, random.gauss(180.0, 50.0)) if is_err else 75.0
        docs.append(build_apm_doc(t, "partner_order_broker", "apex-order-service", "OrderService/createOrder", "POST", "apex-edge-gateway", "10.240.147.249", lat, status))
    return docs


def inject_fanout_anomaly(day_base: float, scale: int, start_hour_offset: float = 11.0) -> list[dict]:
    """Inject target fanout surge sweeping 5 new services in 45m."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 2700
    fanout_targets = ["apex-billing-service", "apex-payment-service", "apex-notification-service", "apex-inventory-service", "apex-catalog-service"]
    for t in generate_smooth_timestamps(win_start, win_end, int(150 * scale), shape="ramp_up"):
        tgt = random.choice(fanout_targets)
        op_info = random.choice(SERVICES[tgt])
        docs.append(build_apm_doc(t, "enterprise_sync_agent", tgt, op_info[0], op_info[1], "b2b-gateway", "115.78.22.84", 35.0, 200))
    return docs


def inject_operation_mix_anomaly(day_base: float, scale: int, start_hour_offset: float = 13.0) -> list[dict]:
    """Inject operation mix shift to updateAddress + billing APIs."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 5400
    for t in generate_smooth_timestamps(win_start, win_end, int(100 * scale), shape="flat"):
        docs.append(build_apm_doc(t, "secops_audit_scanner", "apex-customer-service", "CustomerService/updateAddress", "POST", "portal-sec", "10.150.4.88", 45.0, 200))
    for t in generate_smooth_timestamps(win_start, win_end, int(40 * scale), shape="flat"):
        docs.append(build_apm_doc(t, "secops_audit_scanner", "apex-billing-service", "BillingService/generateInvoiceItem", "POST", "api-client", "10.150.4.88", 45.0, 200))
    return docs


def inject_unusual_time_anomaly(day_base: float, scale: int, start_hour_offset: float = 3.0) -> list[dict]:
    """Inject off-hours activity (02:30-04:30 UTC) with caller switch."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 5400
    for t in generate_smooth_timestamps(win_start, win_end, int(50 * scale), shape="bell"):
        docs.append(build_apm_doc(t, "devops_release_operator", "apex-admin-service", "AdminService/systemConfig", "GET", "portal-admin", "10.240.147.247", 25.0, 200))
    for t in generate_smooth_timestamps(win_start, win_end, int(40 * scale), shape="flat"):
        docs.append(build_apm_doc(t, "devops_release_operator", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "portal-admin", "10.240.147.247", 35.0, 200))
    return docs


def inject_rogue_ip_anomaly(day_base: float, scale: int, start_hour_offset: float = 16.0) -> list[dict]:
    """Inject novel rogue external IP 185.220.101.5 access."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 3600
    for t in generate_smooth_timestamps(win_start, win_end, int(40 * scale), shape="flat"):
        docs.append(build_apm_doc(t, "remote_workplace_client", "apex-admin-service", "AdminService/systemConfig", "GET", "apex-edge-gateway", "185.220.101.5", 25.0, 200))
        docs.append(build_apm_doc(t + 0.5, "remote_workplace_client", "apex-billing-service", "BillingService/calculateUsageTax", "POST", "apex-edge-gateway", "185.220.101.5", 35.0, 200))
    return docs


def inject_auth_failure_burst_anomaly(day_base: float, scale: int, start_hour_offset: float = 12.0) -> list[dict]:
    """Inject 401 unauthorized burst in 45m followed by 200 OK success."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 2700
    for t in generate_smooth_timestamps(win_start, win_end - 120, int(120 * scale), shape="ramp_up"):
        docs.append(build_apm_doc(t, "retail_miniapp_client", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 25.0, 401))
    docs.append(build_apm_doc(win_end - 90, "retail_miniapp_client", "apex-edge-gateway", "SaleApi/InterfaceForSale", "POST", "apex-edge-gateway", "172.16.10.45", 35.0, 200))
    docs.append(build_apm_doc(win_end - 30, "retail_miniapp_client", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 20.0, 200))
    return docs


def inject_dormant_reactivation_anomaly(day_base: float, scale: int, start_hour_offset: float = 14.5) -> list[dict]:
    """Inject dormant account reactivation after 8+ days of silence from IP 172.16.10.45."""
    docs = []
    win_start = day_base + (start_hour_offset * 3600)
    win_end = win_start + 5400
    for t in generate_smooth_timestamps(win_start, win_end, int(50 * scale), shape="flat"):
        docs.append(build_apm_doc(t, "compliance_vault_auditor", "apex-customer-service", "CustomerService/getProfile", "GET", "apex-edge-gateway", "172.16.10.45", 22.0, 200))
    return docs


ANOMALY_GENERATORS = [
    ("traffic_spike", inject_traffic_spike_anomaly),
    ("latency_blowout", inject_latency_anomaly),
    ("error_rate_surge", inject_error_rate_anomaly),
    ("target_fanout_surge", inject_fanout_anomaly),
    ("operation_mix_shift", inject_operation_mix_anomaly),
    ("unusual_time_access", inject_unusual_time_anomaly),
    ("rogue_source_ip", inject_rogue_ip_anomaly),
    ("auth_failure_burst", inject_auth_failure_burst_anomaly),
    ("dormant_reactivation", inject_dormant_reactivation_anomaly),
]


def generate_10day_raw_traces(now_sec: float, scale: int = 1) -> tuple[list[dict], set[int]]:
    """Generate 10-day raw trace dataset with 24/7 hourly traffic and randomized abnormalities on the last 3 days."""
    records: list[dict] = []
    injected_windows: set[int] = set()
    day_sec = 86400
    start_sec = now_sec - (10 * day_sec)
    scale = max(1, scale)

    print(
        f"Generating 10-day raw trace dataset (scale={scale}x) from "
        f"{datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to "
        f"{datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}..."
    )

    # Days 0 to 6: 7 days of established 24/7 baseline traffic
    for day_offset in range(7):
        day_base = start_sec + (day_offset * day_sec)
        day_traces = generate_hourly_baseline_traces_for_day(day_base, day_offset, scale, now_sec)
        records.extend(day_traces)
        print(f"  Day {day_offset} (Baseline, -{10 - day_offset}d): {len(day_traces):,} traces across 24 hours")

    # Days 7, 8, 9: The Last 3 Days (Baseline + Randomized Abnormalities)
    available_anomalies = list(ANOMALY_GENERATORS)
    random.shuffle(available_anomalies)

    day_assignments = {
        7: available_anomalies[0:3],
        8: available_anomalies[3:6],
        9: available_anomalies[6:9],
    }

    # Ensure Day 9 (Today) always contains the traffic spike
    day9_names = [a[0] for a in day_assignments[9]]
    if "traffic_spike" not in day9_names:
        for d in (7, 8):
            for idx, a in enumerate(day_assignments[d]):
                if a[0] == "traffic_spike":
                    day_assignments[d][idx], day_assignments[9][0] = day_assignments[9][0], day_assignments[d][idx]
                    break

    for day_offset in (7, 8, 9):
        day_base = start_sec + (day_offset * day_sec)
        day_traces = generate_hourly_baseline_traces_for_day(day_base, day_offset, scale, now_sec)

        injected_anomalies = day_assignments[day_offset]
        anomaly_names = []
        for name, func in injected_anomalies:
            if name == "unusual_time_access":
                hour_offset = 3.0
            elif name == "traffic_spike" and day_offset == 9:
                hour_offset = 23.65  # In last 20 minutes before now_sec (~200% surge to ~0.60-0.75 TPS)
            else:
                hour_offset = random.uniform(8.0, 20.0)

            anom_docs = func(day_base, scale, start_hour_offset=hour_offset) if name != "traffic_spike" else func(day_base, scale, peak_hour_offset=hour_offset)
            valid_anom = [d for d in anom_docs if datetime.fromisoformat(d["@timestamp"].replace("Z", "+00:00")).timestamp() <= now_sec]
            for d in valid_anom:
                ts = int(datetime.fromisoformat(d["@timestamp"].replace("Z", "+00:00")).timestamp())
                injected_windows.add((ts // 300) * 300)
            day_traces.extend(valid_anom)
            anomaly_names.append(name)

        day_traces = [d for d in day_traces if datetime.fromisoformat(d["@timestamp"].replace("Z", "+00:00")).timestamp() <= now_sec]
        records.extend(day_traces)
        print(f"  Day {day_offset} (Anomaly Window, -{10 - day_offset}d): {len(day_traces):,} traces with randomized anomalies: {', '.join(anomaly_names)}")

    records.sort(key=lambda r: r["@timestamp"])
    print(f"Total raw trace records generated: {len(records):,}")
    return records, injected_windows


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


def aggregate_records_and_save(records: list[dict]):
    """Aggregate all 10 days of raw traces into 1m & 5m metric buckets and topology edges directly."""
    print(f"Aggregating {len(records):,} records into 1m & 5m metric buckets and topology edges...")
    t0 = time.time()
    buckets_1m_map = defaultdict(lambda: {"count": 0, "errors": 0, "lat_sum": 0.0, "lat_min": 1e9, "lat_max": 0.0, "latencies": [], "request_bytes": 0, "response_bytes": 0, "request_bytes_samples": 0, "response_bytes_samples": 0})
    buckets_5m_map = defaultdict(lambda: {"count": 0, "errors": 0, "lat_sum": 0.0, "lat_min": 1e9, "lat_max": 0.0, "latencies": [], "request_bytes": 0, "response_bytes": 0, "request_bytes_samples": 0, "response_bytes_samples": 0})

    edges_map: dict = {}
    principal_edges_map: dict = {}

    for doc in records:
        ts_sec = int(datetime.fromisoformat(doc["@timestamp"].replace("Z", "+00:00")).timestamp())
        target = doc.get("service", {}).get("name", "")
        labels = doc.get("labels", {})
        caller = labels.get("caller_service", "")
        user = doc.get("enduser.id") or doc.get("enduser", {}).get("id") or doc.get("user", {}).get("name") or "unknown"
        op = doc.get("transaction", {}).get("name", "")
        duration_ms = float(doc.get("transaction", {}).get("duration", {}).get("us", 0)) / 1000.0
        status = int(labels.get("http_response_status_code", 200))
        is_err = status >= 400 or doc.get("transaction", {}).get("outcome") in ("failure", "error")
        request_bytes_value = doc.get("request_bytes", doc.get("req_bytes", labels.get("http_request_content_length")))
        response_bytes_value = doc.get("response_bytes", doc.get("resp_bytes", labels.get("http_response_content_length")))
        request_bytes = max(0, int(request_bytes_value or 0))
        response_bytes = max(0, int(response_bytes_value or 0))

        # 1m bucket
        b1m = (ts_sec // 60) * 60
        e1 = buckets_1m_map[(b1m, caller, target, user, op)]
        e1["count"] += 1
        if is_err: e1["errors"] += 1
        e1["lat_sum"] += duration_ms
        if duration_ms < e1["lat_min"]: e1["lat_min"] = duration_ms
        if duration_ms > e1["lat_max"]: e1["lat_max"] = duration_ms
        e1["latencies"].append(duration_ms)
        e1["request_bytes"] += request_bytes
        e1["response_bytes"] += response_bytes
        e1["request_bytes_samples"] += int(request_bytes_value is not None)
        e1["response_bytes_samples"] += int(response_bytes_value is not None)

        # 5m bucket
        b5m = (ts_sec // 300) * 300
        e5 = buckets_5m_map[(b5m, caller, target, user, op)]
        e5["count"] += 1
        if is_err: e5["errors"] += 1
        e5["lat_sum"] += duration_ms
        if duration_ms < e5["lat_min"]: e5["lat_min"] = duration_ms
        if duration_ms > e5["lat_max"]: e5["lat_max"] = duration_ms
        e5["latencies"].append(duration_ms)
        e5["request_bytes"] += request_bytes
        e5["response_bytes"] += response_bytes
        e5["request_bytes_samples"] += int(request_bytes_value is not None)
        e5["response_bytes_samples"] += int(response_bytes_value is not None)

        # Topology edges
        if caller and target:
            edge = edges_map.setdefault((caller, target), {
                "first_seen": ts_sec, "last_seen": ts_sec,
                "count": 0, "errors": 0, "latency_sum": 0.0, "latencies": [],
                "principals": set(), "operations": set(),
            })
            edge["first_seen"] = min(edge["first_seen"], ts_sec)
            edge["last_seen"] = max(edge["last_seen"], ts_sec)
            edge["count"] += 1
            if is_err: edge["errors"] += 1
            edge["latency_sum"] += duration_ms
            edge["latencies"].append(duration_ms)
            edge["principals"].add(user)
            edge["operations"].add(op)

            p_edge = principal_edges_map.setdefault((user, caller, target), {
                "first_seen": ts_sec, "last_seen": ts_sec,
                "count": 0, "errors": 0, "latencies": [],
            })
            p_edge["first_seen"] = min(p_edge["first_seen"], ts_sec)
            p_edge["last_seen"] = max(p_edge["last_seen"], ts_sec)
            p_edge["count"] += 1
            if is_err: p_edge["errors"] += 1
            p_edge["latencies"].append(duration_ms)

    # Materialize 1m buckets
    buckets_1m = []
    for (b_start, caller, target, user, op), stats in buckets_1m_map.items():
        cnt = stats["count"]
        lats = stats["latencies"]
        lats.sort()
        buckets_1m.append(MetricBucket(
            bucket_start=b_start, bucket_size=60,
            caller_service=caller, target_service=target, principal_name=user, operation=op,
            request_count=cnt, error_count=stats["errors"],
            latency_sum=stats["lat_sum"], latency_avg=stats["lat_sum"] / max(1, cnt),
            latency_min=stats["lat_min"], latency_max=stats["lat_max"],
            latency_p50=lats[int(cnt * 0.50)],
            latency_p95=lats[min(cnt - 1, int(cnt * 0.95))],
            latency_p99=lats[min(cnt - 1, int(cnt * 0.99))],
            request_bytes=stats["request_bytes"], response_bytes=stats["response_bytes"],
            request_bytes_samples=stats["request_bytes_samples"],
            response_bytes_samples=stats["response_bytes_samples"],
        ))

    # Materialize 5m buckets
    buckets_5m = []
    for (b_start, caller, target, user, op), stats in buckets_5m_map.items():
        cnt = stats["count"]
        lats = stats["latencies"]
        lats.sort()
        buckets_5m.append(MetricBucket(
            bucket_start=b_start, bucket_size=300,
            caller_service=caller, target_service=target, principal_name=user, operation=op,
            request_count=cnt, error_count=stats["errors"],
            latency_sum=stats["lat_sum"], latency_avg=stats["lat_sum"] / max(1, cnt),
            latency_min=stats["lat_min"], latency_max=stats["lat_max"],
            latency_p50=lats[int(cnt * 0.50)],
            latency_p95=lats[min(cnt - 1, int(cnt * 0.95))],
            latency_p99=lats[min(cnt - 1, int(cnt * 0.99))],
            request_bytes=stats["request_bytes"], response_bytes=stats["response_bytes"],
            request_bytes_samples=stats["request_bytes_samples"],
            response_bytes_samples=stats["response_bytes_samples"],
        ))

    # Materialize edges
    service_edges = []
    for (caller, target), val in edges_map.items():
        cnt = val["count"]
        lats = val["latencies"]
        lats.sort()
        p95 = lats[min(cnt - 1, int(cnt * 0.95))]
        service_edges.append(ServiceEdge(
            caller_service=caller, target_service=target,
            first_seen=val["first_seen"], last_seen=val["last_seen"],
            request_count=cnt, error_count=val["errors"],
            error_rate=round(val["errors"] / max(1, cnt), 4),
            avg_latency=round(val["latency_sum"] / max(1, cnt), 2),
            p95_latency=round(p95, 2),
            principal_count=len(val["principals"]),
            operation_count=len(val["operations"]),
        ))

    principal_edges = []
    for (user, caller, target), val in principal_edges_map.items():
        cnt = val["count"]
        lats = val["latencies"]
        lats.sort()
        p95 = lats[min(cnt - 1, int(cnt * 0.95))]
        principal_edges.append(PrincipalServiceEdge(
            principal_name=user, caller_service=caller, target_service=target,
            first_seen=val["first_seen"], last_seen=val["last_seen"],
            request_count=cnt, error_rate=round(val["errors"] / max(1, cnt), 4),
            p95_latency=round(p95, 2),
        ))

    repo = AggregateRepository()
    batch_size = 10000
    for i in range(0, len(buckets_1m), batch_size):
        repo.save_buckets(buckets_1m[i:i + batch_size])
    for i in range(0, len(buckets_5m), batch_size):
        repo.save_buckets(buckets_5m[i:i + batch_size])

    topo_repo = TopologyRepository()
    topo_repo.save_edges(service_edges, principal_edges)

    print(f"  Aggregated & saved {len(buckets_1m):,} 1m buckets, {len(buckets_5m):,} 5m buckets, {len(service_edges)} service edges, {len(principal_edges)} principal edges in {round(time.time() - t0, 2)}s")


def save_topology_rollups(records: list[dict]):
    """Materialize 5m interactive topology rollups in ClickHouse for all 10 days."""
    print(f"Materializing 5m topology rollups for {len(records):,} records...")
    t0 = time.time()
    now_ms = int(time.time() * 1000)

    service_edges_map = defaultdict(lambda: {
        "count": 0, "errors": 0, "4xx": 0, "5xx": 0, "timeouts": 0,
        "lat_sum": 0.0, "lats": [], "req_bytes": 0, "resp_bytes": 0,
        "principals": set(), "ips": set(), "anon": 0,
        "first_seen": 1e18, "last_seen": 0
    })
    api_edges_map = defaultdict(lambda: {
        "count": 0, "errors": 0, "4xx": 0, "5xx": 0, "timeouts": 0,
        "lat_sum": 0.0, "lats": [], "req_bytes": 0, "resp_bytes": 0,
        "principals": set(), "ips": set(), "anon": 0,
        "first_seen": 1e18, "last_seen": 0
    })
    principal_edges_map = defaultdict(lambda: {
        "count": 0, "errors": 0, "4xx": 0, "5xx": 0, "timeouts": 0,
        "lat_sum": 0.0, "lats": [], "req_bytes": 0, "resp_bytes": 0,
        "ips": set(), "anon": 0,
        "first_seen": 1e18, "last_seen": 0
    })
    ip_edges_map = defaultdict(lambda: {
        "count": 0, "errors": 0, "4xx": 0, "5xx": 0, "timeouts": 0,
        "lats": [], "req_bytes": 0, "resp_bytes": 0,
        "first_seen": 1e18, "last_seen": 0
    })
    seen_user_ips = set()
    sorted_records = sorted(
        records,
        key=lambda d: d.get("@timestamp") or ""
    )

    for doc in sorted_records:
        ts_sec = int(datetime.fromisoformat(doc["@timestamp"].replace("Z", "+00:00")).timestamp())
        ts_ms = ts_sec * 1000
        b5m = (ts_sec // 300) * 300
        b5m_ms = b5m * 1000

        target_service = canonical_service(doc.get("service", {}).get("name", ""))
        labels = doc.get("labels", {})
        caller_service = str(labels.get("caller_service", "")).strip()[:200]
        caller_api = ""
        user_raw = doc.get("enduser.id") or doc.get("enduser", {}).get("id") or doc.get("user", {}).get("name") or "unknown"
        principal = canonical_principal(user_raw)
        raw_op = doc.get("transaction", {}).get("name", "")
        target_api = canonical_api(raw_op, target_service)
        source_ip = str(doc.get("client", {}).get("ip") or "").strip()
        duration_ms = float(doc.get("transaction", {}).get("duration", {}).get("us", 0)) / 1000.0
        status = int(labels.get("http_response_status_code", 200))
        req_bytes = int(doc.get("request_bytes") or doc.get("req_bytes") or labels.get("http_request_content_length") or 0)
        resp_bytes = int(doc.get("response_bytes") or doc.get("resp_bytes") or labels.get("http_response_content_length") or 0)

        is_err = status >= 400 or doc.get("transaction", {}).get("outcome") in ("failure", "error")
        is_4xx = 400 <= status < 500
        is_5xx = status >= 500
        is_timeout = status == 504 or doc.get("transaction", {}).get("outcome") == "timeout"
        is_anon = 1 if principal == "-anonymous-" else 0

        ev_type = "OTEL_CLIENT_SERVER" if caller_service else "IP_SERVICE_INFERRED"
        ev_detail = "OTel client span to peer service" if caller_service else "Relationship inferred from incomplete telemetry"
        confidence = 1.0 if caller_service else 0.5

        # Service edges 5m
        if caller_service and target_service:
            s_key = (b5m, caller_service, target_service, ev_type, ev_detail, confidence)
            st = service_edges_map[s_key]
            st["count"] += 1
            if is_err: st["errors"] += 1
            if is_4xx: st["4xx"] += 1
            if is_5xx: st["5xx"] += 1
            if is_timeout: st["timeouts"] += 1
            st["lat_sum"] += duration_ms
            st["lats"].append(duration_ms)
            st["req_bytes"] += req_bytes
            st["resp_bytes"] += resp_bytes
            if principal != "-anonymous-": st["principals"].add(principal)
            if source_ip and source_ip not in ("", "unavailable", "unknown"): st["ips"].add(source_ip)
            st["anon"] += is_anon
            if ts_ms < st["first_seen"]: st["first_seen"] = ts_ms
            if ts_ms > st["last_seen"]: st["last_seen"] = ts_ms

        # API edges 5m
        api_key = (b5m, caller_service, caller_api, target_service, target_api, ev_type, ev_detail, confidence)
        ast = api_edges_map[api_key]
        ast["count"] += 1
        if is_err: ast["errors"] += 1
        if is_4xx: ast["4xx"] += 1
        if is_5xx: ast["5xx"] += 1
        if is_timeout: ast["timeouts"] += 1
        ast["lat_sum"] += duration_ms
        ast["lats"].append(duration_ms)
        ast["req_bytes"] += req_bytes
        ast["resp_bytes"] += resp_bytes
        if principal != "-anonymous-": ast["principals"].add(principal)
        if source_ip and source_ip not in ("", "unavailable", "unknown"): ast["ips"].add(source_ip)
        ast["anon"] += is_anon
        if ts_ms < ast["first_seen"]: ast["first_seen"] = ts_ms
        if ts_ms > ast["last_seen"]: ast["last_seen"] = ts_ms

        # Principal edges 5m
        p_key = (b5m, principal, caller_service, caller_api, target_service, target_api, ev_type, ev_detail, confidence)
        pst = principal_edges_map[p_key]
        pst["count"] += 1
        if is_err: pst["errors"] += 1
        if is_4xx: pst["4xx"] += 1
        if is_5xx: pst["5xx"] += 1
        if is_timeout: pst["timeouts"] += 1
        pst["lat_sum"] += duration_ms
        pst["lats"].append(duration_ms)
        pst["req_bytes"] += req_bytes
        pst["resp_bytes"] += resp_bytes
        if source_ip and source_ip not in ("", "unavailable", "unknown"): pst["ips"].add(source_ip)
        pst["anon"] += is_anon
        if ts_ms < pst["first_seen"]: pst["first_seen"] = ts_ms
        if ts_ms > pst["last_seen"]: pst["last_seen"] = ts_ms

        # Principal IP edges 5m
        if source_ip:
            is_new_ip = 0 if (principal, source_ip) in seen_user_ips else 1
            seen_user_ips.add((principal, source_ip))
            ip_key = (b5m, principal, source_ip, target_service, target_api, caller_service, is_new_ip)
            ist = ip_edges_map[ip_key]
            ist["count"] += 1
            if is_err: ist["errors"] += 1
            if is_4xx: ist["4xx"] += 1
            if is_5xx: ist["5xx"] += 1
            if is_timeout: ist["timeouts"] += 1
            ist["lats"].append(duration_ms)
            ist["req_bytes"] += req_bytes
            ist["resp_bytes"] += resp_bytes
            if ts_ms < ist["first_seen"]: ist["first_seen"] = ts_ms
            if ts_ms > ist["last_seen"]: ist["last_seen"] = ts_ms

    # Format rows for ClickHouse
    service_rows = []
    for (b5m, caller, target, ev_type, ev_detail, conf), st in service_edges_map.items():
        cnt = st["count"]
        st["lats"].sort()
        p50 = st["lats"][int(cnt * 0.50)]
        p95 = st["lats"][min(cnt - 1, int(cnt * 0.95))]
        p99 = st["lats"][min(cnt - 1, int(cnt * 0.99))]
        service_rows.append([
            b5m, caller, target, cnt, st["errors"], st["4xx"], st["5xx"], st["timeouts"],
            0, 0, st["lat_sum"], p50, p95, p99, st["req_bytes"], st["resp_bytes"],
            len(st["principals"]), len(st["ips"]), st["anon"], st["first_seen"], st["last_seen"],
            ev_type, ev_detail, conf, now_ms
        ])

    api_rows = []
    for (b5m, caller, c_api, target, t_api, ev_type, ev_detail, conf), ast in api_edges_map.items():
        cnt = ast["count"]
        ast["lats"].sort()
        p50 = ast["lats"][int(cnt * 0.50)]
        p95 = ast["lats"][min(cnt - 1, int(cnt * 0.95))]
        p99 = ast["lats"][min(cnt - 1, int(cnt * 0.99))]
        api_rows.append([
            b5m, caller, c_api, target, t_api, cnt, ast["errors"], ast["4xx"], ast["5xx"], ast["timeouts"],
            0, 0, ast["lat_sum"], p50, p95, p99, ast["req_bytes"], ast["resp_bytes"],
            len(ast["principals"]), len(ast["ips"]), ast["anon"], ast["first_seen"], ast["last_seen"],
            ev_type, ev_detail, conf, now_ms
        ])

    principal_rows = []
    for (b5m, user, caller, c_api, target, t_api, ev_type, ev_detail, conf), pst in principal_edges_map.items():
        cnt = pst["count"]
        pst["lats"].sort()
        p50 = pst["lats"][int(cnt * 0.50)]
        p95 = pst["lats"][min(cnt - 1, int(cnt * 0.95))]
        p99 = pst["lats"][min(cnt - 1, int(cnt * 0.99))]
        principal_rows.append([
            b5m, user, caller, c_api, target, t_api, cnt, pst["errors"], pst["4xx"], pst["5xx"], pst["timeouts"],
            0, 0, pst["lat_sum"], p50, p95, p99, pst["req_bytes"], pst["resp_bytes"],
            1, len(pst["ips"]), pst["anon"], pst["first_seen"], pst["last_seen"],
            ev_type, ev_detail, conf, now_ms
        ])

    ip_rows = []
    for (b5m, user, ip, target, t_api, caller, is_new_ip), ist in ip_edges_map.items():
        cnt = ist["count"]
        ist["lats"].sort()
        p95 = ist["lats"][min(cnt - 1, int(cnt * 0.95))]
        role, label, confidence_str = classify_source_ip_role(ip)
        is_lb = 1 if role in ("load_balancer", "reverse_proxy", "nat_gateway") else 0
        ip_rows.append([
            b5m, user, ip, target, t_api, caller, cnt, ist["errors"], ist["4xx"], ist["5xx"], ist["timeouts"],
            p95, ist["req_bytes"], ist["resp_bytes"], ist["first_seen"], ist["last_seen"],
            is_lb, role, label, confidence_str, is_new_ip, now_ms
        ])

    # Insert into ClickHouse
    batch_size = 5000
    with get_connection() as db:
        cols_s = [c[0] for c in db.execute("DESCRIBE TABLE topology_service_edges_5m").fetchall()]
        cols_a = [c[0] for c in db.execute("DESCRIBE TABLE topology_api_edges_5m").fetchall()]
        cols_p = [c[0] for c in db.execute("DESCRIBE TABLE topology_principal_edges_5m").fetchall()]
        cols_ip = [c[0] for c in db.execute("DESCRIBE TABLE topology_principal_ip_5m").fetchall()]

        for i in range(0, len(service_rows), batch_size):
            db.client.insert("topology_service_edges_5m", service_rows[i:i + batch_size], column_names=cols_s)
        for i in range(0, len(api_rows), batch_size):
            db.client.insert("topology_api_edges_5m", api_rows[i:i + batch_size], column_names=cols_a)
        for i in range(0, len(principal_rows), batch_size):
            db.client.insert("topology_principal_edges_5m", principal_rows[i:i + batch_size], column_names=cols_p)
        for i in range(0, len(ip_rows), batch_size):
            db.client.insert("topology_principal_ip_5m", ip_rows[i:i + batch_size], column_names=cols_ip)

        # Populate current tables with latest entries
        if service_rows:
            db.client.insert("topology_service_current", service_rows[-batch_size:], column_names=cols_s)
        if api_rows:
            db.client.insert("topology_api_current", api_rows[-batch_size:], column_names=cols_a)
        if principal_rows:
            db.client.insert("topology_principal_current", principal_rows[-batch_size:], column_names=cols_p)
        if ip_rows:
            db.client.insert("topology_principal_ip_current", ip_rows[-batch_size:], column_names=cols_ip)

    print(f"  ClickHouse topology 5m tables saved ({len(service_rows):,} svc, {len(api_rows):,} api, {len(principal_rows):,} usr, {len(ip_rows):,} ip rows)")

def derive_analytics(now_sec: float, start_sec: float, injected_windows: set[int]):
    print("\n--- Running Derivations: Rollups, Baselines, Anomalies & Principal Intelligence ---")
    t0 = time.time()

    t1 = time.time()
    baseline_cutoff = int(start_sec + (7 * 86400))
    print(f"Stage 1/4: Rebuilding historical median & MAD baselines (cutoff at Day 7: {datetime.fromtimestamp(baseline_cutoff, timezone.utc).isoformat()})...")
    base_count = rebuild_baselines(max_bucket_start=baseline_cutoff)
    print(f"  Baselines computed: {base_count} in {round(time.time() - t1, 2)}s")

    t2 = time.time()
    print("Stage 2/4: Deriving principal behavioral profiles, shifts & incidents across all 10 days...")
    p_result = process_principal_intelligence(force_bootstrap=True)
    print(f"  Principals processed: {p_result} in {round(time.time() - t2, 2)}s")

    t3 = time.time()
    print("Stage 3/4: Evaluating anomaly detection rules across target 5m windows on Days 7, 8, and 9...")
    # Sample 1 window every 2 hours on Days 7, 8, 9
    sample_windows = set()
    curr = baseline_cutoff
    while curr <= now_sec:
        sample_windows.add((int(curr) // 300) * 300)
        curr += 7200  # every 2 hours

    # Include last 12 windows (last 1 hour up to now_sec)
    for m in range(12):
        sample_windows.add((int(now_sec - (m * 300)) // 300) * 300)

    eval_windows = sorted(injected_windows | {w for w in sample_windows if w >= baseline_cutoff})

    all_anomalies = []
    for w in eval_windows:
        found = detect_anomalies(window_start_sec=w, window_end_sec=w + 300)
        all_anomalies.extend(found)
    print(f"  Anomalies detected: {len(all_anomalies)} across {len(eval_windows)} 5m windows on Days 7, 8, 9 in {round(time.time() - t3, 2)}s")

    t4 = time.time()
    print("Stage 4/4: Updating Prometheus worker metrics...")
    prom_snap = update_worker_prometheus_metrics(duration_sec=round(time.time() - t0, 2))
    print(f"  Prometheus metrics updated in {round(time.time() - t4, 2)}s: {prom_snap}")

    print("\n--- 10-Day Dataset Generation & Derivations Finished Successfully ---")


def main():
    parser = argparse.ArgumentParser(description="Wipe databases and generate 10-day dataset.")
    parser.add_argument("--no-wipe", action="store_true", help="Skip wiping databases before generation")
    parser.add_argument("--scale", type=int, default=10, help="Scale multiplier for data density (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible anomaly assignment (default: 42)")
    args = parser.parse_args()

    random.seed(args.seed)

    now_sec = float((int(time.time()) // 60) * 60)  # align to minute
    day_sec = 86400
    start_sec = now_sec - (10 * day_sec)

    if not args.no_wipe:
        print("Stage 0: Wiping previous database records cleanly...")
        wipe_clickhouse()
        wipe_elasticsearch()
        try:
            truncate_system_logs()
        except Exception as e:
            print(f"Note on system logs truncation: {e}")

    # Step 1: Generate 10-day raw trace transactions with new enterprise personas and randomized anomalies on Days 7, 8, 9
    records, injected_windows = generate_10day_raw_traces(now_sec, scale=args.scale)

    # Step 2: Aggregate 10-day records into metric_buckets (both 1m and 5m) and topology edges directly
    aggregate_records_and_save(records)

    # Step 2b: Materialize interactive topology rollups. Bandwidth is already in metric_buckets.
    save_topology_rollups(records)

    # Step 3: Ingest into Elasticsearch
    bulk_insert_es(records)

    # Step 4: Insert into ClickHouse (1-day TTL preserves latest 24 hours)
    insert_clickhouse_traces(records)

    # Step 5: Run analytics derivations
    derive_analytics(now_sec, start_sec, injected_windows)


if __name__ == "__main__":
    main()

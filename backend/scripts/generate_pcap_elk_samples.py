#!/usr/bin/env python3
"""
generate_traces.py — High-Performance OTel ELK APM Trace & Behavioral Change Generator.

Redesigned for TraceScope's expanded observability scope:
  - 9 Multi-Tier Microservices (Edge Gateway, Customer, Order, Catalog, Payment, Billing, Inventory, Notification, Admin).
  - 13 Authentic PCAP & Enterprise Identities (myViettel, cm2.0, sale, vtp, product, pm_mini_app, chatbot, guest_checkout_partner, b2b, admin, cron, pos, support).
  - Ground-Truth Observability Detectors (Traffic Spike, Traffic Drop, Tail Latency, Cascading 5xx, Architectural Drift, Novel Operation).
  - Full User Intelligence Behavior Engine (USERNAME_FIRST_SEEN, NEW_CALLER, NEW_SOURCE_IP, NEW_TARGET, NEW_OPERATION, UNUSUAL_TIME, DORMANT_REACTIVATED, Credential Abuse).
  - 75/25 Historical Bootstrap Boundary (Oldest 75% forms clean baseline; newest 25% contains behavioral drifts).
"""

from __future__ import annotations
import argparse
import gzip
import json
import math
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from anomalies import AnomalyContext, AnomalyManager
except ImportError:
    from backend.scripts.anomalies import AnomalyContext, AnomalyManager


SERVICES = [
    {
        "name": "apex-edge-gateway",
        "group": "EdgeGateway",
        "module": "gateway-routing",
        "ip": "10.150.10.1",
        "port": 443,
        "is_gateway": True,
        "nodes": ["edge-gw-node-01", "edge-gw-node-02", "edge-gw-node-03"],
        "operations": [
            {"url": "/api/v2/checkout/submitOrder", "path": "/api/v2/checkout/submitOrder", "route": "/api/v2/checkout/*", "name": "CheckoutApi/submitOrder", "method": "POST", "base_latency_us": 650000, "std_us": 90000},
            {"url": "/api/v2/catalog/search", "path": "/api/v2/catalog/search", "route": "/api/v2/catalog/*", "name": "CatalogApi/searchProducts", "method": "GET", "base_latency_us": 140000, "std_us": 25000},
            {"url": "/api/v2/subscriber/profile", "path": "/api/v2/subscriber/profile", "route": "/api/v2/subscriber/*", "name": "SubscriberApi/getProfile", "method": "GET", "base_latency_us": 95000, "std_us": 18000},
            {"url": "/api/v2/billing/balance", "path": "/api/v2/billing/balance", "route": "/api/v2/billing/*", "name": "BillingApi/queryBalance", "method": "GET", "base_latency_us": 120000, "std_us": 22000}
        ]
    },
    {
        "name": "apex-customer-service",
        "group": "CustomerService",
        "module": "customer-profile",
        "ip": "10.150.20.14",
        "port": 8084,
        "is_gateway": False,
        "nodes": ["cust-node-01", "cust-node-02"],
        "operations": [
            {"url": "/api/v2/customers/getProfile", "path": "/api/v2/customers/getProfile", "route": "/api/v2/customers/*", "name": "CustomerService/getProfile", "method": "GET", "base_latency_us": 85000, "std_us": 15000},
            {"url": "/api/v2/customers/updateAddress", "path": "/api/v2/customers/updateAddress", "route": "/api/v2/customers/*", "name": "CustomerService/updateAddress", "method": "POST", "base_latency_us": 180000, "std_us": 35000},
            {"url": "/api/v2/customers/verifyMsisdn", "path": "/api/v2/customers/verifyMsisdn", "route": "/api/v2/customers/*", "name": "CustomerService/verifyMsisdn", "method": "GET", "base_latency_us": 70000, "std_us": 12000}
        ]
    },
    {
        "name": "apex-order-service",
        "group": "OrderService",
        "module": "order-processing",
        "ip": "10.150.20.11",
        "port": 8081,
        "is_gateway": False,
        "nodes": ["order-proc-01", "order-proc-02", "order-proc-03"],
        "operations": [
            {"url": "/api/v2/orders/createOrder", "path": "/api/v2/orders/createOrder", "route": "/api/v2/orders/*", "name": "OrderService/createOrder", "method": "POST", "base_latency_us": 350000, "std_us": 60000},
            {"url": "/api/v2/orders/validateOrderLimits", "path": "/api/v2/orders/validateOrderLimits", "route": "/api/v2/orders/*", "name": "OrderService/validateOrderLimits", "method": "POST", "base_latency_us": 140000, "std_us": 25000},
            {"url": "/api/v2/orders/cancelReservation", "path": "/api/v2/orders/cancelReservation", "route": "/api/v2/orders/*", "name": "OrderService/cancelReservation", "method": "POST", "base_latency_us": 120000, "std_us": 20000}
        ]
    },
    {
        "name": "apex-catalog-service",
        "group": "CatalogService",
        "module": "catalog-engine",
        "ip": "10.150.20.12",
        "port": 8082,
        "is_gateway": False,
        "nodes": ["catalog-node-01", "catalog-node-02"],
        "operations": [
            {"url": "/api/v2/catalog/items/details", "path": "/api/v2/catalog/items/details", "route": "/api/v2/catalog/*", "name": "CatalogService/getItemDetails", "method": "GET", "base_latency_us": 90000, "std_us": 18000},
            {"url": "/api/v2/catalog/packages/list", "path": "/api/v2/catalog/packages/list", "route": "/api/v2/catalog/*", "name": "CatalogService/listPackages", "method": "GET", "base_latency_us": 75000, "std_us": 12000}
        ]
    },
    {
        "name": "apex-payment-service",
        "group": "PayService",
        "module": "payment-settlement",
        "ip": "10.150.20.13",
        "port": 8083,
        "is_gateway": False,
        "nodes": ["pay-settle-01", "pay-settle-02"],
        "operations": [
            {"url": "/api/v2/payments/chargeCard", "path": "/api/v2/payments/chargeCard", "route": "/api/v2/payments/*", "name": "PayService/chargeCard", "method": "POST", "base_latency_us": 450000, "std_us": 80000},
            {"url": "/api/v2/payments/settleLedger", "path": "/api/v2/payments/settleLedger", "route": "/api/v2/payments/*", "name": "PayService/settleLedger", "method": "POST", "base_latency_us": 320000, "std_us": 60000},
            {"url": "/api/v2/payments/issueRefund", "path": "/api/v2/payments/issueRefund", "route": "/api/v2/payments/*", "name": "PayService/issueRefund", "method": "POST", "base_latency_us": 250000, "std_us": 45000}
        ]
    },
    {
        "name": "apex-billing-service",
        "group": "BillingService",
        "module": "billing-ledger",
        "ip": "10.150.20.16",
        "port": 8086,
        "is_gateway": False,
        "nodes": ["billing-node-01", "billing-node-02"],
        "operations": [
            {"url": "/api/v2/billing/calculateUsageTax", "path": "/api/v2/billing/calculateUsageTax", "route": "/api/v2/billing/*", "name": "BillingService/calculateUsageTax", "method": "POST", "base_latency_us": 220000, "std_us": 40000},
            {"url": "/api/v2/billing/generateInvoiceItem", "path": "/api/v2/billing/generateInvoiceItem", "route": "/api/v2/billing/*", "name": "BillingService/generateInvoiceItem", "method": "POST", "base_latency_us": 310000, "std_us": 55000},
            {"url": "/api/v2/billing/queryAccountBalance", "path": "/api/v2/billing/queryAccountBalance", "route": "/api/v2/billing/*", "name": "BillingService/queryAccountBalance", "method": "GET", "base_latency_us": 95000, "std_us": 16000}
        ]
    },
    {
        "name": "apex-inventory-service",
        "group": "InventoryService",
        "module": "inventory-warehouse",
        "ip": "10.150.20.15",
        "port": 8085,
        "is_gateway": False,
        "nodes": ["inv-node-01", "inv-node-02"],
        "operations": [
            {"url": "/api/v2/inventory/reserveStock", "path": "/api/v2/inventory/reserveStock", "route": "/api/v2/inventory/*", "name": "InventoryService/reserveStock", "method": "POST", "base_latency_us": 160000, "std_us": 30000},
            {"url": "/api/v2/inventory/checkAvailability", "path": "/api/v2/inventory/checkAvailability", "route": "/api/v2/inventory/*", "name": "InventoryService/checkAvailability", "method": "GET", "base_latency_us": 65000, "std_us": 12000}
        ]
    },
    {
        "name": "apex-notification-service",
        "group": "NotificationService",
        "module": "message-dispatch",
        "ip": "10.150.20.17",
        "port": 8087,
        "is_gateway": False,
        "nodes": ["notify-node-01", "notify-node-02"],
        "operations": [
            {"url": "/api/v2/notifications/sendSmsOtp", "path": "/api/v2/notifications/sendSmsOtp", "route": "/api/v2/notifications/*", "name": "NotificationService/sendSmsOtp", "method": "POST", "base_latency_us": 110000, "std_us": 20000},
            {"url": "/api/v2/notifications/pushAlert", "path": "/api/v2/notifications/pushAlert", "route": "/api/v2/notifications/*", "name": "NotificationService/pushAlert", "method": "POST", "base_latency_us": 90000, "std_us": 15000}
        ]
    },
    {
        "name": "apex-admin-service",
        "group": "AdminService",
        "module": "admin-control",
        "ip": "10.150.20.18",
        "port": 8088,
        "is_gateway": False,
        "nodes": ["admin-node-01"],
        "operations": [
            {"url": "/api/v2/admin/systemConfig", "path": "/api/v2/admin/systemConfig", "route": "/api/v2/admin/*", "name": "AdminService/systemConfig", "method": "GET", "base_latency_us": 105000, "std_us": 18000},
            {"url": "/api/v2/admin/modifyPolicy", "path": "/api/v2/admin/modifyPolicy", "route": "/api/v2/admin/*", "name": "AdminService/modifyPolicy", "method": "POST", "base_latency_us": 210000, "std_us": 40000}
        ]
    }
]

SVC_BY_NAME = {s["name"]: s for s in SERVICES}

CALLER_DEPENDENCIES = {
    "apex-edge-gateway": [None],
    "apex-customer-service": ["apex-edge-gateway", None],
    "apex-order-service": ["apex-edge-gateway", "apex-customer-service"],
    "apex-catalog-service": ["apex-edge-gateway", "apex-order-service"],
    "apex-payment-service": ["apex-order-service", "apex-edge-gateway"],
    "apex-billing-service": ["apex-payment-service", "apex-order-service"],
    "apex-inventory-service": ["apex-order-service", "apex-catalog-service"],
    "apex-notification-service": ["apex-order-service", "apex-customer-service"],
    "apex-admin-service": ["apex-edge-gateway", None]
}

# Authentic Identities directly derived from production PCAP captures + New Identity
PRINCIPALS = [
    ("myViettel", "Basic bXlWaWV0dGVsOm15VmllVHRlbF9hcHBfdG9rZW5fOTk="),
    ("cm2.0", "Basic Y20yLjA6Y20yX3ZpZXR0ZWxfYXBpX3Rva2Vu"),
    ("sale", "Basic c2FsZTp2dF9zYWxlX3Bhc3N3b3JkXzk5"),
    ("vtp", "Basic dnRwOnZ0cF9sb2dpc3RpY3Nfa2V5"),
    ("product", "Basic cHJvZHVjdDpwcm9kdWN0X2NhdGFsb2dfc2VjcmV0"),
    ("pm_mini_app", "Basic cG1fbWluaV9hcHA6bWluaV9hcHBfc2VjcmV0XzEyMw=="),
    ("chatbot", "Basic Y2hhdGJvdDpjaGF0Ym90X2NvbnZlcnNhdGlvbl9rZXk="),
    ("guest_checkout_partner", "Basic Z3Vlc3RfY2hlY2tvdXRfcGFydG5lcjpndWVzdF9zZWNyZXRfMTAx"),
    ("b2b_enterprise_client", "Basic YjJiX2VudGVycHJpc2VfY2xpZW50OmVudGVycHJpc2VfdG9rZW4="),
    ("admin_ops_console", "Basic YWRtaW5fb3BzX2NvbnNvbGU6YWRtaW5fc2VjdXJlXzk5"),
    ("cron_batch_reconciler", "Basic Y3Jvbl9iYXRjaF9yZWNvbmNpbGVyOmJhdGNoX3Bhc3N3b3Jk"),
    ("pos_retail_terminal", "Basic cG9zX3JldGFpbF90ZXJtaW5hbDpwYXNzd29yZF8xMjM="),
    ("support_agent_tier3", "Basic c3VwcG9ydF9hZ2VudF90aWVyMzpjcmVkZW50aWFsX3M3Nw==")
]

# Principal canonical affinities during baseline (0.0h .. 18.0h)
BASELINE_AFFINITIES = {
    "product": {
        "services": ["apex-catalog-service"],
        "ips": ["10.240.147.247", "10.240.147.249"]
    },
    "sale": {
        "services": ["apex-edge-gateway", "apex-order-service", "apex-customer-service"],
        "ips": ["10.240.147.247", "10.240.147.249"]
    },
    "vtp": {
        "services": ["apex-order-service", "apex-inventory-service"],
        "callers": ["apex-edge-gateway"],
        "ips": ["10.150.4.11", "10.150.4.88"]
    },
    "pm_mini_app": {
        "services": ["apex-catalog-service", "apex-customer-service"],
        "ips": ["172.16.12.19", "172.16.10.45"]
    },
    "chatbot": {
        "services": ["apex-customer-service", "apex-catalog-service"],
        "ips": ["172.16.12.19", "10.240.147.247"]
    }
}

CLIENT_IPS = [
    "10.240.147.247",
    "10.240.147.249",
    "10.150.4.11",
    "10.150.4.88",
    "172.16.12.19",
    "172.16.10.45",
    "115.78.22.84",
    "115.78.91.102"
]

USER_AGENTS = [
    "MyViettel/5.8.0 (iPhone; iOS 17.4; Scale/3.00)",
    "MyViettel/5.8.0 (Android 14; SM-S928B)",
    "Viettel-SalesPOS/3.2.1",
    "Go-http-client/2.0",
    "Apache-HttpClient/5.2.1 (Java/17.0.9)",
    "okhttp/4.12.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
]


def format_record_fast(
    index_name: str,
    doc_id: str,
    ts_us: int,
    iso_time: str,
    ingested_iso_time: str,
    trace_id: str,
    span_id: str,
    parent_span_id: Optional[str],
    svc: dict,
    op_path: str,
    op_url: str,
    op_route: str,
    op_name: str,
    op_method: str,
    auth_header: str,
    client_ip: str,
    node_name: str,
    user_agent: str,
    duration_us: int,
    status_code: int,
    outcome: str,
    result: str,
    caller_service: Optional[str] = None
) -> str:
    parent_part = f', "parent": {{"id": "{parent_span_id}"}}' if parent_span_id else ""
    caller_label = f', "caller_service": "{caller_service}"' if caller_service else ""
    peer_part = f', "peer": {{"service": {{"name": "{caller_service}"}}}}' if caller_service else ""
    return (
        f'{{"_index":"{index_name}","_type":"_doc","_id":"{doc_id}","_version":1,"_score":1,'
        f'"_source":{{'
        f'"agent":{{"name":"opentelemetry/java","version":"1.30.1"}},'
        f'"process":{{"pid":37621,"command_line":"/opt/apex/jvm/bin/java -Dotel.resource.attributes=service.name={svc["name"]},service.group.id={svc["group"]},service.module.id={svc["module"]} -jar /opt/apex/services/{svc["name"]}.jar","executable":"/opt/apex/jvm/bin/java"}},'
        f'"source":{{"ip":"{client_ip}"}},'
        f'"processor":{{"name":"transaction","event":"transaction"}},'
        f'"url":{{"path":"{op_path}","original":"{op_url}","scheme":"http","port":{svc["port"]},"domain":"{svc["ip"]}","full":"http://{svc["ip"]}:{svc["port"]}{op_path}"}},'
        f'"labels":{{"net_protocol_name":"http","http_route":"{op_route}","net_sock_host_addr":"{svc["ip"]}","net_sock_peer_port":44240,"telemetry_auto_version":"1.30.0","http_response_content_length":1245,"process_runtime_description":"Eclipse Adoptium OpenJDK 64-Bit Server VM 17.0.9+9","service_module_id":"{svc["module"]}","thread_id":112,"thread_name":"http-nio-{svc["port"]}-exec-6","net_sock_peer_addr":"{client_ip}","user_agent_original":"{user_agent}","http_request_content_length":957,"net_protocol_version":"1.1","http_request_header_authorization":["{auth_header}"],"service_group_id":"{svc["group"]}"{caller_label}}},'
        f'"observer":{{"hostname":"apex-telemetry-collector-01","id":"7f9a12c4-83e1-4560-b80c-ea118f6209ba","ephemeral_id":"8432a5c3-702c-4095-b89a-a2540156a99b","type":"apm-server","version":"8.11.0","version_major":8}},'
        f'"trace":{{"id":"{trace_id}"}}{parent_part}{peer_part},'
        f'"@timestamp":"{iso_time}",'
        f'"ecs":{{"version":"1.11.0"}},'
        f'"service":{{"node":{{"name":"{node_name}"}},"environment":"prod","framework":{{"name":"io.opentelemetry.spring-boot-3.0","version":"1.30.1"}},"name":"{svc["name"]}","runtime":{{"name":"OpenJDK Runtime Environment","version":"17.0.9+9"}},"language":{{"name":"java"}}}},'
        f'"host":{{"hostname":"{node_name}","os":{{"type":"linux","platform":"linux","full":"Linux 5.15.0-1049-aws x86_64"}},"name":"{node_name}","architecture":"amd64"}},'
        f'"http":{{"request":{{"method":"{op_method}"}},"response":{{"status_code":{status_code}}}}},'
        f'"client":{{"ip":"{client_ip}"}},'
        f'"event":{{"ingested":"{ingested_iso_time}","outcome":"{outcome}"}},'
        f'"transaction":{{"result":"{result}","duration":{{"us":{duration_us}}},"name":"{op_name}","id":"{span_id}","type":"request","sampled":true}},'
        f'"timestamp":{{"us":{ts_us}}}'
        f'}}}}'
    )


def main():
    parser = argparse.ArgumentParser(description="TraceScope OTel ELK APM Data, Anomaly & User Behavioral Change Generator")
    parser.add_argument("--count", type=int, default=2_000_000, help="Total transaction records to generate (default: 2,000,000)")
    parser.add_argument("--hours", type=float, default=24.0, help="Timespan in hours backwards from now (default: 24.0)")
    parser.add_argument("--days", type=float, default=None, help="Timespan in days backwards from now (e.g. 15 for 15 days, overrides --hours)")
    parser.add_argument("--output", type=str, default="/home/ubuntu/Viettel/Data/otel_elk_traces_2m.jsonl.gz", help="Output .jsonl.gz file")
    parser.add_argument("--preview", type=str, default="/home/ubuntu/Viettel/Data/otel_elk_sample_preview.json", help="Preview JSON file with first 100 records")
    parser.add_argument("--chunk-size", type=int, default=10000, help="Buffer chunk size")
    parser.add_argument("--anomalies", type=str, default="all", help="Comma-separated scenario names or 'all' or 'none'")
    parser.add_argument("--list-anomalies", action="store_true", help="Print available scenarios and exit")
    parser.add_argument("--start-time", type=int, default=None, help="Custom start unix timestamp in seconds")
    parser.add_argument("--end-time", type=int, default=None, help="Custom end unix timestamp in seconds")
    args = parser.parse_args()

    if args.days is not None:
        args.hours = args.days * 24.0

    now_sec = int(time.time())
    end_time_sec = args.end_time if args.end_time else now_sec
    start_time_sec = args.start_time if args.start_time else (end_time_sec - int(args.hours * 3600))
    total_window_sec = max(1, end_time_sec - start_time_sec)
    bootstrap_cutoff_hour = args.hours * 0.75  # 75% historical bootstrap cutoff

    # Initialize Anomaly Manager
    enabled_set = set(args.anomalies.split(",")) if args.anomalies != "all" else None
    if args.anomalies == "none":
        enabled_set = set()
    mgr = AnomalyManager.create_default(
        enabled_names=enabled_set,
        bootstrap_cutoff_hour=bootstrap_cutoff_hour,
        total_hours=args.hours
    )

    if args.list_anomalies:
        print("=" * 96)
        print(" TraceScope Observability Detectors & User Intelligence Scenarios")
        print("=" * 96)
        print(" [OBSERVABILITY DETECTORS 1-8]")
        for s in mgr.scenarios:
            if s.category != "user_intelligence":
                win_str = (
                    ", ".join(f"{w[0]:04.1f}h-{w[1]:04.1f}h" for w in s.windows)
                    if getattr(s, "windows", None)
                    else f"{s.start_hour:04.1f}h - {s.end_hour:04.1f}h"
                )
                print(f" • {s.name:<28} [{s.category:<12}] Window: {win_str} | {s.description}")
        print("\n [USER INTELLIGENCE BEHAVIORAL CHANGES (principal_relationships.py)]")
        for s in mgr.scenarios:
            if s.category == "user_intelligence":
                win_str = (
                    ", ".join(f"{w[0]:04.1f}h-{w[1]:04.1f}h" for w in s.windows)
                    if getattr(s, "windows", None)
                    else f"{s.start_hour:04.1f}h - {s.end_hour:04.1f}h"
                )
                print(f" • {s.name:<28} [{s.category:<12}] Window: {win_str} | {s.description}")
        print("=" * 96)
        return

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    start_gm = time.gmtime(start_time_sec)
    end_gm = time.gmtime(end_time_sec)
    start_str = f"{start_gm.tm_year:04d}-{start_gm.tm_mon:02d}-{start_gm.tm_mday:02d} {start_gm.tm_hour:02d}:{start_gm.tm_min:02d}:{start_gm.tm_sec:02d} UTC"
    end_str = f"{end_gm.tm_year:04d}-{end_gm.tm_mon:02d}-{end_gm.tm_mday:02d} {end_gm.tm_hour:02d}:{end_gm.tm_min:02d}:{end_gm.tm_sec:02d} UTC"

    print("=" * 80)
    print(" TraceScope OTel ELK APM Data, Anomaly & User Behavioral Generator")
    print(f" Record Count:            {args.count:,}")
    print(f" Timespan Window:         {args.hours} hours ({total_window_sec:,} seconds)")
    print(f" Historical Baseline:     0.0h - {bootstrap_cutoff_hour:04.1f}h (oldest 75%)")
    print(f" Behavioral Drift Window: {bootstrap_cutoff_hour:04.1f}h - {args.hours:04.1f}h (newest 25%)")
    print(f" From:                    {start_str}")
    print(f" To:                      {end_str}")
    print(f" Active Scenarios:        {args.anomalies}")
    print(f" Output Target:           {args.output}")
    print("=" * 80)

    t0 = time.time()
    preview_records = []
    generated = 0

    service_weights = [0.30, 0.16, 0.16, 0.12, 0.10, 0.06, 0.05, 0.03, 0.02]

    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=1) as gz_out:
        lines_buffer = []

        while generated < args.count:
            progress = generated / args.count
            trace_time_sec = start_time_sec + int(progress * total_window_sec) + random.randint(0, 4)
            ts_us = trace_time_sec * 1_000_000 + random.randint(1000, 999000)
            elapsed_hours = (trace_time_sec - start_time_sec) / 3600.0

            gm = time.gmtime(trace_time_sec)
            ctx = AnomalyContext(
                progress=progress,
                trace_time_sec=trace_time_sec,
                hour_of_day=gm.tm_hour,
                window_start_sec=start_time_sec,
                window_end_sec=end_time_sec,
                total_duration_sec=total_window_sec,
                bootstrap_cutoff_hour=bootstrap_cutoff_hour
            )

            # Choose base service
            svc = random.choices(SERVICES, weights=service_weights)[0]

            # Check if traffic drop suppresses this transaction
            if mgr.should_drop_transaction(svc["name"], ctx):
                continue

            # Check if traffic spike boosts this service
            spike_mult = mgr.get_service_traffic_multiplier(svc["name"], ctx)
            if spike_mult > 1.0 and random.random() > (1.0 / spike_mult):
                pass

            op = random.choice(svc["operations"])

            # Identity selection with baseline filtering for new/dormant identities
            valid_principals = [p for p in PRINCIPALS if not mgr.is_principal_suppressed_for_baseline(p[0], ctx)]
            principal_name, auth_header = random.choice(valid_principals) if valid_principals else PRINCIPALS[0]

            # Baseline affinity enforcement prior to cutoff (hours 0 .. 18)
            client_ip = random.choice(CLIENT_IPS)
            callers = CALLER_DEPENDENCIES.get(svc["name"], [None])
            caller_service = random.choice(callers)

            if elapsed_hours < bootstrap_cutoff_hour:
                affinity = BASELINE_AFFINITIES.get(principal_name)
                if affinity:
                    if "ips" in affinity:
                        client_ip = random.choice(affinity["ips"])
                    if "callers" in affinity and caller_service:
                        caller_service = random.choice(affinity["callers"])

            node_name = random.choice(svc["nodes"])
            user_agent = random.choice(USER_AGENTS)

            base_us = op["base_latency_us"]
            std_us = op["std_us"]
            duration_us = int(max(2000, base_us + random.randint(-std_us, std_us)))

            status_code = 200
            outcome = "success"
            result = "HTTP 2xx"

            if random.random() < 0.005:
                status_code = random.choice([400, 401, 403, 404, 500, 503])
                outcome = "failure"
                result = f"HTTP {status_code // 100}xx"

            # Mutable transaction envelope for anomaly & user change scenarios
            tx_dict = {
                "service_name": svc["name"],
                "caller_service": caller_service,
                "principal_name": principal_name,
                "auth_header": auth_header,
                "client_ip": client_ip,
                "duration_us": duration_us,
                "status_code": status_code,
                "outcome": outcome,
                "result": result,
                "path": op["path"],
                "url": op["url"],
                "route": op["route"],
                "op_name": op["name"],
                "op_method": op["method"]
            }

            # Evaluate and apply active anomalies and user behavioral changes
            mgr.apply_mutations(tx_dict, ctx)

            # Build trace identifiers
            trace_int = random.getrandbits(128)
            trace_id = f"{trace_int:032x}"
            span_int = random.getrandbits(64)
            span_id = f"{span_int:016x}"
            parent_span_id = f"{random.getrandbits(64):016x}" if tx_dict["caller_service"] else None
            doc_id = f"{trace_id[:10]}{span_id[:10]}"

            iso_time = f"{gm.tm_year:04d}-{gm.tm_mon:02d}-{gm.tm_mday:02d}T{gm.tm_hour:02d}:{gm.tm_min:02d}:{gm.tm_sec:02d}.{random.randint(100, 999):03d}Z"
            ingested_iso_time = f"{gm.tm_year:04d}-{gm.tm_mon:02d}-{gm.tm_mday:02d}T{gm.tm_hour:02d}:{gm.tm_min:02d}:{min(59, gm.tm_sec+15):02d}.{random.randint(100, 999):03d}Z"
            index_name = f"apm-apex-cluster:apm-8.11.0-transaction-{gm.tm_year:04d}.{gm.tm_mon:02d}.{gm.tm_mday:02d}-1"

            json_line = format_record_fast(
                index_name=index_name,
                doc_id=doc_id,
                ts_us=ts_us,
                iso_time=iso_time,
                ingested_iso_time=ingested_iso_time,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                svc=svc,
                op_path=tx_dict["path"],
                op_url=tx_dict["url"],
                op_route=tx_dict["route"],
                op_name=tx_dict["op_name"],
                op_method=tx_dict["op_method"],
                auth_header=tx_dict["auth_header"],
                client_ip=tx_dict["client_ip"],
                node_name=node_name,
                user_agent=user_agent,
                duration_us=tx_dict["duration_us"],
                status_code=tx_dict["status_code"],
                outcome=tx_dict["outcome"],
                result=tx_dict["result"],
                caller_service=tx_dict["caller_service"]
            )

            lines_buffer.append(json_line)
            if len(preview_records) < 100:
                try:
                    preview_records.append(json.loads(json_line))
                except Exception:
                    pass

            generated += 1

            if len(lines_buffer) >= args.chunk_size:
                gz_out.write("\n".join(lines_buffer) + "\n")
                lines_buffer.clear()
                if generated % 200_000 == 0 or generated == args.count:
                    rate = generated / max(0.001, (time.time() - t0))
                    pct = (generated / args.count) * 100
                    print(f" Progress: {generated:>9,} / {args.count:,} records ({pct:5.1f}%) | {rate:,.0f} rec/s | Elapsed: {time.time() - t0:.1f}s")

        if lines_buffer:
            gz_out.write("\n".join(lines_buffer) + "\n")
            lines_buffer.clear()

    total_time = time.time() - t0
    file_size_mb = os.path.getsize(args.output) / (1024 * 1024)

    print("-" * 80)
    print(f" Generation complete in {total_time:.2f}s ({args.count / total_time:,.0f} records/sec)")
    print(f" File written: {args.output} ({file_size_mb:.2f} MB)")

    if args.preview:
        with open(args.preview, "w", encoding="utf-8") as f_prev:
            json.dump(preview_records, f_prev, indent=2)
        print(f" Preview written: {args.preview} ({len(preview_records)} sample records)")

    print("\n" + "=" * 90)
    print(" INJECTED GROUND-TRUTH ANOMALIES & USER BEHAVIOR CHANGES")
    print("=" * 90)
    print(" [CORE OBSERVABILITY DETECTORS]")
    for s in mgr.get_injection_summary():
        if s["category"] != "user_intelligence":
            status = "ENABLED" if s["enabled"] else "DISABLED"
            print(f" [{status}] {s['name']:<24} | Window: {s['active_window_hours']:<11} | Injected: {s['injected_count']:>7,} tx | {s['description']}")

    print("\n [USER INTELLIGENCE BEHAVIORAL CHANGES]")
    for s in mgr.get_injection_summary():
        if s["category"] == "user_intelligence":
            status = "ENABLED" if s["enabled"] else "DISABLED"
            print(f" [{status}] {s['name']:<24} | Window: {s['active_window_hours']:<11} | Injected: {s['injected_count']:>7,} tx | {s['description']}")
    print("=" * 90)


if __name__ == "__main__":
    main()

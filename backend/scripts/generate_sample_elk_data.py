#!/usr/bin/env python3
"""Generate realistic APM transaction dataset directly into Elasticsearch testbed.

Populates Elasticsearch NodePort 32073 with structured transactions containing:
- Multi-tier service operations and caller-target dependencies
- Canonical user identities and supporting source IP roles
- Normal baselines and deliberate behavioral anomalies / shifts
- Recent timestamps within the active 3-hour dashboard window
"""
from __future__ import annotations

import json
import random
import time
import urllib.request
from datetime import datetime, timezone

ES_URL = "http://127.0.0.1:32073"
INDEX_NAME = "apm-7.17.24-transaction-000001"

SERVICES = {
    "frontend-gateway": [
        ("GatewayService/route", "GET", 8.0, 3.0),
        ("GatewayService/health", "GET", 2.0, 1.0),
    ],
    "auth-service": [
        ("AuthService/login", "POST", 45.0, 15.0),
        ("AuthService/verifyToken", "POST", 12.0, 4.0),
        ("AuthService/refreshToken", "POST", 25.0, 8.0),
    ],
    "user-service": [
        ("UserService/getProfile", "GET", 20.0, 5.0),
        ("UserService/updateProfile", "PUT", 60.0, 15.0),
    ],
    "order-service": [
        ("OrderService/createOrder", "POST", 85.0, 20.0),
        ("OrderService/getOrder", "GET", 25.0, 6.0),
        ("OrderService/listOrders", "GET", 60.0, 15.0),
        ("OrderService/cancelOrder", "POST", 70.0, 18.0),
    ],
    "inventory-service": [
        ("InventoryService/checkStock", "GET", 15.0, 4.0),
        ("InventoryService/reserveStock", "POST", 35.0, 10.0),
    ],
    "payment-service": [
        ("PaymentService/chargeCard", "POST", 95.0, 25.0),
        ("PaymentService/refund", "POST", 80.0, 20.0),
    ],
    "billing-service": [
        ("BillingService/generateInvoice", "POST", 50.0, 12.0),
        ("BillingService/getInvoice", "GET", 22.0, 5.0),
    ],
    "notification-service": [
        ("NotificationService/sendEmail", "POST", 40.0, 10.0),
        ("NotificationService/sendSMS", "POST", 30.0, 8.0),
    ],
}

CALLERS_FOR_SERVICE = {
    "frontend-gateway": ["ingress-controller", "mobile-app", "web-portal"],
    "auth-service": ["frontend-gateway"],
    "user-service": ["frontend-gateway", "order-service"],
    "order-service": ["frontend-gateway"],
    "inventory-service": ["order-service"],
    "payment-service": ["order-service"],
    "billing-service": ["payment-service", "order-service"],
    "notification-service": ["order-service", "user-service"],
}

NORMAL_USERS = [
    "minh.ngoc",
    "linh.pham",
    "duong.nguyen",
    "thao.trang",
    "khanh.vu",
    "quang.bui",
    "hong.dang",
    "admin",
    "system_batch",
    "k6_probe_user",
    "-anonymous-",
]

CLIENT_IPS = [
    "113.190.234.12",
    "14.161.22.88",
    "27.72.105.41",
    "171.244.10.5",
    "123.24.18.99",
]

PROXIES = ["192.168.122.1", "10.240.10.15"]
LOAD_BALANCERS = ["10.244.0.1", "10.96.0.1"]


def hex_id(length: int = 16) -> str:
    return "".join(random.choices("0123456789abcdef", k=length))


def generate_records(total: int = 12000) -> list[dict]:
    records = []
    now_sec = time.time()
    # Span last 3.5 hours up to now
    start_sec = now_sec - (3.5 * 3600)

    # 1. Base traffic distribution (Normal Operations)
    print(f"Generating {total} transactions from {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to {datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}...")

    for i in range(total):
        # Time distribution: uniform over 3.5h with slight ramp toward present
        progress = random.random()
        t_sec = start_sec + (progress * (now_sec - start_sec))
        t_iso = datetime.fromtimestamp(t_sec, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Select service & operation
        service = random.choices(
            list(SERVICES.keys()),
            weights=[15, 12, 12, 25, 12, 10, 7, 7],
            k=1,
        )[0]
        op_info = random.choice(SERVICES[service])
        op_name, method, base_lat, lat_std = op_info

        caller = random.choice(CALLERS_FOR_SERVICE.get(service, ["frontend-gateway"]))

        # Select user identity
        user = random.choice(NORMAL_USERS)

        # IP attribution
        if random.random() < 0.70:
            client_ip = random.choice(CLIENT_IPS)
        elif random.random() < 0.85:
            client_ip = random.choice(PROXIES)
        else:
            client_ip = random.choice(LOAD_BALANCERS)

        # Latency & Status
        duration_ms = max(1.0, random.gauss(base_lat, lat_std))
        http_status = 200
        outcome = "success"

        # Rare background 4xx/5xx errors (~1.5%)
        if random.random() < 0.015:
            if random.random() < 0.7:
                http_status = random.choice([400, 404, 422])
            else:
                http_status = random.choice([500, 502, 503])
            outcome = "failure"

        # -----------------------------------------------------------------
        # Inject Specific Behavioral Anomalies & Change Scenarios
        # -----------------------------------------------------------------

        # Scenario A: "mallory" Rate Surge on payment-service/chargeCard in last 45m
        if t_sec > (now_sec - 45 * 60) and random.random() < 0.12:
            service = "payment-service"
            op_name, method, base_lat, lat_std = ("PaymentService/chargeCard", "POST", 110.0, 30.0)
            user = "mallory"
            caller = "order-service"
            client_ip = "45.134.22.10"
            duration_ms = max(20.0, random.gauss(base_lat, lat_std))

        # Scenario B: "oscar" Auth Failure Burst on auth-service & payment in last 30m
        elif t_sec > (now_sec - 30 * 60) and random.random() < 0.08:
            service = "auth-service"
            op_name, method, base_lat, lat_std = ("AuthService/login", "POST", 40.0, 10.0)
            user = "oscar"
            caller = "frontend-gateway"
            client_ip = "185.220.101.5"
            http_status = 401
            outcome = "failure"

        # Scenario C: "judy" New Target Relationship (introduced to billing-service in last 40m)
        elif t_sec > (now_sec - 40 * 60) and random.random() < 0.06:
            service = "billing-service"
            op_name, method = ("BillingService/generateInvoice", "POST")
            user = "judy"
            caller = "frontend-gateway"
            client_ip = random.choice(CLIENT_IPS)
            duration_ms = 65.0

        # Scenario D: "peggy" Latency Blowout on order-service/cancelOrder in last 1h
        elif t_sec > (now_sec - 60 * 60) and random.random() < 0.07:
            service = "order-service"
            op_name, method = ("OrderService/cancelOrder", "POST")
            user = "peggy"
            caller = "frontend-gateway"
            client_ip = "27.72.105.41"
            # Blown out latency (600ms - 1800ms)
            duration_ms = random.uniform(600.0, 1800.0)

        # Scenario E: "heidi" Dormant Reactivation (traffic only in last 20m via unfamiliar caller)
        elif t_sec > (now_sec - 20 * 60) and random.random() < 0.06:
            service = "user-service"
            op_name, method = ("UserService/updateProfile", "PUT")
            user = "heidi"
            caller = "batch-worker"
            client_ip = "10.240.99.12"
            duration_ms = 75.0

        # Scenario F: "ivan" Shared Credential (invoked across multiple callers)
        elif random.random() < 0.04:
            user = "ivan"
            caller = random.choice(["frontend-gateway", "batch-worker", "partner-api", "mobile-gateway"])

        doc = {
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
                "duration": {"us": int(duration_ms * 1000)},
                "result": f"HTTP {http_status // 100}xx",
                "outcome": outcome,
                "sampled": True,
            },
            "trace": {"id": hex_id(32)},
            "user": {"name": user},
            "client": {"ip": client_ip},
            "http": {
                "response": {"status_code": http_status},
                "request": {"method": method},
            },
            "labels": {
                "caller_service": caller,
                "client_address": client_ip,
                "http_response_status_code": http_status,
                "http_request_method": method,
            },
        }
        records.append(doc)

    records.sort(key=lambda r: r["@timestamp"])
    return records


def bulk_insert_es(records: list[dict], batch_size: int = 1000) -> int:
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            if resp_data.get("errors"):
                print(f"Warning: errors in bulk insert at chunk {i}: {resp_data.get('items', [])[:2]}")
            total_inserted += len(chunk)
            print(f"  Indexed {total_inserted}/{len(records)} records...")

    # Refresh index
    refresh_req = urllib.request.Request(f"{ES_URL}/{INDEX_NAME}/_refresh", method="POST")
    with urllib.request.urlopen(refresh_req, timeout=10) as resp:
        pass

    print(f"Successfully indexed and refreshed {total_inserted} records in Elasticsearch.")
    return total_inserted


if __name__ == "__main__":
    records = generate_records(total=12000)
    bulk_insert_es(records)

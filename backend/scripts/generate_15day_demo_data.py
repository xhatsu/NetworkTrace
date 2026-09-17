#!/usr/bin/env python3
"""Generate a 15-day, 5-user realistic demonstration dataset directly in Elasticsearch.

Personas (5 Users):
1. alice   - Steady golden baseline across all 15 days (low risk, high health).
2. bob     - Demonstrates Candidate Promotion: accesses new billing target on Days 10-15,
             meeting the 3+ days and 5+ windows rule to be promoted into established baseline.
3. mallory - Traffic Surge & Blast Radius: low baseline for 14 days, then massive payment surge
             with elevated latency and 5xx errors in the last 2 hours.
4. oscar   - Auth Attack: sporadic logins for 14 days, then 401 auth failure burst followed by
             success in the last 45 minutes from a foreign IP.
5. judy    - Off-Hours Rogue Access: daytime usage on Days 1-13, then off-hours access (03:00 UTC)
             to billing/admin targets from a new IP on Days 14-15.
"""
from __future__ import annotations

import json
import math
import os
import random
import time
import urllib.request
from datetime import datetime, timezone

ES_URL = "http://127.0.0.1:32073"
INDEX_NAME = "apm-7.17.24-transaction-000001"

SERVICES = {
    "frontend-gateway": [
        ("GatewayService/route", "GET", 8.0, 2.0),
        ("GatewayService/health", "GET", 2.0, 0.5),
    ],
    "auth-service": [
        ("AuthService/login", "POST", 40.0, 10.0),
        ("AuthService/verifyToken", "POST", 12.0, 3.0),
        ("AuthService/refreshToken", "POST", 25.0, 6.0),
    ],
    "user-service": [
        ("UserService/getProfile", "GET", 20.0, 4.0),
        ("UserService/updateProfile", "PUT", 55.0, 12.0),
    ],
    "order-service": [
        ("OrderService/createOrder", "POST", 80.0, 18.0),
        ("OrderService/getOrder", "GET", 22.0, 5.0),
        ("OrderService/listOrders", "GET", 50.0, 10.0),
    ],
    "inventory-service": [
        ("InventoryService/checkStock", "GET", 14.0, 3.0),
        ("InventoryService/reserveStock", "POST", 32.0, 8.0),
    ],
    "payment-service": [
        ("PaymentService/chargeCard", "POST", 90.0, 20.0),
        ("PaymentService/refund", "POST", 75.0, 15.0),
    ],
    "billing-service": [
        ("BillingService/generateInvoice", "POST", 45.0, 10.0),
        ("BillingService/getInvoice", "GET", 20.0, 4.0),
    ],
    "notification-service": [
        ("NotificationService/sendEmail", "POST", 35.0, 8.0),
        ("NotificationService/sendSMS", "POST", 28.0, 6.0),
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
        "user": {"name": user},
        "client": {"ip": client_ip},
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

def generate_15day_data() -> list[dict]:
    records = []
    now_sec = time.time()
    # 15 days total span
    day_sec = 86400
    start_sec = now_sec - (15 * day_sec)

    print(f"Generating 15-day dataset (5 users) from {datetime.fromtimestamp(start_sec, timezone.utc).isoformat()} to {datetime.fromtimestamp(now_sec, timezone.utc).isoformat()}...")

    # -------------------------------------------------------------------------
    # 1. ALICE: Steady Golden Baseline (Days 1 to 15)
    # -------------------------------------------------------------------------
    # ~500 requests per day during daytime hours (07:00 - 19:00 UTC)
    print("Generating persona 1/5: alice (Steady golden baseline)...")
    for day in range(15):
        day_base = start_sec + (day * day_sec)
        # Daytime 08:00 to 18:00 UTC
        day_start = day_base + (8 * 3600)
        day_end = day_base + (18 * 3600)
        if day_end > now_sec:
            day_end = now_sec
        if day_start >= day_end:
            continue

        reqs_today = random.randint(450, 550)
        for _ in range(reqs_today):
            t = random.uniform(day_start, day_end)
            service = random.choice(["user-service", "order-service", "inventory-service"])
            op_info = random.choice(SERVICES[service])
            op_name, method, base_lat, lat_std = op_info
            lat = max(2.0, random.gauss(base_lat, lat_std))
            status = 200 if random.random() > 0.005 else 404
            caller = random.choice(["web-portal", "frontend-gateway"])
            ip = random.choice(["192.168.1.50", "10.0.12.100"])  # corporate client / gateway
            records.append(build_apm_doc(t, "alice", service, op_name, method, caller, ip, lat, status))

    # -------------------------------------------------------------------------
    # 2. BOB: Candidate Promotion to Established Baseline
    # -------------------------------------------------------------------------
    # Days 1 to 9: Regular orders on order-service
    # Days 10 to 15: Regularly accesses BillingService/getInvoice on billing-service!
    # Repeated on 6 distinct days and > 20 distinct 15m windows -> Promoted!
    print("Generating persona 2/5: bob (Candidate promotion across days 10-15)...")
    for day in range(15):
        day_base = start_sec + (day * day_sec)
        day_start = day_base + (9 * 3600)
        day_end = day_base + (17 * 3600)
        if day_end > now_sec:
            day_end = now_sec
        if day_start >= day_end:
            continue

        reqs_today = random.randint(350, 450)
        for _ in range(reqs_today):
            t = random.uniform(day_start, day_end)
            # Days 10-15: 30% of requests go to billing-service
            if day >= 10 and random.random() < 0.30:
                service = "billing-service"
                op_name, method = "BillingService/getInvoice", "GET"
                lat = max(5.0, random.gauss(20.0, 4.0))
                caller = "frontend-gateway"
            else:
                service = random.choice(["order-service", "user-service"])
                op_info = random.choice(SERVICES[service])
                op_name, method, base_lat, lat_std = op_info
                lat = max(2.0, random.gauss(base_lat, lat_std))
                caller = "mobile-app"
            status = 200 if random.random() > 0.008 else 400
            ip = "203.0.113.45"
            records.append(build_apm_doc(t, "bob", service, op_name, method, caller, ip, lat, status))

    # -------------------------------------------------------------------------
    # 3. MALLORY: Traffic Surge & Blast Radius
    # -------------------------------------------------------------------------
    # Days 1 to 14: Low background traffic (100 reqs/day)
    # Day 15 (last 2 hours): 2,000 rapid requests to payment-service with 5xx errors & high latency
    print("Generating persona 3/5: mallory (Traffic surge & blast radius)...")
    for day in range(14):
        day_base = start_sec + (day * day_sec)
        for _ in range(80):
            t = random.uniform(day_base + 3600, day_base + (20 * 3600))
            lat = max(10.0, random.gauss(25.0, 5.0))
            records.append(build_apm_doc(t, "mallory", "order-service", "OrderService/getOrder", "GET", "web-portal", "45.134.22.10", lat, 200))

    # Day 15 Surge: in the last 2 hours
    surge_start = now_sec - (2 * 3600)
    for _ in range(2200):
        t = random.uniform(surge_start, now_sec)
        # 85% payment surge, 15% order caller
        if random.random() < 0.85:
            service = "payment-service"
            op_name, method = "PaymentService/chargeCard", "POST"
            caller = "order-service"
            lat = max(50.0, random.gauss(380.0, 80.0))  # Latency blowout
            status = random.choice([200, 200, 200, 500, 502, 503]) if random.random() < 0.25 else 200
        else:
            service = "order-service"
            op_name, method = "OrderService/createOrder", "POST"
            caller = "frontend-gateway"
            lat = max(30.0, random.gauss(150.0, 30.0))
            status = 200
        records.append(build_apm_doc(t, "mallory", service, op_name, method, caller, "45.134.22.10", lat, status))

    # -------------------------------------------------------------------------
    # 4. OSCAR: Auth Attack (Failure Burst then Success)
    # -------------------------------------------------------------------------
    # Days 1 to 14: Sporadic login activity (40 reqs/day)
    # Day 15 (last 45 minutes): 150 failed 401 logins then 1 successful login from foreign IP
    print("Generating persona 4/5: oscar (Auth failure burst then success)...")
    for day in range(14):
        day_base = start_sec + (day * day_sec)
        for _ in range(35):
            t = random.uniform(day_base + (8 * 3600), day_base + (18 * 3600))
            lat = max(10.0, random.gauss(30.0, 6.0))
            records.append(build_apm_doc(t, "oscar", "auth-service", "AuthService/verifyToken", "POST", "frontend-gateway", "198.51.100.12", lat, 200))

    # Day 15 Auth attack: in the last 45 minutes
    attack_start = now_sec - (45 * 60)
    for _ in range(140):
        t = random.uniform(attack_start, now_sec - 120)
        lat = max(5.0, random.gauss(25.0, 5.0))
        # 401 Unauthorized attempts
        records.append(build_apm_doc(t, "oscar", "auth-service", "AuthService/login", "POST", "frontend-gateway", "185.220.101.5", lat, 401))

    # Followed by 2 successful logins at the very end
    records.append(build_apm_doc(now_sec - 90, "oscar", "auth-service", "AuthService/login", "POST", "frontend-gateway", "185.220.101.5", 35.0, 200))
    records.append(build_apm_doc(now_sec - 30, "oscar", "user-service", "UserService/getProfile", "GET", "frontend-gateway", "185.220.101.5", 20.0, 200))

    # -------------------------------------------------------------------------
    # 5. JUDY: Off-Hours Rogue Access to New Targets
    # -------------------------------------------------------------------------
    # Days 1 to 13: Normal daytime user (150 reqs/day) on user-service & notification-service
    # Days 14 to 15: Off-hours access (02:00 - 04:30 UTC) to billing-service from new IP
    print("Generating persona 5/5: judy (Off-hours access to novel billing target)...")
    for day in range(13):
        day_base = start_sec + (day * day_sec)
        for _ in range(120):
            t = random.uniform(day_base + (9 * 3600), day_base + (17 * 3600))
            service = random.choice(["user-service", "notification-service"])
            op_info = random.choice(SERVICES[service])
            op_name, method, base_lat, lat_std = op_info
            lat = max(5.0, random.gauss(base_lat, lat_std))
            records.append(build_apm_doc(t, "judy", service, op_name, method, "frontend-gateway", "192.168.1.88", lat, 200))

    # Days 14 & 15: Normal daytime + anomalous off-hours access
    for day in [13, 14]:
        day_base = start_sec + (day * day_sec)
        # Normal daytime
        for _ in range(80):
            t = random.uniform(day_base + (10 * 3600), min(now_sec, day_base + (16 * 3600)))
            records.append(build_apm_doc(t, "judy", "user-service", "UserService/getProfile", "GET", "frontend-gateway", "192.168.1.88", 22.0, 200))
        # Off-hours rogue access: 02:30 to 04:00 UTC from rogue IP
        off_start = day_base + int(2.5 * 3600)
        off_end = day_base + (4 * 3600)
        if off_end <= now_sec:
            for _ in range(60):
                t = random.uniform(off_start, off_end)
                records.append(build_apm_doc(t, "judy", "billing-service", "BillingService/generateInvoice", "POST", "frontend-gateway", "103.251.167.22", 65.0, 200))

    # Also add a few recent rogue off-hours calls in the last 2 hours if daytime currently
    for _ in range(30):
        t = random.uniform(now_sec - (2 * 3600), now_sec)
        records.append(build_apm_doc(t, "judy", "billing-service", "BillingService/generateInvoice", "POST", "frontend-gateway", "103.251.167.22", 70.0, 200))

    records.sort(key=lambda r: r["@timestamp"])
    print(f"Total records generated: {len(records)}")
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
            print(f"  Indexed {total_inserted}/{len(records)} records...")

    # Refresh index
    refresh_req = urllib.request.Request(f"{ES_URL}/{INDEX_NAME}/_refresh", method="POST")
    with urllib.request.urlopen(refresh_req, timeout=15) as resp:
        pass

    print(f"Successfully indexed and refreshed {total_inserted} records in Elasticsearch.")
    return total_inserted


if __name__ == "__main__":
    records = generate_15day_data()
    bulk_insert_es(records)

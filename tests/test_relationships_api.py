from __future__ import annotations

import time

from fastapi.testclient import TestClient

from backend.main import app
from backend.repository import StorageRepository
from backend.app.repositories.db_context import get_connection

SVC = "rel-test-orders"
SVC2 = "rel-test-billing"
COLUMNS = ["bucket_start", "principal", "source_ip", "service", "api", "caller_service", "request_count",
           "error_count", "p95_latency_ms", "request_bytes", "response_bytes", "first_seen_ms", "last_seen_ms",
           "is_load_balancer", "source_ip_role", "role_label", "updated_at_ms"]


def _seed(tmp_path):
    StorageRepository(tmp_path / "rel.db").migrate()
    now = int(time.time()) // 300 * 300
    cur, prev = now - 600, now - 3600 - 600  # inside the last hour / inside the hour before it

    def row(bucket, principal, ip, api, caller, requests, errors=0, lb=0, service=SVC):
        ms = bucket * 1000
        return [bucket, principal, ip, service, api, caller, requests, errors, 12.5, requests * 100, requests * 50,
                ms, ms + 1000, lb, "load_balancer" if lb else "client", "LB" if lb else "Client", ms]

    rows = [
        row(cur, "alice", "10.0.0.1", f"{SVC}/POST /checkout", "web", 10, 1),
        row(cur, "alice", "10.0.0.1", "POST /checkout", "mobile", 5),          # bare spelling, same API
        row(cur, "bob", "10.0.0.1", f"{SVC}/GET /status", "web", 4),
        row(cur, "-anonymous-", "10.0.0.9", f"{SVC}/POST /checkout", "web", 7),
        row(cur, "", "10.0.0.8", f"{SVC}/POST /checkout", "web", 3),          # empty principal is unknown too
        row(cur, "carol", "10.0.0.5", f"{SVC}/POST /checkout", "web", 2, lb=1),
        row(prev, "dave", "10.0.0.3", f"{SVC}/POST /checkout", "web", 6),     # only in the previous window
        row(cur, "alice", "10.0.0.1", f"{SVC2}/GET /invoice", "web", 4, service=SVC2),
    ]
    with get_connection() as db:
        db.execute(f"ALTER TABLE topology_principal_ip_5m DELETE WHERE service IN ('{SVC}', '{SVC2}') SETTINGS mutations_sync = 1")
        db.execute(f"ALTER TABLE services DELETE WHERE name IN ('{SVC}', '{SVC2}') SETTINGS mutations_sync = 1")
        db.client.insert("services", [[SVC, "production", "Orders", "Checkout", 1, 2], [SVC2, "production", "Billing", "Invoices", 1, 2]],
                         column_names=["name", "environment", "service_group", "service_module", "first_seen_ms", "last_seen_ms"])
        db.client.insert("topology_principal_ip_5m", rows, column_names=COLUMNS)
    return now


def _get(client, now, **params):
    params.setdefault("from", (now - 3600) * 1000)
    params.setdefault("to", now * 1000)
    response = client.get("/api/v1/relationships", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_api_scope_merges_spellings_and_separates_unknown_users(tmp_path):
    now = _seed(tmp_path)
    client = TestClient(app)
    body = _get(client, now, service=SVC, api="POST /checkout", facets="principal,caller,ip,unknown_ip")
    summary = body["summary"]
    assert summary["requests"] == 10 + 5 + 7 + 3 + 2
    assert summary["unknown_requests"] == 10 and summary["unknown_ips"] == 2
    users = {row["name"]: row for row in body["facets"]["principal"]["items"]}
    assert users["alice"]["requests"] == 15 and users["alice"]["callers"] == 2
    assert "-anonymous-" not in users and "" not in users
    assert users["dave"]["state"] == "silent" and users["dave"]["prev_requests"] == 6
    unknown = {row["name"]: row["requests"] for row in body["facets"]["unknown_ip"]["items"]}
    assert unknown == {"10.0.0.9": 7, "10.0.0.8": 3}
    lb = [row for row in body["facets"]["ip"]["items"] if row["name"] == "10.0.0.5"][0]
    assert lb["is_load_balancer"] is True
    assert len(body["series"]) == 1 and body["series"][0]["requests"] == 27


def test_selection_narrows_other_facets_but_keeps_siblings(tmp_path):
    now = _seed(tmp_path)
    client = TestClient(app)
    body = _get(client, now, service=SVC, sel_caller="mobile", facets="caller,principal,api")
    assert {row["name"] for row in body["facets"]["caller"]["items"] if row["requests"]} == {"web", "mobile"}
    assert [row["name"] for row in body["facets"]["principal"]["items"] if row["requests"]] == ["alice"]
    assert body["summary"]["requests"] == 5


def test_user_scope_lists_apis_by_service_and_shared_ips(tmp_path):
    now = _seed(tmp_path)
    client = TestClient(app)
    body = _get(client, now, principal="alice", facets="api,service,shared")
    apis = {(row["service"], row["name"]): row["requests"] for row in body["facets"]["api"]["items"]}
    assert apis == {(SVC, "POST /checkout"): 15, (SVC2, "GET /invoice"): 4}
    shared = {row["name"]: row["shared_ips"] for row in body["facets"]["shared"]["items"]}
    assert shared.get("bob") == 1


def test_rejects_api_without_service_and_unknown_facets():
    client = TestClient(app)
    assert client.get("/api/v1/relationships", params={"api": "GET /x"}).status_code == 422
    assert client.get("/api/v1/relationships", params={"facets": "nope"}).status_code == 422


def test_multi_select_and_catalog_group_filter(tmp_path):
    now = _seed(tmp_path)
    client = TestClient(app)
    both = _get(client, now, principal="alice", sel_service=[SVC, SVC2], facets="service,api")
    assert both["summary"]["requests"] == 19
    assert {row["name"] for row in both["facets"]["service"]["items"]} == {SVC, SVC2}  # own facet keeps siblings
    billing = _get(client, now, principal="alice", sel_group="Billing", facets="service,api")
    assert billing["summary"]["requests"] == 4
    assert [row["name"] for row in billing["facets"]["service"]["items"]] == [SVC2]
    assert billing["facets"]["service"]["items"][0]["group"] == "Billing"
    groups = {option["value"]: option["services"] for option in billing["service_meta_options"]["group"]}
    assert groups == {"Orders": 1, "Billing": 1}
    modules = [option["value"] for option in billing["service_meta_options"]["module"]]
    assert modules == ["Invoices"]  # modules are counted inside the selected group





def test_links_origin_to_user_for_one_api(tmp_path):
    now = _seed(tmp_path)
    bucket = now - 600
    ms = bucket * 1000
    with get_connection() as db:  # a request with no caller service: its origin is the source IP
        db.client.insert("topology_principal_ip_5m", [[bucket, "erin", "10.0.0.7", SVC, f"{SVC}/POST /checkout", "", 8, 0, 1.0,
                                                       0, 0, ms, ms + 1000, 0, "client", "Client", ms]], column_names=COLUMNS)
    client = TestClient(app)
    params = {"left": "origin", "right": "principal", "service": SVC, "api": "POST /checkout",
              "from": (now - 3600) * 1000, "to": now * 1000}
    body = client.get("/api/v1/relationships/links", params=params).json()
    links = {(l["left_kind"], l["left"], l["right_kind"], l["right"]): l for l in body["links"]}
    assert links[("service", "web", "user", "alice")]["requests"] == 10
    assert links[("service", "mobile", "user", "alice")]["requests"] == 5
    assert links[("service", "web", "unknown", "-anonymous-")]["requests"] == 10  # '' and -anonymous- merge
    assert links[("ip", "10.0.0.7", "user", "erin")]["role"] == "client"
    assert links[("service", "web", "user", "dave")]["state"] == "silent"
    assert sum(l["requests"] for l in body["links"]) == 27 + 8
    scoped = client.get("/api/v1/relationships/links", params={**params, "sel_principal": "alice"}).json()
    assert {l["right"] for l in scoped["links"]} == {"alice"}
    ip_api = client.get("/api/v1/relationships/links", params={"left": "ip", "right": "api", "principal": "alice",
                                                               "from": params["from"], "to": params["to"]}).json()
    pairs = {(l["left"], l["right_service"], l["right"]): l["requests"] for l in ip_api["links"]}
    assert pairs == {("10.0.0.1", SVC, "POST /checkout"): 15, ("10.0.0.1", SVC2, "GET /invoice"): 4}
    assert client.get("/api/v1/relationships/links", params={**params, "right": "origin"}).status_code == 422
    assert client.get("/api/v1/relationships/links", params={"left": "origin", "right": "principal", "api": "x"}).status_code == 422

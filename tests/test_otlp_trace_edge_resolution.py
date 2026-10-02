"""Direct OTLP -> ClickHouse pipeline: bytes, canonical API names, and caller resolution."""
from __future__ import annotations

import time

import pytest

from backend.app.repositories.aggregate_repository import AggregateRepository  # noqa: F401
from backend.app.repositories.db_context import get_connection
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.services import trace_edge_resolution as ter
from backend.app.services.aggregation import aggregate_traces
from backend.app.services.ingest_writer import IngestWriter
from backend.app.services.otlp_parser import _peer_service_name, otlp_span_to_normalized_trace
from backend.config import settings
from backend.repository import StorageRepository

# Recent and five-minute aligned: trace_edge_resolutions has a 2-day TTL, so old
# timestamps would let ClickHouse merge the rows away mid-test.
BASE_MS = (int(time.time() * 1000) // 300_000) * 300_000 - 2 * 3_600_000
WINDOW = (BASE_MS, BASE_MS + 300_000)
SERVER, CLIENT = 2, 3


def span(trace, span_id, service, kind, start_ms, dur_ms, name="POST /api/v1/orders/process",
         parent="", attrs=None):
    return {
        "trace_id": trace, "span_id": span_id, "parent_span_id": parent, "kind": kind, "name": name,
        "resource_attributes": {"service.name": service},
        "attributes": dict(attrs or {}),
        "start_time_unix_nano": (BASE_MS + start_ms) * 1_000_000,
        "end_time_unix_nano": (BASE_MS + start_ms + dur_ms) * 1_000_000,
    }


def client_attrs(host, path="/api/v1/orders/process"):
    return {"http.request.method": "POST", "server.address": host, "url.path": path}


def server_attrs(user="alice_wsse", path="/api/v1/orders/process"):
    return {
        "http.request.method": "POST", "url.path": path, "http.response.status_code": 200,
        "http.request.body.size": 755, "http.response.body.size": 357, "enduser.id": user,
        "network.peer.address": "10.244.0.77", "client.address": "10.244.0.77",  # the collector derives the latter
    }


def trace_spans(n, with_client=True):
    """traffic-ui -> order-service -> payment-service, OBI style (no parent links)."""
    out = []
    for i in range(n):
        t, off = f"{i + 1:032x}", i * 1000
        if with_client:
            out.append(span(t, f"c1{i:014x}", "traffic-ui", CLIENT, off, 100, attrs=client_attrs("order-service:8081")))
        out.append(span(t, f"s1{i:014x}", "order-service", SERVER, off + 10, 80, attrs=server_attrs()))
        out.append(span(t, f"c2{i:014x}", "order-service", CLIENT, off + 20, 50,
                        parent=f"s1{i:014x}", name="POST /api/v1/payments/process",
                        attrs=client_attrs("payment-service.default.svc.cluster.local", "/api/v1/payments/process")))
        out.append(span(t, f"s2{i:014x}", "payment-service", SERVER, off + 25, 40,
                        name="POST /api/v1/payments/process", attrs=server_attrs("bob_wsse", "/api/v1/payments/process")))
    return out


@pytest.fixture
def resolution_on():
    original = settings.trace_edge_resolution
    object.__setattr__(settings, "trace_edge_resolution", "true")
    yield
    object.__setattr__(settings, "trace_edge_resolution", original)


@pytest.fixture
def repo(tmp_path):
    db_path = tmp_path / "otlp_edges.db"
    StorageRepository(db_path).migrate()
    # Never truncate anything but a throwaway database (tests/conftest.py sets one).
    assert settings.clickhouse_database.startswith("test_"), settings.clickhouse_database
    with get_connection(db_path) as db:
        db.execute("TRUNCATE TABLE traces")
        db.execute("TRUNCATE TABLE metric_buckets")
        db.execute("TRUNCATE TABLE trace_edge_resolutions")
    return db_path


def insert(db_path, spans):
    traces = [otlp_span_to_normalized_trace(s) for s in spans]
    TraceRepository(db_path).insert_traces([t for t in traces if t])


def buckets(db_path, size=60):
    with get_connection(db_path) as db:
        rows = db.execute(
            "SELECT caller_service, target_service, principal_name, operation, "
            "sum(request_count), sum(request_bytes), sum(response_bytes) FROM metric_buckets FINAL "
            "WHERE bucket_size=? GROUP BY 1,2,3,4 ORDER BY 1,2", (size,),
        ).fetchall()
    return [tuple(r) for r in rows]


# --------------------------------------------------------------------------- normalizer

def test_server_span_gets_bytes_and_canonical_operation():
    trace = otlp_span_to_normalized_trace(span("a" * 32, "b" * 16, "order-service", SERVER, 0, 50,
                                               name="POST /api/v1/orders/42", attrs=server_attrs(path="/api/v1/orders/42")))
    assert trace.operation == "POST /api/v1/orders/{id}"
    assert (trace.request_bytes, trace.response_bytes) == (755, 357)


def test_unmeasured_bytes_stay_null_not_zero():
    attrs = server_attrs()
    del attrs["http.request.body.size"], attrs["http.response.body.size"]
    trace = otlp_span_to_normalized_trace(span("a" * 32, "b" * 16, "order-service", SERVER, 0, 50, attrs=attrs))
    assert trace.request_bytes is None and trace.response_bytes is None


@pytest.mark.parametrize("host,expected", [
    ("payment-service:8082", "payment-service"),
    ("payment-service.default.svc.cluster.local", "payment-service"),
    ("payment-service.default.svc", "payment-service"),
    ("http://order-service:8081/x", "order-service"),
    ("api.example.com", "api.example.com"),
    ("10.0.0.5", "10.0.0.5"),
    ("", None),
])
def test_client_peer_comes_from_destination_address(host, expected):
    assert _peer_service_name(host) == expected


def test_client_span_targets_the_called_service():
    trace = otlp_span_to_normalized_trace(span("a" * 32, "c" * 16, "traffic-ui", CLIENT, 0, 50, attrs=client_attrs("order-service:8081")))
    assert (trace.caller_service, trace.target_service) == ("traffic-ui", "order-service")
    assert trace.caller_resolution_method == "client_span"


def test_client_span_without_destination_keeps_unknown_marker():
    trace = otlp_span_to_normalized_trace(span("a" * 32, "c" * 16, "traffic-ui", CLIENT, 0, 50, attrs={"http.request.method": "GET"}))
    assert trace.target_service == "unknown-downstream"


# --------------------------------------------------------------------------- resolver (pure)

def rows_for(spans):
    out = []
    for s in spans:
        t = otlp_span_to_normalized_trace(s)
        out.append({
            "trace_id": t.trace_id, "span_id": t.span_id, "parent_span_id": t.parent_span_id,
            "service_name": t.service_name, "span_kind": t.span_kind, "target_service": t.target_service,
            "caller_service": t.caller_service, "timestamp_ms": t.timestamp_ms, "duration_us": t.duration_us,
            "observed_ip": t.observed_ip, "caller_ip": t.caller_ip,
        })
    return out


def by_span(result):
    return {row[1]: row for row in result.rows}


def test_server_takes_caller_from_matching_client_span_and_client_is_dropped():
    spans = trace_spans(1)
    rows = by_span(ter.resolve_rows(rows_for(spans), *WINDOW, now_ms=1))
    s1, c1 = rows["s1" + "0" * 14], rows["c1" + "0" * 14]
    assert (s1[3], s1[4], s1[6]) == (1, "traffic-ui", "trace_peer_match")
    assert c1[8] == 1  # paired root client: the server span already counts the request
    assert rows["s2" + "0" * 14][4] == "order-service"
    assert rows["c2" + "0" * 14][8] == 1  # non-root client span is not a request


def test_unpaired_root_client_becomes_an_edge_to_the_external_host():
    spans = [span("a" * 32, "c" * 16, "osclient-web", CLIENT, 0, 50, attrs=client_attrs("db.supabase.co", "/rest/v1/x"))]
    row = by_span(ter.resolve_rows(rows_for(spans), *WINDOW, now_ms=1))["c" * 16]
    assert (row[3], row[4], row[5], row[6], row[8]) == (1, "osclient-web", "db.supabase.co", "client_retargeted", 0)


def test_root_client_without_destination_is_not_counted():
    spans = [span("a" * 32, "c" * 16, "traffic-ui", CLIENT, 0, 50, attrs={"http.request.method": "GET"})]
    assert by_span(ter.resolve_rows(rows_for(spans), *WINDOW, now_ms=1))["c" * 16][8] == 1


def test_explicit_caller_is_kept():
    attrs = server_attrs()
    attrs["peer.service"] = "gateway"
    rows = rows_for([span("a" * 32, "s" * 16, "order-service", SERVER, 0, 50, attrs=attrs)])
    row = by_span(ter.resolve_rows(rows, *WINDOW, now_ms=1))["s" * 16]
    assert (row[3], row[8]) == (0, 0)  # no override, not skipped


def test_time_correlated_pairing_across_traces():
    server = span("1" * 32, "s" * 16, "order-service", SERVER, 10, 80, attrs=server_attrs())
    client = span("2" * 32, "c" * 16, "traffic-ui", CLIENT, 0, 100, attrs=client_attrs("order-service:8081"))
    row = by_span(ter.resolve_rows(rows_for([server, client]), *WINDOW, now_ms=1))["s" * 16]
    assert (row[4], row[6]) == ("traffic-ui", "time_correlated")


def test_context_outside_the_slice_is_used_but_not_resolved():
    # The client started in the previous slice, the server falls in this one.
    client = span("1" * 32, "c" * 16, "traffic-ui", CLIENT, -1_000, 2_000, attrs=client_attrs("order-service:8081"))
    server = span("1" * 32, "s" * 16, "order-service", SERVER, 0, 500, attrs=server_attrs())
    out = by_span(ter.resolve_rows(rows_for([client, server]), *WINDOW, now_ms=1))
    assert set(out) == {"s" * 16}
    assert out["s" * 16][4] == "traffic-ui"


# --------------------------------------------------------------------------- end to end in ClickHouse

def test_high_throughput_writer_persists_bytes_and_ip_evidence(repo):
    """The production ingest path is IngestWriter, not TraceRepository."""
    writer = IngestWriter(db_path=repo, coalesce_ms=0, commit_timeout_seconds=10)
    try:
        traces = [otlp_span_to_normalized_trace(s) for s in trace_spans(1)]
        assert writer.submit(traces, batch_id="bytes-1", node="otlp").inserted == len(traces)
    finally:
        writer.shutdown()
    with get_connection(repo) as db:
        row = db.execute(
            "SELECT request_bytes, response_bytes, observed_ip, ip_resolution FROM traces "
            "WHERE service_name='order-service' AND span_kind='server'").fetchone()
    assert (row[0], row[1], row[2]) == (755, 357, "10.244.0.77")


def test_aggregation_counts_each_request_once_with_resolved_callers(repo, resolution_on):
    insert(repo, trace_spans(3))
    aggregate_traces(*WINDOW, db_path=repo)
    result = buckets(repo)
    assert {(r[0], r[1]) for r in result} == {("traffic-ui", "order-service"), ("order-service", "payment-service")}
    assert all(r[4] == 3 for r in result), result
    assert not any("unknown-downstream" in (r[0], r[1]) for r in result)
    ui = next(r for r in result if r[0] == "traffic-ui")
    assert ui[2:4] == ("alice_wsse", "POST /api/v1/orders/process")
    assert (ui[5], ui[6]) == (3 * 755, 3 * 357)


def test_topology_rollups_use_the_same_resolved_callers(repo, resolution_on):
    insert(repo, trace_spans(2))
    aggregate_traces(*WINDOW, db_path=repo)
    with get_connection(repo) as db:
        ips = db.execute(
            "SELECT caller_service, service, source_ip, sum(request_count) FROM topology_principal_ip_5m FINAL "
            "GROUP BY 1,2,3 ORDER BY 1,2").fetchall()
        edges = db.execute("SELECT caller_service, target_service, request_count FROM service_edges FINAL ORDER BY 1,2").fetchall()
    assert [(r[0], r[1], r[2], int(r[3])) for r in ips] == [
        ("order-service", "payment-service", "10.244.0.77", 2),
        ("traffic-ui", "order-service", "10.244.0.77", 2),
    ]
    assert [(r[0], r[1], int(r[2])) for r in edges] == [
        ("order-service", "payment-service", 2), ("traffic-ui", "order-service", 2),
    ]


def test_late_client_span_replaces_the_unresolved_buckets(repo, resolution_on):
    spans = trace_spans(2)
    insert(repo, [s for s in spans if not (s["kind"] == CLIENT and s["span_id"].startswith("c1"))])
    aggregate_traces(*WINDOW, db_path=repo)
    first = {(r[0], r[1]): r[4] for r in buckets(repo)}
    assert first[("", "order-service")] == 2  # caller unknown so far

    insert(repo, [s for s in spans if s["span_id"].startswith("c1")])
    aggregate_traces(*WINDOW, db_path=repo)
    second = {(r[0], r[1]): r[4] for r in buckets(repo)}
    assert second[("traffic-ui", "order-service")] == 2
    assert ("", "order-service") not in second, second


def test_resolution_off_keeps_the_raw_row_behaviour(repo):
    original = settings.trace_edge_resolution
    object.__setattr__(settings, "trace_edge_resolution", "false")
    try:
        assert ter.traces_source_sql() == "traces"
        insert(repo, trace_spans(1))
        aggregate_traces(*WINDOW, db_path=repo)
        assert sum(r[4] for r in buckets(repo)) == 4  # every stored span is a row
    finally:
        object.__setattr__(settings, "trace_edge_resolution", original)


def test_auto_mode_follows_the_pipeline_mode():
    original, mode = settings.trace_edge_resolution, settings.trace_pipeline_mode
    try:
        object.__setattr__(settings, "trace_edge_resolution", "auto")
        object.__setattr__(settings, "trace_pipeline_mode", "clickhouse")
        assert settings.trace_edge_resolution_enabled
        object.__setattr__(settings, "trace_pipeline_mode", "elk_to_clickhouse")
        assert not settings.trace_edge_resolution_enabled
    finally:
        object.__setattr__(settings, "trace_edge_resolution", original)
        object.__setattr__(settings, "trace_pipeline_mode", mode)


# --------------------------------------------------------------------------- outgoing calls mid-request

def test_outgoing_call_to_an_uninstrumented_service_becomes_an_edge():
    # order-service (serving traffic-ui) calls a database nobody instruments.
    t = "a" * 32
    spans = [
        span(t, "s" * 16, "order-service", SERVER, 0, 100, attrs=server_attrs()),
        span(t, "c" * 16, "order-service", CLIENT, 10, 30, parent="s" * 16, name="GET /stock",
             attrs={"http.request.method": "GET", "server.address": "inventory-db.data.svc.cluster.local",
                    "url.path": "/stock"}),
    ]
    row = by_span(ter.resolve_rows(rows_for(spans), *WINDOW, now_ms=1))["c" * 16]
    assert (row[3], row[4], row[5], row[6], row[8]) == (1, "order-service", "inventory-db", "client_exit", 0)
    assert row[7] == ter.CONFIDENCE["client_exit"]


def test_outgoing_call_paired_with_the_callee_is_not_counted_twice():
    rows = by_span(ter.resolve_rows(rows_for(trace_spans(1)), *WINDOW, now_ms=1))
    assert (rows["c2" + "0" * 14][6], rows["c2" + "0" * 14][8]) == ("client_skipped", 1)


def test_outgoing_call_to_itself_is_not_an_edge():
    t = "b" * 32
    spans = [
        span(t, "s" * 16, "order-service", SERVER, 0, 100, attrs=server_attrs()),
        span(t, "c" * 16, "order-service", CLIENT, 10, 30, parent="s" * 16,
             attrs=client_attrs("order-service:8081")),
    ]
    assert by_span(ter.resolve_rows(rows_for(spans), *WINDOW, now_ms=1))["c" * 16][8] == 1


def test_internal_span_is_never_an_edge():
    t = "d" * 32
    spans = [
        span(t, "s" * 16, "order-service", SERVER, 0, 100, attrs=server_attrs()),
        span(t, "i" * 16, "order-service", 1, 10, 30, parent="s" * 16, name="validate"),
    ]
    row = by_span(ter.resolve_rows(rows_for(spans), *WINDOW, now_ms=1))["i" * 16]
    assert (row[6], row[8]) == ("not_a_transaction", 1)


def test_elk_resolver_keeps_mid_request_clients_out_by_default():
    from backend.app.services.trace_edges import TraceDoc, resolve
    server = TraceDoc(doc_id="s", trace_id="t", kind="server", service="order-service", parent_id=None,
                      peer="", peer_host="", start_us=0, end_us=100_000, client_ip="", explicit_caller="",
                      root_client=False)
    client = TraceDoc(doc_id="c", trace_id="t", kind="client", service="order-service", parent_id="s",
                      peer="inventory-db", peer_host="inventory-db", start_us=10_000, end_us=40_000,
                      client_ip="", explicit_caller="", root_client=False)
    assert "c" not in resolve([server, client]).resolutions
    assert resolve([server, client], exit_clients=True).resolutions["c"].method == "client_exit"


def test_aggregation_adds_the_edge_to_the_uninstrumented_service(repo, resolution_on):
    t = "e" * 32
    insert(repo, [
        span(t, "s" * 16, "order-service", SERVER, 0, 100, attrs=server_attrs()),
        span(t, "c" * 16, "order-service", CLIENT, 10, 30, parent="s" * 16, name="GET /stock",
             attrs={"http.request.method": "GET", "server.address": "inventory-db:5432", "url.path": "/stock"}),
    ])
    aggregate_traces(*WINDOW, db_path=repo)
    edges = {(r[0], r[1]) for r in buckets(repo)}
    assert ("order-service", "inventory-db") in edges

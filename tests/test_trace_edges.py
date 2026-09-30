"""Trace-scoped caller resolution for service edges."""
from unittest.mock import MagicMock, patch

from backend.app.repositories.elasticsearch_metric_repository import ElasticsearchMetricRepository
from backend.app.services.trace_edges import doc_from_source, normalize_peer, parse_ip_map, resolve


def _txn(service, doc_id, start_us, dur_us, parent=None, trace="t1", peer=None, ip=None, caller=None):
    labels = {"server_address": service}
    if peer:
        labels = {"service_peer_name": peer, "server_address": f"{peer}:8080"}
    if ip:
        labels["net_sock_peer_addr"] = ip
    source = {
        "processor": {"event": "transaction"}, "trace": {"id": trace}, "service": {"name": service},
        "transaction": {"id": doc_id, "duration": {"us": dur_us}}, "timestamp": {"us": start_us},
        "labels": labels,
    }
    if parent:
        source["parent"] = {"id": parent}
    return doc_from_source(source, [caller] if caller else None)


def _exit(service, doc_id, start_us, dur_us, peer, parent=None, trace="t1"):
    source = {
        "processor": {"event": "span"}, "trace": {"id": trace}, "service": {"name": service},
        "span": {"id": doc_id, "duration": {"us": dur_us}, "type": "external"},
        "timestamp": {"us": start_us},
        "labels": {"service_peer_name": peer, "server_address": f"{peer}:8082"},
    }
    if parent:
        source["parent"] = {"id": parent}
    return doc_from_source(source)


def test_parent_id_join_for_sdk_agents():
    docs = [
        _txn("checkout", "a1", 0, 10_000),
        _exit("checkout", "s1", 1_000, 5_000, "payments", parent="a1"),
        _txn("payments", "b1", 2_000, 3_000, parent="s1"),
    ]
    result = resolve(docs)
    assert (result.resolutions["b1"].caller, result.resolutions["b1"].method) == ("checkout", "trace_parent")
    assert result.stats["trace_parent"] == 1


def test_dangling_parent_ids_match_by_peer_and_time_with_clock_skew():
    """OBI propagates trace.id but exported parents do not exist (live data shape)."""
    docs = [
        # Root client-only doc: traffic-ui has no server span of its own.
        _txn("traffic-ui", "ui", 1_000_200, 6_841, peer="order-service"),
        # Callee starts 200us *before* the caller on another node's clock.
        _txn("order-service", "o1", 1_000_000, 6_867, parent="dangling"),
        _exit("order-service", "os", 1_002_300, 4_191, "payment-service", parent="dangling2"),
        _txn("payment-service", "p1", 1_002_400, 3_941, parent="dangling"),
        _exit("payment-service", "ps", 1_004_700, 1_167, "notification-service", parent="dangling3"),
        _txn("notification-service", "n1", 1_004_800, 917, parent="dangling"),
    ]
    result = resolve(docs)
    callers = {k: (r.caller, r.method) for k, r in result.resolutions.items() if not r.skip}
    assert callers == {
        "o1": ("traffic-ui", "trace_peer_match"),
        "p1": ("order-service", "trace_peer_match"),
        "n1": ("payment-service", "trace_peer_match"),
    }
    # The client-only root duplicates order-service's request and must not count.
    assert result.resolutions["ui"].skip
    assert result.skipped() == {"ui": True}


def test_peer_match_ignores_other_traces_and_non_containing_calls():
    docs = [
        _exit("checkout", "s1", 0, 1_000, "payments", trace="other"),
        _exit("checkout", "s2", 5_000_000, 1_000, "payments"),
        _txn("payments", "b1", 0, 800, parent="dangling"),
    ]
    assert "b1" not in resolve(docs, skew_us=250_000).resolutions


def test_uninstrumented_caller_uses_configured_ip_map():
    docs = [_txn("payments", "b1", 0, 1_000, ip="10.9.0.7")]
    result = resolve(docs, ip_map=parse_ip_map("10.9.0.0/24=legacy-billing, 10.9.0.7=cron-job"))
    assert (result.resolutions["b1"].caller, result.resolutions["b1"].method) == ("cron-job", "network_ip")


def test_uninstrumented_request_uses_ip_learned_from_resolved_edges():
    docs = [
        _exit("checkout", "s1", 0, 5_000, "payments", trace="t1"),
        _txn("payments", "b1", 1_000, 1_000, parent="x", trace="t1", ip="10.244.1.5"),
        # Same pod, but this request lost its trace context (new root trace).
        _txn("payments", "b2", 9_000, 1_000, trace="t2", ip="10.244.1.5"),
        # Unknown IP stays without a caller rather than inventing one.
        _txn("payments", "b3", 9_000, 1_000, trace="t3", ip="10.244.9.9"),
    ]
    result = resolve(docs)
    assert (result.resolutions["b2"].caller, result.resolutions["b2"].method) == ("checkout", "network_ip")
    assert "b3" not in result.resolutions


def test_ambiguous_learned_ip_is_not_attributed():
    docs = [
        _exit("checkout", "s1", 0, 5_000, "payments", trace="t1"),
        _txn("payments", "b1", 1_000, 1_000, trace="t1", ip="10.0.0.9"),
        _exit("search", "s2", 0, 5_000, "payments", trace="t2"),
        _txn("payments", "b2", 1_000, 1_000, trace="t2", ip="10.0.0.9"),
        _txn("payments", "b3", 9_000, 1_000, trace="t3", ip="10.0.0.9"),
    ]
    assert "b3" not in resolve(docs).resolutions


def test_explicit_caller_is_kept_before_ip_inference():
    docs = [_txn("payments", "b1", 0, 1_000, ip="10.9.0.7", caller="gateway")]
    result = resolve(docs, ip_map=parse_ip_map("10.9.0.7=cron-job"))
    assert "b1" not in result.resolutions
    assert result.stats["explicit"] == 1


def test_uninstrumented_intermediary_is_the_direct_caller():
    """checkout -> nginx (no agent, forwards traceparent) -> payments."""
    docs = [
        _txn("checkout", "a1", 0, 10_000),
        _exit("checkout", "s1", 1_000, 5_000, "nginx", parent="a1"),
        _txn("payments", "b1", 2_000, 3_000, parent="s1"),
    ]
    resolution = resolve(docs).resolutions["b1"]
    assert (resolution.caller, resolution.method) == ("nginx", "trace_intermediary")


def test_client_root_into_uninstrumented_callee_is_retargeted():
    docs = [_txn("traffic-ui", "ui", 0, 1_000, peer="legacy-core")]
    result = resolve(docs)
    assert result.targets() == {"ui": "legacy-core"}
    assert result.target_callers() == {"ui": "traffic-ui"}


def test_targets_limit_resolution_to_slice_documents():
    docs = [
        _exit("checkout", "s1", 0, 5_000, "payments"),
        _txn("payments", "b1", 1_000, 1_000, parent="x"),
    ]
    assert resolve(docs, targets=[]).resolutions == {}


def test_normalize_peer():
    assert normalize_peer("payment-service:8082") == "payment-service"
    assert normalize_peer("http://Payment-Service.default.svc.cluster.local:80/x") == "payment-service"
    assert normalize_peer("10.1.2.3:8080") == "10.1.2.3"


def _response(payload):
    result = MagicMock()
    result.status_code = 200
    result.json.return_value = payload
    return result


def test_metric_window_applies_trace_resolution_to_runtime_fields():
    hits = [{"_source": s} for s in (
        {"processor": {"event": "transaction"}, "trace": {"id": "t"}, "service": {"name": "traffic-ui"},
         "transaction": {"id": "ui", "duration": {"us": 7000}}, "timestamp": {"us": 360_000_000},
         "labels": {"service_peer_name": "order-service", "server_address": "order-service:8081"}},
        {"processor": {"event": "transaction"}, "trace": {"id": "t"}, "service": {"name": "order-service"},
         "parent": {"id": "missing"}, "transaction": {"id": "o1", "duration": {"us": 6000}},
         "timestamp": {"us": 360_000_500}, "labels": {"server_address": "order-service"}},
    )]
    repo = ElasticsearchMetricRepository("test_metrics")
    repo.url = "http://elk.test:9200"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = [
        _response({"hits": {"total": {"value": 2}, "hits": hits}}),
        _response({"aggregations": {"buckets": {"buckets": []}}}),
    ]
    with patch.object(repo, "_client", return_value=client), \
         patch("backend.app.repositories.elasticsearch_metric_repository.AggregateRepository.save_buckets"):
        result = repo.materialize_window(300_000, 600_000, 300)
    assert result["complete"] and result["edge_resolution"]["trace_peer_match"] == 1
    fetch = client.post.call_args_list[0].kwargs["json"]
    assert fetch["query"]["bool"]["filter"][0]["range"]["@timestamp"] == {"gte": 240_000, "lt": 660_000}
    body = client.post.call_args_list[1].kwargs["json"]
    caller = body["runtime_mappings"]["topology.caller"]["script"]
    assert caller["params"] == {"callers": {"o1": "traffic-ui"}}
    assert body["runtime_mappings"]["topology.trace_skip"]["script"]["params"] == {"skip": {"ui": True}}
    assert body["query"]["bool"]["must_not"] == [{"term": {"topology.trace_skip": True}}]


def test_windows_are_sliced_and_resumable():
    repo = ElasticsearchMetricRepository("test_metrics")
    slices = list(repo._slices(0, 3_600_000, None))
    assert [(s, e) for s, e, _ in slices] == [(0, 900_000), (900_000, 1_800_000), (1_800_000, 2_700_000), (2_700_000, 3_600_000)]
    resumed = list(repo._slices(0, 3_600_000, {"slice_start_ms": 1_800_000, "after": {"k": 1}}))
    assert resumed[0] == (1_800_000, 2_700_000, {"k": 1}) and resumed[1][2] is None
    # Unaligned starts snap the first slice end to a five-minute boundary.
    assert list(repo._slices(100_000, 1_000_000, None))[0][:2] == (100_000, 900_000)
    # Legacy composite after keys restart the window.
    assert list(repo._slices(0, 600_000, {"bucket_start_ms": 1}))[0] == (0, 600_000, None)


def test_caller_without_trace_context_pairs_across_traces_and_is_not_double_counted():
    """legacy-service propagates no traceparent, so order-service starts a new trace."""
    docs = [
        _txn("legacy-service", "lg", 1_000_000, 5_000, peer="order-service", trace="t-legacy"),
        _txn("order-service", "o1", 1_000_900, 3_000, trace="t-order"),
    ]
    result = resolve(docs)
    assert (result.resolutions["o1"].caller, result.resolutions["o1"].method) == ("legacy-service", "time_correlated")
    assert result.resolutions["lg"].skip


def test_learned_ip_is_preferred_over_time_correlation():
    docs = [
        _exit("checkout", "s1", 0, 5_000, "payments", trace="t1"),
        _txn("payments", "b1", 1_000, 1_000, trace="t1", ip="10.244.1.5"),
        _txn("batch", "bt", 8_000, 5_000, peer="payments", trace="t9"),
        _txn("payments", "b2", 9_000, 1_000, trace="t2", ip="10.244.1.5"),
    ]
    result = resolve(docs)
    assert result.resolutions["b2"].method == "network_ip"
    assert result.resolutions["b2"].caller == "checkout"
    assert result.resolutions["bt"].target == "payments"


def test_external_peer_keeps_full_host():
    docs = [_txn("osclient-web", "c1", 0, 1_000, peer="upmelrrwltcbgwjxpiga.supabase.co")]
    assert resolve(docs).targets() == {"c1": "upmelrrwltcbgwjxpiga.supabase.co"}


def test_recent_slices_are_cleared_before_rewrite_and_old_slices_are_not():
    import time as _time
    repo = ElasticsearchMetricRepository("test_metrics")
    db = MagicMock()
    conn = MagicMock(__enter__=MagicMock(return_value=db))
    now = int(_time.time() * 1000)
    with patch("backend.app.repositories.elasticsearch_metric_repository.get_connection", return_value=conn):
        repo._clear("metric_buckets", now - 900_000, now, 300)
        repo._clear("metric_buckets", 0, 900_000, 300)
    assert db.client.command.call_count == 1
    sql = db.client.command.call_args.args[0]
    assert sql.startswith("DELETE FROM metric_buckets WHERE") and "bucket_size" in sql
    assert db.client.command.call_args.kwargs["parameters"]["size"] == 300

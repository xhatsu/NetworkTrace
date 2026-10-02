"""Root OBI transactions must not reverse outbound service relationships."""
from copy import deepcopy

from backend.app.services.normalization import normalize_otel_record


ROOT = {
    "@timestamp": "2026-09-30T10:00:00Z",
    "processor": {"event": "transaction"},
    "service": {"name": "traffic-ui"},
    "trace": {"id": "root-trace"},
    "transaction": {"id": "root-span", "name": "POST /api/v1/orders/process"},
    "parent": {"id": None},
    "labels": {
        "service_peer_name": "order-service",
        "server_address": "order-service:8081",
        "url_full": "http://order-service:8081/api/v1/orders/process",
    },
}


def test_obi_root_transaction_is_outbound():
    trace = normalize_otel_record(deepcopy(ROOT))
    assert trace.span_kind == "client"
    assert trace.caller_service == "traffic-ui"
    assert trace.target_service == "order-service"
    assert trace.caller_resolution_method == "root_client_inferred"
    assert trace.caller_confidence < 1


def test_explicit_server_is_never_reclassified():
    doc = deepcopy(ROOT)
    doc["span_kind"] = "server"
    trace = normalize_otel_record(doc)
    assert trace.span_kind == "server"
    assert trace.target_service == "traffic-ui"


def test_parented_transaction_keeps_server_direction():
    doc = deepcopy(ROOT)
    doc["parent"]["id"] = "upstream"
    assert normalize_otel_record(doc).span_kind == "server"


def test_caller_metadata_is_not_outbound_evidence():
    doc = deepcopy(ROOT)
    del doc["labels"]["service_peer_name"]
    doc["labels"]["caller_service"] = "gateway"
    doc["labels"]["server_address"] = "gateway:8081"
    trace = normalize_otel_record(doc)
    assert trace.span_kind == "server"
    assert trace.caller_service == "gateway"
    assert trace.target_service == "traffic-ui"


def test_peer_without_matching_destination_is_not_reclassified():
    doc = deepcopy(ROOT)
    doc["labels"]["server_address"] = "traffic-ui:8080"
    doc["labels"]["url_full"] = "http://traffic-ui:8080/api"
    assert normalize_otel_record(doc).span_kind == "server"


def test_url_alone_can_corroborate_destination():
    doc = deepcopy(ROOT)
    del doc["labels"]["server_address"]
    assert normalize_otel_record(doc).target_service == "order-service"

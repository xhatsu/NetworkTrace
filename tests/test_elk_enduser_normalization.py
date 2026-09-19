"""Tests for extracting enduser.id and related user semantics from Elasticsearch / ELK documents."""
import pytest
from backend.app.services.normalization import normalize_otel_record
from backend.app.services.apm_parser import apm_document_to_normalized_trace


def test_elk_enduser_id_top_level_in_source():
    doc = {
        "_id": "elk-hit-1",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "GET /api/checkout", "duration": {"us": 45000}},
            "service": {"name": "order-service", "environment": "production"},
            "processor": {"event": "transaction"},
            "enduser.id": "user_alice_01",
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "user_alice_01"
    assert trace.identity_source == "enduser_id"
    assert trace.principal_id == "production:user_alice_01"


def test_elk_enduser_id_nested_in_source():
    doc = {
        "_id": "elk-hit-2",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "POST /api/payment", "duration": {"us": 55000}},
            "service": {"name": "payment-service", "environment": "production"},
            "processor": {"event": "transaction"},
            "enduser": {"id": "user_bob_02"},
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "user_bob_02"
    assert trace.identity_source == "enduser_id"


def test_elk_enduser_id_in_labels():
    doc = {
        "_id": "elk-hit-3",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "GET /api/items", "duration": {"us": 12000}},
            "service": {"name": "catalog-service", "environment": "staging"},
            "processor": {"event": "transaction"},
            "labels": {
                "enduser.id": "user_charlie_03",
            },
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "user_charlie_03"
    assert trace.identity_source == "enduser_id"
    assert trace.principal_id == "staging:user_charlie_03"


def test_elk_enduser_id_in_labels_snake_case():
    doc = {
        "_id": "elk-hit-4",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "GET /api/profile", "duration": {"us": 8000}},
            "service": {"name": "user-service", "environment": "production"},
            "processor": {"event": "transaction"},
            "labels": {
                "enduser_id": "user_david_04",
            },
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "user_david_04"
    assert trace.identity_source == "enduser_id"


def test_elk_enduser_id_in_attributes_list():
    doc = {
        "_id": "elk-hit-5",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "GET /api/status", "duration": {"us": 3000}},
            "service": {"name": "status-service", "environment": "production"},
            "processor": {"event": "transaction"},
            "attributes": [
                {"key": "enduser.id", "value": {"stringValue": "user_eve_05"}}
            ],
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "user_eve_05"
    assert trace.identity_source == "enduser_id"


def test_elk_enduser_id_in_fields():
    doc = {
        "_id": "elk-hit-6",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "GET /api/feed", "duration": {"us": 15000}},
            "service": {"name": "feed-service", "environment": "production"},
            "processor": {"event": "transaction"},
        },
        "fields": {
            "enduser.id": ["user_frank_06"]
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "user_frank_06"
    assert trace.identity_source == "enduser_id"


def test_apm_parser_enduser_id_extraction():
    hit = {
        "_id": "apm-hit-1",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "11112222333344445555666677778888"},
            "transaction": {"id": "aaaabbbbccccdddd", "name": "POST /order", "duration": {"us": 100000}},
            "service": {"name": "checkout-svc", "environment": "production"},
            "processor": {"event": "transaction"},
            "labels": {
                "enduser.id": "user_grace_07"
            }
        }
    }
    trace = apm_document_to_normalized_trace(hit)
    assert trace is not None
    assert trace.principal_name == "user_grace_07"
    assert trace.identity_source == "enduser_id"
    assert trace.principal_id == "production:user_grace_07"


def test_elk_enduser_id_placeholder_falls_back():
    doc = {
        "_id": "elk-hit-7",
        "_source": {
            "@timestamp": "2026-09-17T08:00:00.000Z",
            "trace": {"id": "abcdef1234567890abcdef1234567890"},
            "transaction": {"id": "1234567890abcdef", "name": "GET /api/health", "duration": {"us": 1000}},
            "service": {"name": "health-service", "environment": "production"},
            "processor": {"event": "transaction"},
            "enduser.id": "-",
        }
    }
    trace = normalize_otel_record(doc)
    assert trace is not None
    assert trace.principal_name == "unknown"
    assert trace.identity_source == "anonymous"

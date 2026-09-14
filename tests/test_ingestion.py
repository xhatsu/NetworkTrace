from datetime import datetime, timezone

from backend.ingest import basic_username, import_documents, normalize
from backend.repository import StorageRepository
from backend.analytics import run_jobs


def repo(tmp_path):
    value=StorageRepository(tmp_path/"test.db");value.migrate();return value


def test_basic_credentials_are_sanitized_before_storage(tmp_path):
    raw={"_source":{"@timestamp":"2026-01-01T00:00:00Z","trace":{"id":"t"},"transaction":{"id":"x","name":"GET /","duration":{"us":1000}},"service":{"name":"api"},"http":{"request":{"method":"GET"}},"labels":{"http_request_header_authorization":"Basic dXNlcjpzdXBlci1zZWNyZXQ="}}}
    event=normalize(raw)
    assert event["account_username"]=="user"
    assert "authorization" not in " ".join(event.keys()).lower()
    assert "super-secret" not in repr(event)
    r=repo(tmp_path);import_documents(r,[raw])
    with r.connect() as db:
        stored=dict(db.execute("SELECT * FROM events").fetchone())
        ddl=" ".join(row[0] or "" for row in db.execute("SELECT sql FROM sqlite_master"))
    assert "super-secret" not in repr(stored)
    assert "authorization" not in ddl.lower()


def test_malformed_credentials_are_never_exposed():
    assert basic_username("Basic !!!") is None
    assert basic_username("Bearer secret") is None


def test_source_wins_and_duplicate_replay_is_idempotent(tmp_path):
    raw={"_id":"stable","_source":{"@timestamp":"2026-01-01T00:00:00Z","transaction":{"id":"x","name":"GET /","duration":{"us":100}},"service":{"name":"correct"}},"fields":{"service.name":["wrong"]}}
    r=repo(tmp_path);first=import_documents(r,[raw]);second=import_documents(r,[raw])
    assert first.inserted==1 and second.inserted==0 and second.duplicates==1
    with r.connect() as db: assert db.execute("SELECT service_name FROM events").fetchone()[0]=="correct"


def test_late_event_recomputes_affected_results_without_double_counting(tmp_path):
    r=repo(tmp_path);base={"@timestamp":"2026-01-01T00:05:00Z","transaction":{"name":"GET /","duration":{"us":1000}},"service":{"name":"late-api"},"http":{"request":{"method":"GET"}}}
    import_documents(r,[{"_id":"newer","_source":base}]);run_jobs(r)
    late={**base,"@timestamp":"2026-01-01T00:01:00Z","transaction":{**base["transaction"],"id":"late"}}
    import_documents(r,[{"_id":"late","_source":late},{"_id":"late","_source":late}]);run_jobs(r)
    with r.connect() as db:
        assert db.execute("SELECT SUM(http_count) FROM latency_rollups WHERE service_name='late-api' AND operation='' AND account_username=''").fetchone()[0]==2


def test_otlp_span_format_normalized_and_stored(tmp_path):
    raw = {
        "traceId": "trace123456",
        "spanId": "span789",
        "name": "POST /api/v1/cart/items",
        "kind": "SPAN_KIND_SERVER",
        "startTimeUnixNano": "1788473206091709952",
        "endTimeUnixNano": "1788473206106139952",
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "cart-service"}}]},
        "attributes": [
            {"key": "http.response.status_code", "value": {"intValue": 200}},
            {"key": "enduser.id", "value": {"stringValue": "user_42"}},
        ],
        "status": {"code": "STATUS_CODE_OK"}
    }
    event = normalize(raw)
    assert event["service_name"] == "cart-service"
    assert event["operation"] == "POST /api/v1/cart/items"
    assert event["trace_id"] == "trace123456"
    assert event["transaction_id"] == "span789"
    assert event["duration_us"] == 14430
    assert event["outcome"] == "success"
    assert event["status_code"] == 200
    assert event["account_username"] == "user_42"
    r = repo(tmp_path)
    res = import_documents(r, [raw])
    assert res.inserted == 1
    with r.connect() as db:
        row = dict(db.execute("SELECT * FROM events WHERE trace_id='trace123456'").fetchone())
        assert row["service_name"] == "cart-service"
        assert row["duration_us"] == 14430


def test_elk_apm_transaction_format_normalized_and_sanitized(tmp_path):
    doc = {
        "_index": "apm-bss-cluster:apm-7.15.2-transaction-2026.09.04-4",
        "_id": "apS1a6ABe_Fcqh4oxgIN",
        "_source": {
            "@timestamp": "2026-09-04T09:17:15.359Z",
            "event": {"ingested": "2026-09-04T09:17:49.958700477Z", "outcome": "success"},
            "trace": {"id": "5402b69a3ac1d41dd1096bb6f1837026"},
            "service": {"name": "VTN_CNTT_BSS_201_BCCS_Payment2_Webservice", "environment": "prod", "node": {"name": "bccs2-payment-process-02"}},
            "transaction": {"id": "40ecc6e90589f58b", "name": "/SALE_SERVICE/bpm/getQrCode", "duration": {"us": 681519}},
            "http": {"request": {"method": "POST"}, "response": {"status_code": 200}},
            "labels": {
                "service_group_id": "PayService",
                "service_module_id": "VTN_CNTT_BSS_201_002",
                "http_request_header_authorization": ["Basic dnRwOnBhc3N3b3Jk"],
                "net_sock_host_addr": "10.240.147.79",
                "net_sock_peer_addr": "10.240.147.249"
            }
        }
    }
    event = normalize(doc)
    assert event["event_uid"] == "apS1a6ABe_Fcqh4oxgIN"
    assert event["service_name"] == "VTN_CNTT_BSS_201_BCCS_Payment2_Webservice"
    assert event["service_group"] == "PayService"
    assert event["service_module"] == "VTN_CNTT_BSS_201_002"
    assert event["account_username"] == "vtp"
    assert "password" not in repr(event)
    assert event["duration_us"] == 681519
    assert event["ingested_ms"] == 1788513469958
    r = repo(tmp_path)
    res = import_documents(r, [doc])
    assert res.inserted == 1
    with r.connect() as db:
        row = dict(db.execute("SELECT * FROM events WHERE event_uid='apS1a6ABe_Fcqh4oxgIN'").fetchone())
        assert row["service_name"] == "VTN_CNTT_BSS_201_BCCS_Payment2_Webservice"
        assert row["account_username"] == "vtp"
        assert "password" not in repr(row)


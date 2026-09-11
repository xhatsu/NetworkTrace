import json
import time
from pathlib import Path
import pytest

from backend.app.models.trace import NormalizedTrace
from backend.app.repositories.db_context import get_connection, db_transaction
from backend.app.repositories.trace_repository import TraceRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.services.normalization import normalize_otel_record, normalize_operation_key
from backend.app.services.behavioral_engine import (
    evaluate_readiness,
    emit_behavioral_change,
    recalculate_incident_score,
    get_or_create_incident,
    detect_operation_mix_shift,
    detect_caller_principal_switch,
    detect_telemetry_quality_gates,
    detect_explicit_auth_anomalies,
    FAMILY_CAPS,
)
from backend.repository import SQLiteRepository


@pytest.fixture
def clean_db(tmp_path):
    db_file = tmp_path / "test_tracescope.db"
    repo = SQLiteRepository(db_file)
    repo.migrate()
    return str(db_file)


# Scenario 1: New principal during learning emits audit event; novelty alerts suppressed
def test_new_principal_during_learning_suppresses_novelty_alerts(clean_db):
    now = int(time.time() * 1000)
    with get_connection(clean_db) as db:
        # Principal has only 1 observation today
        db.execute("""
            INSERT INTO traces (
                event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                principal_name, principal_id, operation, duration_ms, duration_us, created_at
            ) VALUES ('e1', ?, ?, 't1', 's1', 'api', 'api', 'learner_user', 'production:learner_user', 'op', 10, 10000, ?)
        """, (now // 1000, now, now))

        ready, status = evaluate_readiness(db, "production:learner_user", "NEW_CALLER", now)
        assert not ready
        assert status == "insufficient_history"

        # Emitting USERNAME_FIRST_SEEN produces 0 security points (audit event)
        ev_id = emit_behavioral_change(
            db,
            principal_id="production:learner_user",
            change_type="USERNAME_FIRST_SEEN",
            detected_at=now,
            new_value="learner_user"
        )
        assert ev_id > 0

        # Incident score should be 0
        inc = db.execute("SELECT * FROM incidents WHERE principal_id = 'production:learner_user'").fetchone()
        assert inc["score"] == 0
        assert inc["priority"] == "low"


# Scenario 2: Same request exported twice results in one observation
def test_same_request_exported_twice_deduplicates_to_one(clean_db):
    trace_repo = TraceRepository(clean_db)
    raw = {
        "_source": {
            "@timestamp": "2026-09-01T12:00:00Z",
            "trace": {"id": "trace_dup_1"},
            "transaction": {"id": "span_dup_1", "name": "GET /test", "duration": {"us": 500}},
            "service": {"name": "test-svc", "environment": "production"}
        }
    }
    t1 = normalize_otel_record(raw)
    t2 = normalize_otel_record(raw)
    assert t1.dedup_key == t2.dedup_key == "production:trace_dup_1:span_dup_1"

    inserted1 = trace_repo.insert_traces([t1])
    assert inserted1 == 1

    # Second insert of identical span
    inserted2 = trace_repo.insert_traces([t2])
    assert inserted2 == 0

    with get_connection(clean_db) as db:
        count = db.execute("SELECT COUNT(*) FROM traces WHERE trace_id = 'trace_dup_1'").fetchone()[0]
        assert count == 1


# Scenario 3: Client and server spans: server span is counted request, client span gives caller attribution
def test_client_server_spans_handling(clean_db):
    raw_server = {
        "_source": {
            "@timestamp": "2026-09-01T12:00:00Z",
            "trace": {"id": "trace_cs_1"},
            "transaction": {"id": "span_server_1", "name": "POST /order", "duration": {"us": 500}},
            "service": {"name": "order-service"},
            "span": {"kind": "server"},
            "peer": {"service": {"name": "gateway-service"}}
        }
    }
    norm = normalize_otel_record(raw_server)
    assert norm.span_kind == "server"
    assert norm.service_name == "order-service"
    assert norm.caller_service == "gateway-service"
    assert norm.caller_resolution_method in {"header", "trace_parent"}
    assert norm.caller_confidence >= 0.8


# Scenario 4: One deployment introduces caller and IP creates one incident with capped contributions
def test_deployment_introducing_caller_and_ip_has_capped_scoring(clean_db):
    now = int(time.time() * 1000)
    pid = "production:deploy_bot"
    with db_transaction(clean_db) as db:
        # Emit multiple origin events
        emit_behavioral_change(db, principal_id=pid, change_type="NEW_CALLER", detected_at=now, new_value="caller_a")
        emit_behavioral_change(db, principal_id=pid, change_type="NEW_SOURCE_IP", detected_at=now, new_value="10.0.1.5")
        emit_behavioral_change(db, principal_id=pid, change_type="NEW_PRINCIPAL_ON_SOURCE", detected_at=now, new_value="10.0.1.5")
        emit_behavioral_change(db, principal_id=pid, change_type="SOURCE_FANOUT_SURGE", detected_at=now, new_value="fanout_3")

        inc = db.execute("SELECT * FROM incidents WHERE principal_id = ?", (pid,)).fetchone()
        assert inc is not None
        # Raw points would be 30 + 10 + 15 + 25 = 80 pts.
        # But Origin family cap is 35!
        family_scores = json.loads(inc["family_scores_json"])
        assert family_scores["origin"] == FAMILY_CAPS["origin"] == 35
        assert inc["score"] == 35
        assert inc["priority"] == "medium"


# Scenario 5: Familiar operations change from mostly read to mostly cancel emits operation mix event
def test_operation_mix_shift_detection(clean_db):
    now = int(time.time() * 1000)
    pid = "production:billing_app"
    svc = "billing-service"
    window_start = now - 900_000
    window_end = now

    with db_transaction(clean_db) as db:
        # Establish history: 20 days, 300 observations of readInvoice (98%) and cancelInvoice (2%)
        past_start = now - 20 * 86_400_000
        for i in range(294):
            ts = past_start + i * 3600_000
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                                    principal_name, principal_id, operation, operation_key, duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'billing_app', ?, 'readInvoice', 'billing-service/readInvoice', 10, 10000, ?)
            """, (f"h_{i}", ts // 1000, ts, f"t_{i}", f"s_{i}", svc, svc, pid, ts))
        for i in range(6):
            ts = past_start + i * 3600_000 + 100
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                                    principal_name, principal_id, operation, operation_key, duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'billing_app', ?, 'cancelInvoice', 'billing-service/cancelInvoice', 10, 10000, ?)
            """, (f"h_c_{i}", ts // 1000, ts, f"t_c_{i}", f"s_c_{i}", svc, svc, pid, ts))

        # Current window: 120 observations, 60 of which are cancelInvoice (50% vs historical 2% -> +48% shift)
        for i in range(60):
            ts = window_start + i * 1000
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                                    principal_name, principal_id, operation, operation_key, duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'billing_app', ?, 'readInvoice', 'billing-service/readInvoice', 10, 10000, ?)
            """, (f"w_r_{i}", ts // 1000, ts, f"t_w_r_{i}", f"s_w_r_{i}", svc, svc, pid, ts))
        for i in range(60):
            ts = window_start + i * 1000 + 500
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                                    principal_name, principal_id, operation, operation_key, duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'billing_app', ?, 'cancelInvoice', 'billing-service/cancelInvoice', 10, 10000, ?)
            """, (f"w_c_{i}", ts // 1000, ts, f"t_w_c_{i}", f"s_w_c_{i}", svc, svc, pid, ts))

        ev_id = detect_operation_mix_shift(db, pid, svc, window_start, window_end)
        assert ev_id is not None
        ev = db.execute("SELECT * FROM principal_change_events WHERE id = ?", (ev_id,)).fetchone()
        assert ev["change_type"] == "OPERATION_MIX_SHIFT"


# Scenario 6: Collector stops receiving data: data-quality event, no mass disappearance
def test_collector_gap_telemetry_gate(clean_db):
    now = int(time.time() * 1000)
    with db_transaction(clean_db) as db:
        # Window with 0 spans
        quality = detect_telemetry_quality_gates(db, now - 900_000, now)
        assert quality["is_gap"] is True


# Scenario 7: Generic SOAP failure does not infer authentication failure
def test_generic_soap_failure_not_auth_failure():
    raw_500 = {
        "_source": {
            "@timestamp": "2026-09-01T12:00:00Z",
            "trace": {"id": "trace_err_1"},
            "transaction": {"id": "span_err_1", "name": "POST /PaymentService", "duration": {"us": 500}},
            "service": {"name": "payment-service"},
            "http": {"response": {"status_code": 500}},
            "error": {"code": "DatabaseTimeoutFault"},
            "event": {"outcome": "failure"}
        }
    }
    norm = normalize_otel_record(raw_500)
    assert norm.http_status == 500
    assert norm.outcome == "failure"
    # Authentication result remains unknown (NOT inferred as auth failure!)
    assert norm.auth_result == "unknown"

    # Explicit WS-Security authentication fault
    raw_wsse_fault = {
        "_source": {
            "@timestamp": "2026-09-01T12:00:00Z",
            "trace": {"id": "trace_err_2"},
            "transaction": {"id": "span_err_2", "name": "POST /PaymentService", "duration": {"us": 500}},
            "service": {"name": "payment-service"},
            "http": {"response": {"status_code": 500}},
            "soap": {"fault": {"code": "wsse:FailedAuthentication"}}
        }
    }
    norm_wsse = normalize_otel_record(raw_wsse_fault)
    assert norm_wsse.auth_result == "failure"
    assert "FailedAuthentication" in norm_wsse.auth_evidence


# Scenario 8: Familiar caller changes credentials emits CALLER_PRINCIPAL_SWITCH
def test_caller_principal_switch_detection(clean_db):
    now = int(time.time() * 1000)
    caller = "checkout-service"
    target = "payment-service"
    op = "PaymentService/charge"
    window_start = now - 900_000
    window_end = now

    with db_transaction(clean_db) as db:
        # History: checkout-service -> payment-service used "prod_checkout_key" 150 times (100% share)
        for i in range(150):
            ts = now - 86_400_000 + i * 1000
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, caller_service,
                                    service_name, target_service, principal_name, principal_id, operation, operation_key,
                                    duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prod_checkout_key', 'production:prod_checkout_key', 'charge', ?, 10, 10000, ?)
            """, (f"hc_{i}", ts // 1000, ts, f"tc_{i}", f"sc_{i}", caller, target, target, op, ts))

        # Current window: checkout-service switches credentials to "rogue_admin" 20 times
        for i in range(20):
            ts = window_start + i * 1000
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, caller_service,
                                    service_name, target_service, principal_name, principal_id, operation, operation_key,
                                    duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'rogue_admin', 'production:rogue_admin', 'charge', ?, 10, 10000, ?)
            """, (f"wc_{i}", ts // 1000, ts, f"twc_{i}", f"swc_{i}", caller, target, target, op, ts))

        ev_id = detect_caller_principal_switch(db, caller, target, op, window_start, window_end)
        assert ev_id is not None
        ev = db.execute("SELECT * FROM principal_change_events WHERE id = ?", (ev_id,)).fetchone()
        assert ev["change_type"] == "CALLER_PRINCIPAL_SWITCH"
        assert ev["base_importance"] == "high"


# Scenario 9: Burst repeats same novel operation 10,000 times adds one novelty contribution
def test_repetitive_novel_operation_burst_deduplicated_to_single_contribution(clean_db):
    now = int(time.time() * 1000)
    pid = "production:burst_user"
    with db_transaction(clean_db) as db:
        # Simulate burst repeating same novel operation 100 times in the same window
        for i in range(100):
            emit_behavioral_change(
                db,
                principal_id=pid,
                change_type="NEW_OPERATION",
                detected_at=now + i * 10,
                operation="PaymentService/dumpKeys",
                new_value="PaymentService/dumpKeys"
            )

        inc = db.execute("SELECT * FROM incidents WHERE principal_id = ?", (pid,)).fetchone()
        assert inc is not None
        family_scores = json.loads(inc["family_scores_json"])
        # Exactly 15 points contributed for the novel operation, not 15 * 100!
        assert family_scores["access"] == 15
        assert inc["score"] == 15
        assert inc["priority"] == "low"


# Scenario 10: Explicit authentication failure burst followed by success
def test_explicit_auth_failure_burst_and_recovery(clean_db):
    now = int(time.time() * 1000)
    pid = "production:locked_user"
    window_start = now - 900_000
    window_end = now

    with db_transaction(clean_db) as db:
        # 6 explicit auth failures
        for i in range(6):
            ts = window_start + i * 1000
            db.execute("""
                INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                                    principal_name, principal_id, operation, operation_key, auth_result, auth_evidence,
                                    duration_ms, duration_us, created_at)
                VALUES (?, ?, ?, ?, ?, 'auth-svc', 'auth-svc', 'locked_user', ?, 'login', 'login', 'failure',
                        'soap_fault:wsse:FailedAuthentication', 10, 10000, ?)
            """, (f"af_{i}", ts // 1000, ts, f"taf_{i}", f"saf_{i}", pid, ts))

        # 1 explicit auth success shortly after
        ts_ok = window_start + 10_000
        db.execute("""
            INSERT INTO traces (event_uid, timestamp, timestamp_ms, trace_id, span_id, service_name, target_service,
                                principal_name, principal_id, operation, operation_key, auth_result, auth_evidence,
                                duration_ms, duration_us, created_at)
            VALUES ('af_ok', ?, ?, 'taf_ok', 'saf_ok', 'auth-svc', 'auth-svc', 'locked_user', ?, 'login', 'login',
                    'success', 'security_event:auth_success', 10, 10000, ?)
        """, (ts_ok // 1000, ts_ok, pid, ts_ok))

        ev_ids = detect_explicit_auth_anomalies(db, pid, window_start, window_end)
        assert len(ev_ids) > 0
        ev = db.execute("SELECT * FROM principal_change_events WHERE id = ?", (ev_ids[0],)).fetchone()
        assert ev["change_type"] == "FAILURE_THEN_SUCCESS"


def test_principal_normalization_without_realm():
    raw = {
        "_source": {
            "@timestamp": "2026-09-01T12:00:00Z",
            "trace": {"id": "t_realm_test"},
            "transaction": {"id": "s_realm_test", "name": "POST /login"},
            "service": {"name": "auth-service", "environment": "production"},
            "labels": {"wsse_username": "test_agent"},
            "user": {"domain": "CORP_DOMAIN"},
            "auth": {"realm": "IGNORED_REALM"}
        }
    }
    trace = normalize_otel_record(raw)
    assert trace.principal_name == "test_agent"
    assert trace.principal_id == "production:test_agent"
    assert not hasattr(trace, "principal_realm")


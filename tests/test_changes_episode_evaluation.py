from backend.app.api.changes import _evaluate_episode


def _signal(
    signal_type: str,
    *,
    source: str = "principal_change",
    severity: str = "medium",
    status: str = "new",
    delta: float | None = None,
    source_ip: str | None = None,
    reason: dict | None = None,
):
    raw_key = "anomaly_type" if source == "anomaly" else "change_type"
    return {
        "source": source,
        "severity": severity,
        "raw_status": status,
        "context": {"source_ip": source_ip},
        "highlights": [{"label": "TPS", "before": 4.2, "after": 17.8, "delta": delta}] if delta is not None else [],
        "signal": {raw_key: signal_type, "reason": reason or {}},
    }


def test_expected_review_is_not_presented_as_abnormal():
    result = _evaluate_episode([_signal("NEW_TARGET", status="expected")])

    assert result["state"] == "expected"
    assert result["is_abnormal"] is False


def test_suppression_is_not_presented_as_expected_behavior():
    result = _evaluate_episode([_signal("NEW_TARGET", status="suppressed")])

    assert result["state"] != "expected"
    assert result["is_abnormal"] is False


def test_known_load_balancer_ip_remains_a_change_only():
    result = _evaluate_episode([
        _signal(
            "NEW_SOURCE_IP",
            severity="high",
            source_ip="10.20.4.7",
            reason={
                "source_ip_role": "load_balancer",
                "attribution_confidence": "low",
            },
        )
    ])

    assert result["state"] == "changed"
    assert result["is_abnormal"] is False
    assert result["infrastructure_only"] is True


def test_correlated_access_and_rate_changes_need_attention():
    result = _evaluate_episode([
        _signal("NEW_TARGET"),
        _signal("NEW_OPERATION"),
        _signal("PRINCIPAL_RATE_SURGE", delta=324),
    ])

    assert result["state"] == "needs_attention"
    assert result["is_abnormal"] is True
    assert result["correlated"] is True
    assert result["domains"] == ["access", "traffic"]


def test_critical_error_evidence_promotes_correlated_episode():
    result = _evaluate_episode([
        _signal("ERROR_RATE", source="anomaly", severity="critical", delta=500),
        _signal("NEW_OPERATION"),
    ])

    assert result["state"] == "critical"
    assert result["is_abnormal"] is True

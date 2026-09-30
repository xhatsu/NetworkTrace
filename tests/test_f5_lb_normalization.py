from backend.app.services.normalization import normalize_otel_record, classify_source_ip_role


def test_f5_bigip_xff_extraction():
    raw = {
        "service": {"name": "bpm-sale-service"},
        "client": {"ip": "10.240.147.249"},
        "destination": {"address": "10.240.147.79", "port": 8080},
        "http": {
            "request": {
                "method": "POST",
                "headers": {
                    "x-forwarded-for": "117.1.28.250, 10.240.147.80",
                },
            },
            "response": {"status_code": 200},
        },
        "transaction": {"name": "SALE_SERVICE/bpm/sale/InterfaceForSale"},
    }
    normalized = normalize_otel_record(raw)
    assert normalized.caller_ip == "10.240.147.249"
    assert normalized.original_client_ip == "117.1.28.250"
    assert normalized.original_client_ip_trusted == 1

    role, label, confidence = classify_source_ip_role(normalized.caller_ip)
    assert role == "load_balancer"
    assert confidence == "low"


def test_f5_bigip_x_real_ip_priority():
    raw = {
        "service": {"name": "bpm-sale-service"},
        "labels": {
            "net_sock_peer_addr": "10.240.147.249",
        },
        "destination": {"address": "10.240.147.79"},
        "http": {
            "request": {
                "method": "POST",
                "headers": {
                    "x-forwarded-for": "10.240.147.80, 10.240.147.112",
                    "x-real-ip": "117.1.28.250",
                },
            },
        },
    }
    normalized = normalize_otel_record(raw)
    assert normalized.original_client_ip == "117.1.28.250"
    assert normalized.original_client_ip_trusted == 1


def test_untrusted_client_cannot_spoof_xff():
    raw = {
        "service": {"name": "public-service"},
        "client": {"ip": "203.0.113.50"},  # Public untrusted client direct connection
        "http": {
            "request": {
                "method": "GET",
                "headers": {
                    "x-forwarded-for": "10.0.0.1",
                },
            },
        },
    }
    normalized = normalize_otel_record(raw)
    assert normalized.original_client_ip == "203.0.113.50"
    assert normalized.original_client_ip_trusted == 0


def test_f5_unresolved_ip_handling():
    """When F5 forwards request without XFF/X-Real-IP, do NOT guess F5 as client!"""
    raw = {
        "service": {"name": "bpm-sale-service"},
        "client": {"ip": "10.240.147.249"},  # F5 BIG-IP IP
        "http": {
            "request": {
                "method": "POST",
                "headers": {},  # No XFF header
            },
            "response": {"status_code": 200},
        },
        "user": {"name": "alice"},
    }
    normalized = normalize_otel_record(raw)
    assert normalized.observed_ip == "10.240.147.249"
    assert normalized.effective_client_ip == "unavailable"
    assert normalized.effective_client_ip != "10.240.147.249"
    assert normalized.ip_resolution == "load_balancer_unresolved"
    assert normalized.client_identity_quality == "low"
    assert normalized.traffic_class == "identified"
    assert normalized.context_quality == "medium"  # identified user, but unresolved LB client IP


def test_anonymous_and_f5_unresolved_quality_ladder():
    """Worst-case: anonymous traffic behind unresolved F5 load balancer."""
    raw = {
        "service": {"name": "public-api"},
        "client": {"ip": "10.240.147.249"},
        "http": {
            "request": {"method": "GET"},
            "response": {"status_code": 200},
        },
        # No user / principal
    }
    normalized = normalize_otel_record(raw)
    assert normalized.observed_ip == "10.240.147.249"
    assert normalized.effective_client_ip == "unavailable"
    assert normalized.ip_resolution == "load_balancer_unresolved"
    assert normalized.client_identity_quality == "low"
    assert normalized.traffic_class == "anonymous"
    assert normalized.context_quality == "very_low"


def test_kubernetes_pod_ip_not_blindly_marked_lb():
    """Kubernetes internal Pod IPs (e.g. 10.244.1.203) should NOT be blindly marked as LB."""
    raw = {
        "service": {"name": "order-service"},
        "client": {"ip": "10.244.1.203"},
        "http": {
            "request": {"method": "POST"},
            "response": {"status_code": 200},
        },
    }
    normalized = normalize_otel_record(raw)
    assert normalized.observed_ip == "10.244.1.203"
    assert normalized.effective_client_ip == "10.244.1.203"
    assert normalized.ip_resolution == "direct"
    assert normalized.client_identity_quality == "high"

    role, label, confidence = classify_source_ip_role("10.244.1.203")
    assert role == "client"
    assert label == "Internal client address"
    assert confidence == "high"


def test_cidr_matching_in_trusted_proxies(monkeypatch):
    """CIDR subnets configured in OTEL_TRUSTED_PROXIES are correctly identified."""
    from dataclasses import replace
    from backend import config
    from backend.app.services import normalization

    # Monkeypatch settings with a CIDR
    monkeypatch.setattr(config, "settings", replace(config.settings, trusted_proxies=("10.99.0.0/16",)))
    normalization._is_trusted_proxy_cached.cache_clear()

    # 10.99.1.5 is inside 10.99.0.0/16
    assert normalization._is_ip_in_configured_targets("10.99.1.5", ("10.99.0.0/16",)) is True
    # 10.244.1.203 is NOT inside 10.99.0.0/16
    assert normalization._is_ip_in_configured_targets("10.244.1.203", ("10.99.0.0/16",)) is False
    assert normalization._is_trusted_proxy("10.99.1.5") is True
    assert normalization._is_trusted_proxy("10.244.1.203") is False

from __future__ import annotations

from contextlib import contextmanager

from backend.app.repositories import interactive_topology_repository as module


def _captured_args(monkeypatch, api, service):
    seen = {}

    class Db:
        def execute(self, sql, args):
            seen["sql"], seen["args"] = sql, list(args)
            return []

    @contextmanager
    def connection(*_args, **_kwargs):
        yield Db()

    monkeypatch.setattr(module, "get_connection", connection)
    repo = module.InteractiveTopologyRepository.__new__(module.InteractiveTopologyRepository)
    repo.db_path = None
    repo._es_repo = type("NoEs", (), {"is_configured": lambda self: False})()
    window = {"start_ms": 0, "end_ms": 3_600_000}
    repo.principal_ips("-anonymous-", window, 50, None, service=service, api=api)
    return seen


def test_api_filter_matches_bare_and_service_prefixed_spellings(monkeypatch):
    for api in ("POST /api/v1/orders/checkout", "order-service/POST /api/v1/orders/checkout"):
        seen = _captured_args(monkeypatch, api, "order-service")
        assert "api IN (?, ?)" in seen["sql"]
        assert "POST /api/v1/orders/checkout" in seen["args"]
        assert "order-service/POST /api/v1/orders/checkout" in seen["args"]
        assert "-anonymous-" in seen["args"]


def test_api_filter_without_service_keeps_one_spelling(monkeypatch):
    seen = _captured_args(monkeypatch, "POST /x", None)
    assert seen["args"].count("POST /x") == 2

"""Jev contract and complete advisory pipeline, with no real provider requests."""
import asyncio
import copy
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import changes
from backend.app.repositories.semantic_assessment_repository import (
    SemanticAssessmentRepository, assessment_from_row,
)
from backend.app.services.change_episodes import _anomaly_signal, _merge_signals, attach_semantic_assessments
from backend.app.services.semantic_provider import (
    CATEGORY_CRITERIA, PRIORITY_CRITERIA, RECOMMENDATION_CRITERIA,
    OpenRouterSemanticProvider, SemanticProviderNotConfigured, create_semantic_provider,
)
from backend.app.services.semantic_worker import SemanticAssessmentWorker, _assessment_input


def settings(**overrides):
    return SimpleNamespace(**{
        "semantic_assessment_enabled": True, "semantic_provider": "openrouter",
        "semantic_base_url": "https://openrouter.ai", "semantic_model": "typesafe/jev-1.13",
        "semantic_api_key": "mock-key-only", "semantic_timeout_seconds": 15,
        "semantic_batch_size": 2, "semantic_budget_seconds": 1, "semantic_retry_seconds": 900,
        **overrides,
    })


def episode():
    return _merge_signals([_anomaly_signal({
        "id": 123, "anomaly_type": "latency", "severity": "critical", "target_service": "private-name",
        "detected_at": 1800000000000, "current_value": 600, "baseline_value": 100,
    })])[0]


def choice(criteria, selected):
    return {"type": "choice", "choice": selected, "confidence": 1,
            "probabilities": {key: int(key == selected) for key in criteria}}


def response_body():
    return {"model": "typesafe/jev-1.13-20260917", "id": "mock-request", "provider": "TypeSafe",
            "answers": {"abnormality": {"type": "noul", "noul": 0.8},
                        "category": choice(CATEGORY_CRITERIA, "performance"),
                        "priority": choice(PRIORITY_CRITERIA, "investigate"),
                        "recommendation": choice(RECOMMENDATION_CRITERIA, "inspect_traces")},
            "usage": {"input_tokens": 100, "output_tokens": 40, "cost": 0.0001}}


async def assess(body=None, status=200, handler=None):
    async with httpx.AsyncClient(base_url="https://openrouter.ai", transport=httpx.MockTransport(
        handler or (lambda request: httpx.Response(status, json=body if body is not None else response_body()))
    )) as client:
        return await OpenRouterSemanticProvider(settings(), client).assess(_assessment_input(episode()))


class MemoryRepository:
    def __init__(self):
        self.rows = {}

    def get_latest_many(self, keys):
        return [copy.deepcopy(row) for (key, _), row in self.rows.items() if key in keys]

    def save(self, key, result, **kwargs):
        row = result.model_dump()
        row.update(episode_key=key, updated_at_ms=int(time.time() * 1000),
                   evaluated_at_ms=result.evaluated_at, **kwargs)
        self.rows[key, result.episode_version] = row

    def mark_pending(self, key, version, **kwargs):
        from backend.app.models.semantic_assessment import SemanticAssessmentV1
        self.save(key, SemanticAssessmentV1(status="pending", episode_version=version), **kwargs)

    def mark_failed(self, key, version, **kwargs):
        from backend.app.models.semantic_assessment import SemanticAssessmentV1
        self.save(key, SemanticAssessmentV1(status="failed", episode_version=version), **kwargs)


def test_adviser_migration_runs_with_existing_statement_parser(monkeypatch):
    from backend.app.repositories import clickhouse_migrator as migrator
    version = "015_semantic_adviser.sql"
    statements = []

    class Client:
        def query(self, sql):
            return SimpleNamespace(result_rows=[(p.name,) for p in migrator.MIGRATIONS_DIR.glob("*.sql")
                                               if p.name != version])

        def command(self, sql, **kwargs):
            sql = sql.strip()
            if sql.startswith("CREATE TABLE") or sql.startswith("INSERT INTO schema_migrations"):
                return
            assert sql.startswith("ALTER TABLE semantic_assessments ADD COLUMN IF NOT EXISTS ")
            statements.append(sql)

    monkeypatch.setattr(migrator, "ensure_database", lambda *args: None)
    monkeypatch.setattr(migrator, "get_clickhouse_client", lambda *args: Client())
    assert migrator.run_clickhouse_migrations() == [version]
    assert len(statements) == 4


def test_typed_request_and_provenance():
    def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
        payload = json.loads(request.content)
        assert payload["model"] == "typesafe/jev-1.13"
        assert set(payload["questions"]) == {"abnormality", "category", "priority", "recommendation"}
        assert "private-name" not in request.content.decode()
        assert payload["state"]["episode"]["signal_ids"] == ["anm-123"]
        return httpx.Response(200, json=response_body())
    result = asyncio.run(assess(handler=handler))
    assert result.recommendation == "inspect_traces"
    assert result.input_signal_ids == ["anm-123"]
    assert result.supporting_signal_ids == []  # Input provenance is not model attribution.
    assert result.category == "performance"


@pytest.mark.parametrize("status", [301, 401, 402, 403, 404, 429, 500, 503, 529])
def test_http_errors_are_sanitized(status):
    with pytest.raises(SemanticProviderNotConfigured) as error:
        asyncio.run(assess({"error": "mock-sensitive-provider-body"}, status))
    assert "mock-sensitive" not in str(error.value)


@pytest.mark.parametrize("mutation", [
    lambda b: b.update(model="typesafe/jev-1.130"),
    lambda b: b["answers"].pop("recommendation"),
    lambda b: b["answers"]["abnormality"].update(noul="0.8"),
    lambda b: b["answers"]["abnormality"].update(noul=True),
    lambda b: b["answers"]["abnormality"].update(noul=2),
    lambda b: b["answers"]["priority"].update(choice="execute-command"),
    lambda b: b["answers"]["recommendation"].update(choice="execute-command"),
    lambda b: b["answers"]["category"]["probabilities"].update(performance=0.5),
    lambda b: b["answers"]["recommendation"]["probabilities"].pop("observe"),
    lambda b: b["answers"]["recommendation"].update(extra="not-allowed"),
    lambda b: b["usage"].update(cost="0.1"),
])
def test_malformed_typed_results_rejected(mutation):
    body = response_body()
    mutation(body)
    with pytest.raises(SemanticProviderNotConfigured):
        asyncio.run(assess(body))


@pytest.mark.parametrize("kind", ["timeout", "json", "oversized"])
def test_transport_and_body_failures(kind):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("mock-sensitive", request=request)
        return httpx.Response(200, content=b"not-json" if kind == "json" else b"x" * 17000)
    with pytest.raises(SemanticProviderNotConfigured) as error:
        asyncio.run(assess(handler=handler))
    assert "mock-sensitive" not in str(error.value)


def test_disabled_and_configuration_restrictions():
    assert create_semantic_provider(settings(semantic_assessment_enabled=False)) is None
    for overrides in ({"semantic_model": "~typesafe/jev-latest"},
                      {"semantic_base_url": "https://openrouter.ai:8443"},
                      {"semantic_base_url": "http://openrouter.ai"},
                      {"semantic_api_key": ""}):
        with pytest.raises(SemanticProviderNotConfigured):
            create_semantic_provider(settings(**overrides))


def test_worker_to_list_detail_and_stale_api(monkeypatch):
    original = episode()
    before = copy.deepcopy(original)
    repo = MemoryRepository()
    calls = []
    async def run():
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response_body())
        async with httpx.AsyncClient(base_url="https://openrouter.ai", transport=httpx.MockTransport(handler)) as client:
            worker = SemanticAssessmentWorker(repo, OpenRouterSemanticProvider(settings(), client))
            assert (await worker.run_once([original, original]))["assessed"] == 1
            assert (await worker.run_once([original]))["assessed"] == 0
    asyncio.run(run())
    assert len(calls) == 1
    assert original == before
    monkeypatch.setattr(changes, "_load_signals", lambda *a: [])
    monkeypatch.setattr(changes, "_merge_signals", lambda *a: [copy.deepcopy(original)])
    monkeypatch.setattr(changes, "get_source_signals", lambda *a: [])
    monkeypatch.setattr(changes, "attach_semantic_assessments", lambda episodes: attach_semantic_assessments(episodes, repo))
    app = FastAPI()
    app.include_router(changes.router)
    with TestClient(app) as client:
        for url in ("/api/v1/changes", "/api/v1/changes/anm-123"):
            res = client.get(url)
            assert res.status_code == 200
            item = res.json()["items"][0] if url.endswith("changes") else res.json()
            assert item["state"] == before["state"]
            assert item["severity"] == before["severity"]
            assert item["semantic_assessment"]["recommendation"] == "inspect_traces"
        original["episode_version"] = "a" * 64
        stale = client.get("/api/v1/changes/anm-123").json()["semantic_assessment"]
        assert stale["status"] == "stale"
        assert stale["input_signal_ids"] == ["anm-123"]
    assert len(calls) == 1  # Reads never invoke the provider.


def test_retry_budget_fail_open_and_no_sensitive_logs(caplog):
    repo = MemoryRepository()
    first = episode()
    second = {**first, "episode_key": "second"}
    async def run():
        async with httpx.AsyncClient(base_url="https://openrouter.ai", transport=httpx.MockTransport(
            lambda request: httpx.Response(402, json={"error": "mock-sensitive"})
        )) as client:
            worker = SemanticAssessmentWorker(repo, OpenRouterSemanticProvider(settings(), client), batch_size=1)
            assert (await worker.run_once([first, second]))["failed"] == 1
            assert len(repo.rows) == 1
            assert (await worker.run_once([first]))["failed"] == 0
            row = next(iter(repo.rows.values()))
            row["updated_at_ms"] = 0
            assert (await worker.run_once([first]))["failed"] == 1
            row["status"] = "pending"
            row["updated_at_ms"] = 0
            # Abandoned pending work is also retryable.
            repo.rows[first["episode_key"], first["episode_version"]] = row
            assert (await worker.run_once([first]))["failed"] == 1
    asyncio.run(run())
    assert "mock-sensitive" not in caplog.text
    attach_semantic_assessments([first], repo)
    assert first["semantic_assessment"]["status"] == "failed"
    assert first["state"] == "watch"


def test_context_bounds_and_version_changes():
    item = episode()
    item["abnormality"]["reasons"] = ["mock-sensitive" * 10000]
    item["signals"] = [{"id": f"anm-{i}", "type": "latency"} for i in range(500)]
    data = _assessment_input(item)
    assert len(data.episode["signal_ids"]) == 100
    assert data.episode["signals_truncated"]
    assert "mock-sensitive" not in data.model_dump_json()
    assert len(data.model_dump_json()) < 24000
    signal = _anomaly_signal({"id": 123, "anomaly_type": "latency", "target_service": "test",
                              "detected_at": 1800000000000, "current_value": 600, "baseline_value": 100})
    first = _merge_signals([signal])[0]
    signal["last_seen_at"] += 300000
    assert _merge_signals([signal])[0]["episode_version"] != first["episode_version"]


def test_repository_column_alignment_and_roundtrip():
    result = asyncio.run(assess())
    inserted = []
    class Client:
        def query(self, *a, **kw):
            return SimpleNamespace(result_rows=[])
        def insert(self, table, values, column_names):
            assert table == "semantic_assessments"
            assert len(values[0]) == len(column_names)
            inserted.append(dict(zip(column_names, values[0])))
    @contextmanager
    def connection(path):
        yield SimpleNamespace(client=Client())
    repo = SemanticAssessmentRepository(connection_factory=connection)
    repo.save("episode", result, provider_model="typesafe/jev-1.13", input_digest="a" * 64)
    restored = assessment_from_row(inserted[0])
    assert restored == result


def test_scheduler_disabled_failure_and_timeout(monkeypatch):
    from backend import worker as scheduler
    from backend.app.services import semantic_worker, semantic_provider
    monkeypatch.setattr(scheduler, "settings", settings(semantic_assessment_enabled=False))
    monkeypatch.setattr(scheduler, "_load_signals", lambda *a, **kw: (_ for _ in ()).throw(AssertionError()))
    assert scheduler._run_semantic_assessments()["status"] == "disabled"
    monkeypatch.setattr(scheduler, "settings", settings())
    assert scheduler._run_semantic_assessments()["status"] == "unavailable"
    monkeypatch.setattr(scheduler, "_load_signals", lambda *a, **kw: [])
    monkeypatch.setattr(semantic_provider, "create_semantic_provider", lambda *a: object())
    async def slow(self, episodes):
        await asyncio.sleep(5)
    monkeypatch.setattr(semantic_worker.SemanticAssessmentWorker, "run_once", slow)
    started = time.monotonic()
    assert scheduler._run_semantic_assessments()["status"] == "unavailable"
    assert time.monotonic() - started < 3


def test_new_version_reassessed_and_noneligible_skipped():
    repo = MemoryRepository()
    item = episode()
    async def run():
        async with httpx.AsyncClient(base_url="https://openrouter.ai", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_body())
        )) as client:
            worker = SemanticAssessmentWorker(repo, OpenRouterSemanticProvider(settings(), client))
            assert (await worker.run_once([{**item, "status": "resolved"}, {**item, "state": "expected"}]))["eligible"] == 0
            assert (await worker.run_once([item]))["assessed"] == 1
            item["episode_version"] = "b" * 64
            assert (await worker.run_once([item]))["assessed"] == 1
    asyncio.run(run())
    assert len(repo.rows) == 2


def test_oversized_input_never_calls_provider():
    data = _assessment_input(episode())
    data.context["large"] = "x" * 25000
    async def run():
        async with httpx.AsyncClient(base_url="https://openrouter.ai", transport=httpx.MockTransport(
            lambda request: pytest.fail("oversized input must not reach provider")
        )) as client:
            with pytest.raises(SemanticProviderNotConfigured):
                await OpenRouterSemanticProvider(settings(), client).assess(data)
    asyncio.run(run())


def test_scheduler_complete_stage(monkeypatch):
    from backend import worker as scheduler
    from backend.app.services import semantic_provider
    from backend.app.repositories import semantic_assessment_repository
    repo = MemoryRepository()
    item = episode()
    class Provider:
        async def assess(self, data):
            return await assess()
    monkeypatch.setattr(scheduler, "settings", settings())
    monkeypatch.setattr(scheduler, "_load_signals", lambda *a, **kw: [])
    monkeypatch.setattr(scheduler, "_merge_signals", lambda *a: [item])
    monkeypatch.setattr(semantic_provider, "create_semantic_provider", lambda *a: Provider())
    monkeypatch.setattr(semantic_assessment_repository, "SemanticAssessmentRepository", lambda *a: repo)
    assert scheduler._run_semantic_assessments()["assessed"] == 1
    assert scheduler._run_semantic_assessments()["assessed"] == 0


def test_helm_semantic_secret_isolation_and_single_owner():
    import shutil
    import subprocess
    from pathlib import Path
    import yaml
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("helm unavailable")
    chart = Path.cwd() / "deploy/helm/tracescope"
    args = [helm, "template", "jev-test", str(chart), "--set", "semantic.enabled=true",
            "--set", "secrets.internalApiToken=0123456789abcdef0123456789abcdef",
            "--set", "secrets.semanticApiKey=synthetic-test-canary"]
    rendered = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    docs = list(yaml.safe_load_all(rendered))
    config = next(d["data"] for d in docs if d and d["kind"] == "ConfigMap" and "OTEL_SEMANTIC_MODEL" in d.get("data", {}))
    assert config["OTEL_SEMANTIC_MODEL"] == "typesafe/jev-1.13"
    assert config["OTEL_SEMANTIC_ASSESSMENT_ENABLED"] == "true"
    assert "OTEL_SEMANTIC_API_KEY" not in config
    assert "synthetic-test-canary" not in json.dumps(config)
    secret = next(d for d in docs if d and d["kind"] == "Secret")
    assert secret["stringData"]["OTEL_SEMANTIC_API_KEY"] == "synthetic-test-canary"
    worker = next(c for d in docs if d and d["kind"] == "StatefulSet"
                  for c in d["spec"]["template"]["spec"]["containers"] if c["name"] == "analytics-worker")
    assert any("secretRef" in item for item in worker["envFrom"])
    rejected = subprocess.run(args + ["--set", "app.replicaCount=2"], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "single-owner" in rejected.stderr


def test_worker_prioritizes_critical_and_fails_open_on_store_error():
    repo = MemoryRepository()
    item = episode()
    critical = {**item, "episode_key": "critical-episode", "state": "critical"}
    async def run():
        async with httpx.AsyncClient(base_url="https://openrouter.ai", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_body())
        )) as client:
            worker = SemanticAssessmentWorker(repo, OpenRouterSemanticProvider(settings(), client), batch_size=1)
            assert (await worker.run_once([item, critical]))["assessed"] == 1
            assert next(iter(repo.rows))[0] == "critical-episode"
            def unavailable(keys):
                raise RuntimeError("unavailable storage")
            repo.get_latest_many = unavailable
            assert (await worker.run_once([item]))["failed"] == 1
    asyncio.run(run())

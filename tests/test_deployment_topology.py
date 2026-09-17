"""Deployment-topology tests for the OtelTrace / TraceScope Kubernetes refactor.

Covers three things that must hold after splitting the monolith into
independently deployable workloads:

1. Role isolation — the ingest and agent-stats entrypoints expose only their
   own HTTP surface and can never reach each other's routes.
2. The agent-stats workload never starts the trace SQLite ``IngestWriter``.
3. The stateless edge roles forward through an internal storage boundary.
4. Only one StatefulSet pod mounts SQLite; its worker is a sidecar.
"""
from __future__ import annotations

import importlib.util
import shutil
import re
import subprocess
from pathlib import Path

import httpx
import pytest

from backend.app.application import (
    ROLE_AGENT_STATS,
    ROLE_ALL,
    ROLE_INGEST,
    VALID_ROLES,
    create_app,
)
from backend.config import settings


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = REPO_ROOT / "deploy" / "k8s"
DOCKERFILE = REPO_ROOT / "deploy" / "docker" / "Dockerfile"


def _load_validator():
    path = MANIFEST_DIR / "validate_manifests.py"
    spec = importlib.util.spec_from_file_location("tracescope_manifest_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _load_bootstrap():
    path = REPO_ROOT / "bootstrap" / "nt-bootstrap.py"
    spec = importlib.util.spec_from_file_location("tracescope_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _openapi_paths(app) -> set[str]:
    return set(app.openapi().get("paths", {}).keys())


def _request(app, method: str, url: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    import asyncio

    return asyncio.run(send())


# ---------------------------------------------------------------------------
# 1. Role surface / isolation
# ---------------------------------------------------------------------------
def test_valid_roles_are_declared():
    assert VALID_ROLES == (ROLE_ALL, ROLE_INGEST, ROLE_AGENT_STATS)


def test_invalid_role_is_rejected():
    with pytest.raises(ValueError):
        create_app("does-not-exist")


def test_all_role_preserves_the_full_monolith_surface():
    app = create_app(ROLE_ALL)
    paths = _openapi_paths(app)
    # Spot-check one route from each historical feature area.
    assert "/api/v1/health" in paths
    assert "/api/v1/ingest" in paths
    assert "/api/v1/ingestion/status" in paths
    assert "/api/agent/stats" in paths
    assert "/api/v1/overview" in paths
    assert "/api/v1/topology" in paths
    assert "/api/v1/anomalies" in paths
    assert "/api/v1/incidents" in paths
    assert "/api/v1/users" in paths
    assert app.state.tracescope_role == ROLE_ALL


def test_ingest_role_exposes_only_ingest_surface():
    app = create_app(ROLE_INGEST)
    paths = _openapi_paths(app)
    for expected in (
        "/api/v1/ingest",
        "/api/v1/ingest/traces",
        "/api/ingest/apm",
        "/api/ingest/elastic-apm",
        "/api/v1/ingestion/status",
        "/v1/traces",
        "/v1/metrics",
        "/v1/logs",
        "/api/v1/health",
    ):
        assert expected in paths, expected
    # Analytics and agent-telemetry routes must be absent.
    for forbidden in ("/api/v1/overview", "/api/v1/topology", "/api/agent/stats"):
        assert forbidden not in paths, forbidden
    assert app.state.tracescope_role == ROLE_INGEST


def test_agent_stats_role_exposes_only_agent_surface():
    app = create_app(ROLE_AGENT_STATS)
    paths = _openapi_paths(app)
    for expected in (
        "/api/agent/stats",
        "/api/agent/stats/{node}",
        "/api/agent/stats/{node}/history",
        "/api/agent/stats/{node}/{instance_id}",
        "/api/v1/health",
    ):
        assert expected in paths, expected
    for forbidden in (
        "/api/v1/ingest",
        "/api/v1/ingest/traces",
        "/v1/traces",
        "/api/v1/overview",
        "/api/v1/ingestion/status",
    ):
        assert forbidden not in paths, forbidden
    assert app.state.tracescope_role == ROLE_AGENT_STATS


def test_roles_return_404_across_boundaries_at_runtime():
    ingest_app = create_app(ROLE_INGEST)
    agent_app = create_app(ROLE_AGENT_STATS)

    # Ingest pod answers its own health and rejects foreign routes.
    assert _request(ingest_app, "GET", "/api/v1/health").status_code == 200
    assert _request(ingest_app, "GET", "/api/v1/overview").status_code == 404
    assert _request(ingest_app, "GET", "/api/agent/stats").status_code == 404
    # Malformed JSON proves the legacy route exists without starting a writer.
    legacy = _request(ingest_app, "POST", "/api/ingest", content=b"{")
    assert legacy.status_code != 404

    # Agent pod answers its own health and rejects ingest + analytics.
    assert _request(agent_app, "GET", "/api/v1/health").status_code == 200
    assert _request(agent_app, "POST", "/api/v1/ingest", content=b"{}").status_code == 404
    assert _request(agent_app, "GET", "/api/v1/overview").status_code == 404
    assert _request(agent_app, "POST", "/api/agent/stats", content=b"{}").status_code != 404


def test_health_reports_the_running_role():
    for role in VALID_ROLES:
        body = _request(create_app(role), "GET", "/api/v1/health").json()
        assert body["status"] == "ok"
        assert body["service_role"] == role


def test_every_public_mutation_uses_the_central_api_key_policy():
    previous = settings.api_key
    object.__setattr__(settings, "api_key", "central-policy-key")
    try:
        app = create_app(ROLE_ALL)
        checked = set()
        for path, operations in app.openapi()["paths"].items():
            if path.startswith("/internal/"):
                continue
            for method in set(operations) & {"post", "put", "patch", "delete"}:
                concrete = re.sub(r"\{[^}]+\}", "test-value", path)
                response = _request(app, method.upper(), concrete, content=b"{}", headers={"content-type": "application/json"})
                assert response.status_code == 401, (method, path, response.status_code)
                checked.add((method, path))
        assert checked
    finally:
        object.__setattr__(settings, "api_key", previous)


@pytest.mark.parametrize("path", ["/../AGENTS.md", "/%2e%2e/AGENTS.md", "/..%2FAGENTS.md"])
def test_spa_fallback_rejects_path_traversal(path):
    response = _request(create_app(ROLE_ALL), "GET", path)
    assert response.status_code in {200, 400, 404}
    assert b"xHatsu" not in response.content


# ---------------------------------------------------------------------------
# 2. IngestWriter lifecycle scoping
# ---------------------------------------------------------------------------
def test_only_ingest_capable_roles_start_the_sqlite_writer(monkeypatch):
    import backend.app.application as application
    import asyncio

    events: list[str] = []
    monkeypatch.setattr(application.ingest_writer, "start", lambda: events.append("start"))
    monkeypatch.setattr(
        application.ingest_writer, "shutdown", lambda *a, **k: events.append("shutdown")
    )
    monkeypatch.setattr(application.StorageRepository, "migrate", lambda _self: None)

    async def run_lifespan(role):
        role_app = create_app(role)
        async with role_app.router.lifespan_context(role_app):
            pass

    # agent-stats pod must never open a trace write path.
    asyncio.run(run_lifespan(ROLE_AGENT_STATS))
    assert events == []

    # ingest pod owns the writer.
    asyncio.run(run_lifespan(ROLE_INGEST))
    assert events == ["start", "shutdown"]

    events.clear()
    # monolith keeps historical behaviour.
    asyncio.run(run_lifespan(ROLE_ALL))
    assert events == ["start", "shutdown"]


def test_remote_ingest_role_does_not_start_a_sqlite_writer(monkeypatch):
    import backend.app.application as application
    import asyncio

    events: list[str] = []
    monkeypatch.setattr(
        type(application.storage_owner_client), "enabled", property(lambda _self: True)
    )
    monkeypatch.setattr(application.storage_owner_client, "start", _async_noop)
    monkeypatch.setattr(application.storage_owner_client, "shutdown", _async_noop)
    monkeypatch.setattr(application.ingest_writer, "start", lambda: events.append("start"))
    monkeypatch.setattr(application.ingest_writer, "shutdown", lambda: events.append("shutdown"))
    monkeypatch.setattr(application.StorageRepository, "migrate", lambda _self: None)

    async def run_lifespan():
        role_app = create_app(ROLE_INGEST)
        async with role_app.router.lifespan_context(role_app):
            pass

    asyncio.run(run_lifespan())
    assert events == []


async def _async_noop(*_args, **_kwargs):
    return None


# ---------------------------------------------------------------------------
# 3. Container build file
# ---------------------------------------------------------------------------
def test_dockerfile_defines_all_four_role_targets():
    text = DOCKERFILE.read_text(encoding="utf-8")
    for target in ("api", "ingest", "agent-stats", "worker"):
        assert f"AS {target}" in text, target
    assert "backend.main:app" in text
    assert "backend.ingest_main:app" in text
    assert "backend.agent_stats_main:app" in text
    assert "backend.worker" in text
    # non-root + no bytecode writes to a read-only root filesystem
    assert "USER 10001" in text
    assert "PYTHONDONTWRITEBYTECODE=1" in text


def test_bootstrap_scripts_require_https_and_verify_pinned_digests():
    bootstrap = _load_bootstrap()
    digest = "a" * 64
    modern = bootstrap.generate_bootstrap_script(
        "hub.example", 30105, 30102, "https://bootstrap.example", digest,
    )
    legacy = bootstrap.generate_oldkernel_bootstrap_script(
        "hub.example", 30105, 30102, "https://bootstrap.example", digest,
    )
    for script in (modern, legacy):
        assert 'EXPECTED_SHA256="{}"'.format(digest) in script
        assert "sha256sum" in script
        assert 'BOOTSTRAP_URL="https://bootstrap.example' in script


# ---------------------------------------------------------------------------
# 4. Kubernetes manifests
# ---------------------------------------------------------------------------
def test_manifests_validate_cleanly():
    errors, documents = validator.validate(MANIFEST_DIR)
    assert errors == [], "\n".join(errors)
    kinds = [d.get("kind") for d in documents]
    for required in (
        "Namespace",
        "ConfigMap",
        "PersistentVolumeClaim",
        "Deployment",
        "Service",
        "Ingress",
    ):
        assert required in kinds, required
    assert kinds.count("StatefulSet") == 2
    assert kinds.count("Deployment") == 1
    assert kinds.count("Service") == 4
    assert kinds.count("HorizontalPodAutoscaler") == 1


def test_helm_requires_private_token_and_propagates_storage_credentials():
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is not installed")
    chart = REPO_ROOT / "deploy" / "helm" / "tracescope"
    rejected = subprocess.run([
        helm, "template", "test", str(chart),
        "--set", "secrets.internalApiToken=",
    ], text=True, capture_output=True)
    assert rejected.returncode != 0
    assert "internalApiToken" in rejected.stderr
    rendered = subprocess.run([
        helm, "template", "test", str(chart),
        "--set", "secrets.internalApiToken=0123456789abcdef0123456789abcdef",
        "--set", "clickhouse.password=secret-password",
    ], text=True, capture_output=True, check=True).stdout
    assert "OTEL_STORAGE_OWNER_URL" in rendered
    assert "server-snippet" not in rendered
    assert "OTEL_CLICKHOUSE_PASSWORD" in rendered
    assert "CLICKHOUSE_PASSWORD" in rendered
    assert "app-0.1.0" not in rendered and "ingest-0.1.0" not in rendered


def test_helm_global_image_tag_and_component_overrides():
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is not installed")
    chart = REPO_ROOT / "deploy" / "helm" / "tracescope"
    token = "0123456789abcdef0123456789abcdef"

    # 1. Default uses global.image.tag ("0.3.3") across all workloads
    rendered = subprocess.run([
        helm, "template", "test", str(chart),
        "--set", f"secrets.internalApiToken={token}",
        "--set", "ingest.enabled=true",
        "--set", "agentStats.enabled=true",
        "--set", "ui.enabled=true",
    ], text=True, capture_output=True, check=True).stdout
    images = [line.strip().split(": ", 1)[1].strip('"') for line in rendered.splitlines() if line.strip().startswith("image:")]
    assert "xhatsu101/tracescope:0.3.3" in images
    assert "clickhouse/clickhouse-server:24.8" in images
    # No old hardcoded tags
    assert not any("app-0.3.2" in img or "ingest-0.3.2" in img for img in images)
    # Exactly 6 tracescope containers with 0.3.3
    tracescope_imgs = [img for img in images if "tracescope" in img and "clickhouse" not in img]
    assert len(tracescope_imgs) == 6
    assert all(img.endswith(":0.3.3") for img in tracescope_imgs)

    # 2. Dynamic override via global.image.tag
    rendered_dyn = subprocess.run([
        helm, "template", "test", str(chart),
        "--set", f"secrets.internalApiToken={token}",
        "--set", "ingest.enabled=true",
        "--set", "agentStats.enabled=true",
        "--set", "ui.enabled=true",
        "--set", "global.image.tag=0.3.4",
    ], text=True, capture_output=True, check=True).stdout
    images_dyn = [line.strip().split(": ", 1)[1].strip('"') for line in rendered_dyn.splitlines() if line.strip().startswith("image:")]
    tracescope_dyn = [img for img in images_dyn if "tracescope" in img and "clickhouse" not in img]
    assert len(tracescope_dyn) == 6
    assert all(img.endswith(":0.3.4") for img in tracescope_dyn)

    # 3. Dynamic override via global.imageTag
    rendered_alias = subprocess.run([
        helm, "template", "test", str(chart),
        "--set", f"secrets.internalApiToken={token}",
        "--set", "ingest.enabled=true",
        "--set", "agentStats.enabled=true",
        "--set", "ui.enabled=true",
        "--set", "global.imageTag=0.3.5",
    ], text=True, capture_output=True, check=True).stdout
    images_alias = [line.strip().split(": ", 1)[1].strip('"') for line in rendered_alias.splitlines() if line.strip().startswith("image:")]
    tracescope_alias = [img for img in images_alias if "tracescope" in img and "clickhouse" not in img]
    assert len(tracescope_alias) == 6
    assert all(img.endswith(":0.3.5") for img in tracescope_alias)

    # 4. Per-component override
    rendered_override = subprocess.run([
        helm, "template", "test", str(chart),
        "--set", f"secrets.internalApiToken={token}",
        "--set", "ingest.enabled=true",
        "--set", "agentStats.enabled=true",
        "--set", "ui.enabled=true",
        "--set", "global.image.tag=0.3.3",
        "--set", "ingest.image.tag=ingest-custom",
    ], text=True, capture_output=True, check=True).stdout
    images_override = [line.strip().split(": ", 1)[1].strip('"') for line in rendered_override.splitlines() if line.strip().startswith("image:")]
    assert "xhatsu101/tracescope:ingest-custom" in images_override
    non_ingest = [img for img in images_override if "tracescope" in img and "clickhouse" not in img and "ingest-custom" not in img]
    assert len(non_ingest) == 5
    assert all(img.endswith(":0.3.3") for img in non_ingest)


def test_only_clickhouse_mounts_data_and_edges_scale():
    _, documents = validator.validate(MANIFEST_DIR)
    workloads = [d for d in documents if d.get("kind") in ("Deployment", "StatefulSet")]
    data_owners = [d for d in workloads if validator._mounts_data(d)]
    assert [d["metadata"]["name"] for d in data_owners] == ["tracescope-clickhouse"]
    assert data_owners[0]["kind"] == "StatefulSet"
    assert data_owners[0]["spec"]["replicas"] == 1
    deployments = {d["metadata"]["name"]: d for d in workloads if d["kind"] == "Deployment"}
    assert deployments["tracescope-ingest"]["spec"]["replicas"] == 3
    for edge in deployments.values():
        assert not validator._mounts_data(edge)


def test_pvc_is_read_write_once_and_not_shared_over_network_fs():
    _, documents = validator.validate(MANIFEST_DIR)
    pvcs = [d for d in documents if d.get("kind") == "PersistentVolumeClaim"]
    assert len(pvcs) == 1
    assert pvcs[0]["metadata"]["name"] == "clickhouse-data"
    assert pvcs[0]["spec"]["accessModes"] == ["ReadWriteOnce"]


def test_ingress_splits_ingest_agent_and_ui_traffic():
    _, documents = validator.validate(MANIFEST_DIR)
    ingress = next(d for d in documents if d.get("kind") == "Ingress")
    routes: set[str] = set()
    for rule in ingress["spec"]["rules"]:
        for path in rule["http"]["paths"]:
            routes.add(path["backend"]["service"]["name"])
    assert routes == {"tracescope-ingest", "tracescope-api"}

    ingest_paths = {
        p["path"]
        for rule in ingress["spec"]["rules"]
        for p in rule["http"]["paths"]
        if p["backend"]["service"]["name"] == "tracescope-ingest"
    }
    assert {"/api/v1/ingest", "/api/ingest", "/v1/traces", "/api/v1/ingestion/status"} <= ingest_paths

    api_paths = {
        p["path"]
        for rule in ingress["spec"]["rules"]
        for p in rule["http"]["paths"]
        if p["backend"]["service"]["name"] == "tracescope-api"
    }
    assert {"/", "/assets", "/api", "/api/agent/stats"} <= api_paths


def test_validator_catches_a_second_clickhouse_data_owner(tmp_path):
    for path in MANIFEST_DIR.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    target = tmp_path / "32-ingest-deployment.yaml"
    text = target.read_text(encoding="utf-8")
    marker = "      volumes:\n        - name: tmp"
    assert marker in text
    text = text.replace(
        marker,
        "      volumes:\n        - name: data\n          persistentVolumeClaim:\n"
        "            claimName: clickhouse-data\n        - name: tmp",
        1,
    )
    target.write_text(text, encoding="utf-8")

    errors, _ = validator.validate(tmp_path)
    joined = "\n".join(errors)
    assert "only StatefulSet/tracescope-clickhouse may mount ClickHouse data" in joined
    assert "exactly tracescope-clickhouse must mount ClickHouse data" in joined


def test_validator_catches_legacy_sqlite_owner(tmp_path):
    for path in MANIFEST_DIR.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    target = tmp_path / "32-ingest-deployment.yaml"
    text = target.read_text(encoding="utf-8")
    marker = "      volumes:\n        - name: tmp"
    assert marker in text
    text = text.replace(
        marker,
        "      volumes:\n        - name: data\n          persistentVolumeClaim:\n"
        "            claimName: tracescope-data\n        - name: tmp",
        1,
    )
    target.write_text(text, encoding="utf-8")

    errors, _ = validator.validate(tmp_path)
    joined = "\n".join(errors)
    assert "legacy SQLite PVC tracescope-data must not be mounted" in joined


def test_storage_owner_is_the_only_migration_runner():
    """Schema ownership: one init container migrates, everyone else is false."""
    _, documents = validator.validate(MANIFEST_DIR)
    storage = next(d for d in documents if d.get("kind") == "StatefulSet" and d["metadata"]["name"] in ("tracescope-app", "tracescope-storage"))
    pod = storage["spec"]["template"]["spec"]
    init_env = {
        item["name"]: item.get("value")
        for container in pod.get("initContainers", [])
        for item in container.get("env", [])
    }
    assert init_env.get("OTEL_RUN_MIGRATIONS") == "true"

    for container in pod["containers"]:
        env = {item["name"]: item.get("value") for item in container.get("env", [])}
        assert env.get("OTEL_RUN_MIGRATIONS") == "false", container["name"]

    for doc in documents:
        if doc.get("kind") not in ("Deployment", "StatefulSet"):
            continue
        if doc["metadata"]["name"] in ("tracescope-app", "tracescope-storage", "tracescope-clickhouse"):
            continue
        pod_spec = doc["spec"]["template"]["spec"]
        for container in (pod_spec.get("containers") or []) + (
            pod_spec.get("initContainers") or []
        ):
            env = {item["name"]: item.get("value") for item in container.get("env", [])}
            assert env.get("OTEL_RUN_MIGRATIONS") != "true", doc["metadata"]["name"]


def test_validator_enforces_ui_is_stateless(tmp_path):
    """tracescope-ui (if standalone) must be stateless and have no DB access."""
    for path in MANIFEST_DIR.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    target = tmp_path / "38-ui-deployment.yaml"
    target.write_text(
        """apiVersion: apps/v1
kind: Deployment
metadata:
  name: tracescope-ui
  namespace: tracescope
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: tracescope-ui
  template:
    metadata:
      labels:
        app.kubernetes.io/name: tracescope-ui
    spec:
      containers:
        - name: ui
          image: nginx:alpine
          env:
            - name: OTEL_CLICKHOUSE_HOST
              value: rogue
""",
        encoding="utf-8",
    )
    kustomization = tmp_path / "kustomization.yaml"
    import yaml

    kdoc = yaml.safe_load(kustomization.read_text(encoding="utf-8"))
    kdoc.setdefault("resources", []).append("38-ui-deployment.yaml")
    kustomization.write_text(yaml.safe_dump(kdoc), encoding="utf-8")

    errors, _ = validator.validate(tmp_path)
    joined = "\n".join(errors)
    assert "tracescope-ui must have no DB access" in joined


def test_validator_catches_an_unlisted_manifest(tmp_path):
    """kustomize must reference every manifest or a workload silently disappears."""
    import yaml

    for path in MANIFEST_DIR.glob("*.yaml"):
        shutil.copy(path, tmp_path / path.name)
    kustomization = tmp_path / "kustomization.yaml"
    doc = yaml.safe_load(kustomization.read_text(encoding="utf-8"))
    doc["resources"] = [
        resource
        for resource in doc["resources"]
        if resource != "32-ingest-deployment.yaml"
    ]
    kustomization.write_text(yaml.safe_dump(doc), encoding="utf-8")

    errors, _ = validator.validate(tmp_path)
    joined = "\n".join(errors)
    assert "does not reference manifest '32-ingest-deployment.yaml'" in joined


def test_kustomization_references_every_manifest():
    import yaml

    kustomization = MANIFEST_DIR / "kustomization.yaml"
    doc = yaml.safe_load(kustomization.read_text(encoding="utf-8"))
    listed = {Path(resource).name for resource in doc["resources"]}
    for resource in doc["resources"]:
        assert (MANIFEST_DIR / resource).is_file(), resource
    # A manifest that exists but is not listed is never applied.
    for path in MANIFEST_DIR.glob("*.yaml"):
        if path.name == "kustomization.yaml" or ".example." in path.name:
            continue
        assert path.name in listed, path.name
    # The storage owner, api service, ingest deployment and service must
    # all be part of the kustomization.
    assert "32-ingest-deployment.yaml" in listed
    assert "33-ingest-service.yaml" in listed
    assert "31-api-service.yaml" in listed
    assert "37-storage-service.yaml" in listed
    assert "30-storage-statefulset.yaml" in listed
    assert "11-secret.example.yaml" not in listed  # placeholders must not ship

#!/usr/bin/env python3
"""Statically protect TraceScope's ClickHouse deployment invariants.

No cluster and no kubectl required: parses every YAML document under this
directory and enforces the invariants this application actually depends on —
in particular the ClickHouse single-store contract: exactly one database
StatefulSet mounts the ReadWriteOnce data volume, schema changes are serialized,
and horizontally scaled application roles remain storage-free. No
HorizontalPodAutoscaler may target the durable database owner.

Usage::

    python3 deploy/k8s/validate_manifests.py [directory]
    # exit 0 = all checks passed, 1 = violations found, 2 = PyYAML missing
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:  # pragma: no cover - import guard
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

DATA_CLAIM = "clickhouse-data"
NAMESPACE = "tracescope"
CLUSTER_SCOPED = {"Namespace", "ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition"}
SPA_SERVICE_PORTS = {
    "tracescope-api": 30102,
    "tracescope-ingest": 30103,
}


def load_documents(directory: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (documents, errors)."""
    errors: list[str] = []
    documents: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        if path.name == "kustomization.yaml":
            continue  # kustomize config, not a Kubernetes resource
        try:
            text = path.read_text(encoding="utf-8")
            docs = list(yaml.safe_load_all(text))
        except Exception as exc:  # pragma: no cover - defensive
            errors.append("{}: YAML parse error: {}".format(path.name, exc))
            continue
        for doc in docs:
            if doc is None:
                continue
            if not isinstance(doc, dict):
                errors.append("{}: document is not a mapping".format(path.name))
                continue
            doc["__file__"] = path.name
            documents.append(doc)
    return documents, errors


def _containers(doc: dict[str, Any]) -> list[dict[str, Any]]:
    pod = doc.get("spec", {}).get("template", {}).get("spec", {})
    if not isinstance(pod, dict):
        return []
    return [c for c in (pod.get("containers") or []) if isinstance(c, dict)]


def _init_containers(doc: dict[str, Any]) -> list[dict[str, Any]]:
    pod = doc.get("spec", {}).get("template", {}).get("spec", {})
    if not isinstance(pod, dict):
        return []
    return [c for c in (pod.get("initContainers") or []) if isinstance(c, dict)]


def _container_env(container: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item.get("name")): item.get("value")
        for item in (container.get("env") or [])
        if isinstance(item, dict) and item.get("name")
    }


def _pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    return doc.get("spec", {}).get("template", {}).get("spec", {}) or {}


def _mounts_data(doc: dict[str, Any]) -> bool:
    for volume in _pod_spec(doc).get("volumes") or []:
        claim = (volume or {}).get("persistentVolumeClaim") or {}
        if claim.get("claimName") == DATA_CLAIM:
            return True
    return False


def validate(directory: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Return (errors, documents)."""
    if yaml is None:  # pragma: no cover
        return ["PyYAML is not installed; cannot parse manifests"], []
    documents, errors = load_documents(directory)

    if not documents:
        return errors + ["no manifest documents found in {}".format(directory)], []

    seen: dict[tuple[str, str], str] = {}
    workloads: dict[str, dict[str, Any]] = {}
    services: dict[str, dict[str, Any]] = {}
    configmaps: dict[str, dict[str, Any]] = {}

    # ---- structure / identity -------------------------------------------
    for doc in documents:
        where = doc.get("__file__", "?")
        kind = doc.get("kind")
        meta = doc.get("metadata") or {}
        name = meta.get("name")
        if not doc.get("apiVersion"):
            errors.append("{}: missing apiVersion".format(where))
        if not kind:
            errors.append("{}: missing kind".format(where))
        if not name:
            errors.append("{}: missing metadata.name".format(where))
            continue
        key = (str(kind), str(name))
        if key in seen:
            errors.append(
                "duplicate {} '{}' in {} (already in {})".format(kind, name, where, seen[key])
            )
        else:
            seen[key] = where
        if kind not in CLUSTER_SCOPED and meta.get("namespace") != NAMESPACE:
            errors.append(
                "{}/{}: expected metadata.namespace '{}', got {!r}".format(
                    kind, name, NAMESPACE, meta.get("namespace")
                )
            )
        if kind in ("Deployment", "StatefulSet"):
            workloads[str(name)] = doc
        elif kind == "Service":
            services[str(name)] = doc
        elif kind == "ConfigMap":
            configmaps[str(name)] = doc

    # ---- Workload and single-storage-owner invariants -------------------
    data_owners: list[str] = []
    for name, doc in workloads.items():
        where = doc.get("__file__", name)
        spec = doc.get("spec", {}) or {}
        replicas = spec.get("replicas")
        if replicas is None:
            errors.append("Workload/{}: spec.replicas must be explicit".format(name))
        mounts_db = _mounts_data(doc)

        containers = _containers(doc)
        if not containers:
            errors.append("Workload/{}: no containers".format(name))
        for c in containers:
            cname = c.get("name", "?")
            if not c.get("image"):
                errors.append("Workload/{}/{}: missing image".format(name, cname))
            if not c.get("imagePullPolicy"):
                errors.append("Workload/{}/{}: missing imagePullPolicy".format(name, cname))
            res = c.get("resources") or {}
            if not (res.get("requests") and res.get("limits")):
                errors.append(
                    "Workload/{}/{}: resources.requests and limits are required".format(name, cname)
                )
            if not (c.get("readinessProbe") or c.get("livenessProbe") or c.get("startupProbe")):
                errors.append("Workload/{}/{}: no readiness/liveness probe".format(name, cname))
            sc = c.get("securityContext") or {}
            if sc.get("allowPrivilegeEscalation") is not False:
                errors.append(
                    "Workload/{}/{}: securityContext.allowPrivilegeEscalation must be false".format(name, cname)
                )

        for volume in _pod_spec(doc).get("volumes") or []:
            claim = (volume or {}).get("persistentVolumeClaim") or {}
            if claim.get("claimName") == "tracescope-data":
                errors.append(
                    "Workload/{}: legacy SQLite PVC tracescope-data must not be mounted".format(name)
                )

        if mounts_db:
            data_owners.append(name)
            if replicas != 1:
                errors.append(
                    "Workload/{}: mounts ClickHouse data but replicas={} (must be 1)".format(name, replicas)
                )
            if doc.get("kind") != "StatefulSet" or name != "tracescope-clickhouse":
                errors.append(
                    "Workload/{}: only StatefulSet/tracescope-clickhouse may mount ClickHouse data".format(name)
                )
            pvc_seen = False
            for c in containers:
                for m in c.get("volumeMounts") or []:
                    if m.get("mountPath") == "/var/lib/clickhouse":
                        pvc_seen = True
            if not pvc_seen:
                errors.append(
                    "Workload/{}: mounts claim {} but no container mounts it at /var/lib/clickhouse".format(
                        name, DATA_CLAIM
                    )
                )
    if data_owners != ["tracescope-clickhouse"]:
        errors.append("exactly tracescope-clickhouse must mount ClickHouse data; found {}".format(data_owners))

    storage_name = "tracescope-app" if "tracescope-app" in workloads else "tracescope-storage"
    storage = workloads.get("tracescope-app") or workloads.get("tracescope-storage") or {}
    storage_names = {container.get("name") for container in _containers(storage)}
    if storage_names != {"api", "analytics-worker"}:
        errors.append(
            "{} must colocate api and analytics-worker; found {}".format(
                storage_name, sorted(str(name) for name in storage_names)
            )
        )

    # ---- Schema ownership ------------------------------------------------
    # Exactly one process in the fleet applies migrations: the storage/app owner's
    # init container. Runtime containers and stateless edge replicas must not,
    # so a fleet rollout can never race the schema.
    if not any(
        _container_env(container).get("OTEL_RUN_MIGRATIONS") == "true"
        for container in _init_containers(storage)
    ):
        errors.append(
            "{}: an init container must own migrations "
            "(OTEL_RUN_MIGRATIONS=true)".format(storage_name)
        )
    for name, doc in workloads.items():
        for container in _containers(doc) + _init_containers(doc):
            if _container_env(container).get("OTEL_RUN_MIGRATIONS") != "true":
                continue
            if name in ("tracescope-app", "tracescope-storage") and container in _init_containers(doc):
                continue  # the single schema owner
            errors.append(
                "Workload/{}/{}: only the {} init container may run "
                "migrations (OTEL_RUN_MIGRATIONS must be false)".format(
                    name, container.get("name"), storage_name
                )
            )

    # ---- Stateless edge workloads ----------------------------------------
    for edge_name, minimum_replicas in (
        ("tracescope-ingest", 2),
    ):
        edge = workloads.get(edge_name)
        if not edge:
            errors.append("missing stateless edge workload {}".format(edge_name))
            continue
        if edge.get("kind") != "Deployment":
            errors.append("{} must be a Deployment".format(edge_name))
        if int(edge.get("spec", {}).get("replicas", 0)) < minimum_replicas:
            errors.append("{} must start with at least {} replicas".format(edge_name, minimum_replicas))
        if _mounts_data(edge):
            errors.append("{} must not mount the ClickHouse data PVC".format(edge_name))
        for container in _containers(edge):
            refs = [item.get("configMapRef", {}).get("name") for item in container.get("envFrom") or []]
            if "tracescope-config" in refs:
                errors.append("{} must not import the storage ClickHouse config".format(edge_name))
            env = _container_env(container)
            for env_name in env:
                if env_name.startswith("OTEL_CLICKHOUSE_"):
                    errors.append("{} must not receive {}".format(edge_name, env_name))

    edge_data = (configmaps.get("tracescope-edge-config") or {}).get("data") or {}
    if edge_data.get("OTEL_STORAGE_OWNER_URL") != "http://tracescope-api:30102":
        errors.append("tracescope-edge-config must route OTEL_STORAGE_OWNER_URL to tracescope-api:30102")
    if any(str(key).startswith("OTEL_CLICKHOUSE_") for key in edge_data):
        errors.append("tracescope-edge-config must not contain ClickHouse credentials")

    # ---- UI workload (optional standalone; default merged into tracescope-storage) ----
    ui = workloads.get("tracescope-ui")
    if ui:
        if ui.get("kind") != "Deployment":
            errors.append("tracescope-ui must be a Deployment")
        if int(ui.get("spec", {}).get("replicas", 0)) < 2:
            errors.append("tracescope-ui must start with at least 2 replicas")
        if _mounts_data(ui):
            errors.append("tracescope-ui must not mount the data PVC")
        for c in _containers(ui):
            for env_name in _container_env(c):
                if env_name.startswith("OTEL_CLICKHOUSE_") or env_name in ("OTEL_DB_PATH", "OTEL_RUN_MIGRATIONS"):
                    errors.append("tracescope-ui must have no DB access; found env {}".format(env_name))

    # ---- PVC -------------------------------------------------------------
    pvcs = [d for d in documents if d.get("kind") == "PersistentVolumeClaim"]
    if not pvcs:
        errors.append("no PersistentVolumeClaim for the ClickHouse data volume")
    for pvc in pvcs:
        pvc_name = pvc.get("metadata", {}).get("name")
        if pvc_name == "tracescope-data":
            errors.append("PVC/tracescope-data: legacy SQLite PVC must not exist")
        modes = pvc.get("spec", {}).get("accessModes") or []
        if modes != ["ReadWriteOnce"]:
            errors.append(
                "PVC/{}: accessModes must be exactly ['ReadWriteOnce'] (block storage is required)".format(
                    pvc_name
                )
            )

    ingresses = [d for d in documents if d.get("kind") == "Ingress"]
    for ingress in ingresses:
        annotations = ingress.get("metadata", {}).get("annotations") or {}
        if "location ^~ /internal/ { return 404; }" not in annotations.get(
            "nginx.ingress.kubernetes.io/server-snippet", ""
        ):
            errors.append("Ingress must explicitly deny the /internal/ prefix")
    if not any(pvc.get("metadata", {}).get("name") == DATA_CLAIM for pvc in pvcs):
        errors.append("no PersistentVolumeClaim for {}".format(DATA_CLAIM))

    # ---- Service <-> Deployment selector wiring --------------------------
    for name, doc in services.items():
        where = doc.get("__file__", name)
        spec = doc.get("spec", {}) or {}
        selector = spec.get("selector") or {}
        if not selector:
            errors.append("Service/{}: missing spec.selector".format(name))
        else:
            matched = False
            for workload in workloads.values():
                pod_labels = ((workload.get("spec", {}) or {}).get("template", {}) or {}).get("metadata", {}).get("labels", {}) or {}
                if all(pod_labels.get(k) == v for k, v in selector.items()):
                    matched = True
                    break
            if not matched:
                errors.append("Service/{}: selector {} matches no workload pod template".format(name, selector))
        ports = spec.get("ports") or []
        if not ports:
            errors.append("Service/{}: no ports".format(name))
        for p in ports:
            if p.get("targetPort") is None:
                errors.append("Service/{}: port {} missing targetPort".format(name, p.get("port")))
        if spec.get("type") in ("LoadBalancer", "NodePort"):
            errors.append(
                "Service/{}: type {} bypasses the single Ingress entrypoint; use ClusterIP".format(
                    name, spec.get("type")
                )
            )
        del where

    # ---- Ingress ---------------------------------------------------------
    ingresses = [d for d in documents if d.get("kind") == "Ingress"]
    if not ingresses:
        errors.append("no Ingress defined for the single public entrypoint")
    for ing in ingresses:
        where = ing.get("__file__", "ingress")
        annotations = (ing.get("metadata", {}) or {}).get("annotations") or {}
        if not annotations.get("nginx.ingress.kubernetes.io/proxy-body-size"):
            errors.append("{}: missing proxy-body-size annotation (ingest bodies up to 10 MiB)".format(where))
        routed: set[str] = set()
        for rule in (ing.get("spec", {}) or {}).get("rules") or []:
            for path in ((rule.get("http") or {}).get("paths") or []):
                backend = ((path.get("backend") or {}).get("service") or {})
                svc_name = backend.get("name")
                port = (backend.get("port") or {}).get("number")
                if svc_name and port:
                    routed.add(svc_name)
                    expected = SPA_SERVICE_PORTS.get(svc_name)
                    if expected is not None and port != expected:
                        errors.append(
                            "{}: service {} routed on port {} but Service defines {}".format(
                                where, svc_name, port, expected
                            )
                        )
                if svc_name and svc_name not in services:
                    errors.append("{}: routes to unknown Service '{}'".format(where, svc_name))
        missing = set(SPA_SERVICE_PORTS) - routed
        if missing:
            errors.append("{}: no route to {}".format(where, ", ".join(sorted(missing))))

    # ---- Horizontal scaling must target only stateless edge workloads ----
    hpas = [d for d in documents if d.get("kind") == "HorizontalPodAutoscaler"]
    for hpa in hpas:
        target = (hpa.get("spec", {}).get("scaleTargetRef") or {}).get("name")
        if target not in ("tracescope-ingest", "tracescope-agent-stats"):
            errors.append("HPA/{} targets non-edge workload {!r}".format(hpa.get("metadata", {}).get("name"), target))
        elif _mounts_data(workloads.get(str(target), {})):
            errors.append("HPA/{} targets a SQLite-mounting workload".format(hpa.get("metadata", {}).get("name")))

    # ---- kustomization ---------------------------------------------------
    kustomization = directory / "kustomization.yaml"
    if kustomization.is_file():
        kdoc = (yaml.safe_load(kustomization.read_text(encoding="utf-8")) or {})
        listed = [str(resource) for resource in (kdoc.get("resources") or [])]
        for resource in listed:
            if not (directory / resource).is_file():
                errors.append("kustomization.yaml references missing file '{}'".format(resource))
        # Every manifest must be referenced, otherwise `kubectl apply -k` would
        # silently skip a workload the docs claim is deployed.
        listed_names = {Path(resource).name for resource in listed}
        for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
            if path.name == "kustomization.yaml":
                continue  # kustomize config, not a resource
            if ".example." in path.name:
                continue  # documentation-only secret template
            if path.name not in listed_names:
                errors.append(
                    "kustomization.yaml does not reference manifest '{}'".format(path.name)
                )

    return errors, documents


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent
    if yaml is None:
        print(json.dumps({"ok": False, "error": "PyYAML is not installed"}, indent=2))
        return 2
    errors, documents = validate(directory)
    kinds: dict[str, int] = {}
    for doc in documents:
        kinds[doc.get("kind", "?")] = kinds.get(doc.get("kind", "?"), 0) + 1
    print(json.dumps(
        {
            "ok": not errors,
            "directory": str(directory),
            "documents": len(documents),
            "kinds": kinds,
            "errors": errors,
        },
        indent=2,
    ))
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))

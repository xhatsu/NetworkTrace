from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_TABLE_READ = re.compile(r"\b(?:FROM|JOIN)\s+`?traces`?\b", re.IGNORECASE)


def _method_sources(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node.name] = ast.get_source_segment(source, node) or ""
    return result


def test_api_modules_do_not_query_raw_trace_table():
    api_dir = ROOT / "backend" / "app" / "api"
    offenders = []
    for path in sorted(api_dir.glob("*.py")):
        if RAW_TABLE_READ.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], "API modules must query read models: " + ", ".join(offenders)


def test_topology_interactive_methods_use_rollups_only():
    path = ROOT / "backend" / "app" / "repositories" / "interactive_topology_repository.py"
    methods = _method_sources(path)
    allowed_worker_methods = {"materialize_slice", "_materialize_queries"}
    offenders = [
        name for name, source in methods.items()
        if name not in allowed_worker_methods and RAW_TABLE_READ.search(source)
    ]
    assert offenders == [], "Interactive topology methods must use rollups: " + ", ".join(offenders)


def test_user_and_investigation_read_repositories_use_rollups_only():
    repository_paths = [
        ROOT / "backend" / "app" / "repositories" / "user_repository.py",
        ROOT / "backend" / "app" / "repositories" / "investigation_evidence_repository.py",
    ]
    offenders = [
        str(path.relative_to(ROOT))
        for path in repository_paths
        if RAW_TABLE_READ.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], "User-facing reads must use aggregated models: " + ", ".join(offenders)


def test_prometheus_scrape_uses_worker_snapshot_without_raw_fallback():
    methods = _method_sources(ROOT / "backend" / "app" / "services" / "prometheus_metrics.py")
    snapshot_reader = methods["get_worker_metrics_snapshot"]
    assert not RAW_TABLE_READ.search(snapshot_reader)
    assert "compute_domain_metrics_snapshot(" not in snapshot_reader


def test_trace_explorer_raw_access_is_limited_to_explicit_routes():
    path = ROOT / "backend" / "app" / "repositories" / "trace_repository.py"
    source = path.read_text(encoding="utf-8")
    methods = _method_sources(path)
    raw_methods = {name for name, source in methods.items() if RAW_TABLE_READ.search(source)}
    allowed = {"insert_traces", "get_trace", "list_traces"}
    assert raw_methods <= allowed, "Raw table access escaped ingestion/Trace Explorer: " + ", ".join(sorted(raw_methods - allowed))
    assert "temporary exception" in source

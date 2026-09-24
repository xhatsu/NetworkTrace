"""Role-aware FastAPI application factory for TraceScope / OtelTrace.

Historically the platform was a single monolith served by ``backend.main:app``
(FastAPI + built React SPA + ingest + analytics + agent telemetry). The ``all``
role preserves that public surface while adding authenticated internal storage
operations used by Kubernetes edge workloads.

Two additional roles isolate independently deployable Kubernetes workloads:

* ``ingest``      -> ``backend.ingest_main:app``       traffic-log ingestion
* ``agent-stats`` -> ``backend.agent_stats_main:app``  agent lifecycle / health

Role isolation is enforced at *router mount* and *lifespan* time:

* the ingest role never mounts the analytics read/write routers or the SPA;
* role-isolated deployments may call the authenticated storage owner over HTTP,
  while direct ClickHouse mode remains available for stateless edge workloads;
* only the ``all`` role serves the compiled SPA and the legacy dashboard APIs.

See ``deploy/k8s/README.md`` for the storage / single-writer contract that these
roles are deployed under.
"""
from __future__ import annotations

import json
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone as dt_timezone, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from backend.config import settings
from backend.models import AnomalyPatch, Page, QueryFilters, epoch_ms
from backend.repository import StorageRepository

from backend.app.api.overview import router as overview_router
from backend.app.api.services import router as services_router
from backend.app.api.principals import router as principals_router
from backend.app.api.topology import router as topology_router
from backend.app.api.anomalies import router as anomalies_router
from backend.app.api.traces import router as traces_router
from backend.app.api.blast_radius import router as blast_radius_router
from backend.app.api.ingest import (
    legacy_router as legacy_ingest_router,
    otlp_router,
    router as ingest_router,
)
from backend.app.api.users import router as users_router
from backend.app.api.reference_compat import router as reference_compat_router
from backend.app.api.agent_stats import router as agent_stats_router
from backend.app.api.internal_storage import router as internal_storage_router
from backend.app.api.investigations import router as investigations_router
from backend.app.api.changes import router as changes_router
from backend.app.services.ingest_writer import ingest_writer
from backend.app.services.investigation import InvestigationRunner
from backend.app.services.storage_owner_client import StorageOwnerError, storage_owner_client
from backend.app.services.prometheus_metrics import PrometheusMiddleware, prometheus_registry


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLE_ALL = "all"
ROLE_INGEST = "ingest"
ROLE_AGENT_STATS = "agent-stats"
VALID_ROLES = (ROLE_ALL, ROLE_INGEST, ROLE_AGENT_STATS)

# The all role owns the in-process writer. An ingest role uses it only when the
# optional internal-storage boundary is absent, keeping standalone launches compatible.

# Analytics / read-mostly routers (dashboard, topology, traces, users, ...).
_ANALYTICS_ROUTERS = (
    overview_router,
    services_router,
    principals_router,
    topology_router,
    anomalies_router,
    traces_router,
    blast_radius_router,
    users_router,
    changes_router,
    reference_compat_router,
)

# Traffic-log ingestion routers: /api/v1/ingest, /api/v1/ingest/traces,
# /api/ingest (+ apm aliases) and the canonical OTLP /v1/{traces,metrics,logs}.
_INGEST_ROUTERS = (ingest_router, legacy_ingest_router, otlp_router)

# Agent lifecycle / health routers: /api/agent/stats*.
_AGENT_STATS_ROUTERS = (agent_stats_router,)


def create_app(role: str = ROLE_ALL) -> FastAPI:
    """Build a FastAPI app for ``role``.

    ``role`` must be one of :data:`VALID_ROLES`.  ``all`` reproduces the
    historical monolith exactly; the other roles expose only their own surface.
    """
    if role not in VALID_ROLES:
        raise ValueError(
            "Unknown TraceScope role {!r}; expected one of {}".format(role, VALID_ROLES)
        )

    repo = StorageRepository()
    investigation_runner = InvestigationRunner()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # One designated role runs migrations so horizontally scaled pods never race schema changes.
        if settings.run_migrations:
            repo.migrate()
        owns_writer = role == ROLE_ALL or (
            role == ROLE_INGEST and not storage_owner_client.enabled
        )
        if storage_owner_client.enabled:
            await storage_owner_client.start()
        if owns_writer:
            ingest_writer.start()
        if role == ROLE_ALL and settings.llm_investigation_enabled:
            try:
                await investigation_runner.start()
                _app.state.investigation_start_error = None
            except Exception as exc:
                # Investigation availability must never take ingestion or the
                # deterministic analytics application down.
                _app.state.investigation_start_error = str(getattr(exc, "code", "owner_unavailable"))
        try:
            yield
        finally:
            if role == ROLE_ALL:
                await investigation_runner.shutdown()
            if owns_writer:
                ingest_writer.shutdown()
            if storage_owner_client.enabled:
                await storage_owner_client.shutdown()

    app = FastAPI(
        title="TraceScope API",
        version="0.2.5",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(PrometheusMiddleware, registry=prometheus_registry)

    @app.middleware("http")
    async def authenticate_public_mutations(request: Request, call_next):
        """Apply one mutation policy to every public write route.

        Internal storage routes answer 404 to any request that fails the
        internal-token check: the cluster ingress disables server-snippet
        annotations, so edge-level /internal/ isolation must be reproduced at
        the application boundary (publicly indistinguishable from a missing
        route).
        """
        path = request.url.path
        if path.startswith("/internal/"):
            expected_token = settings.internal_api_token
            if not expected_token:
                return JSONResponse(status_code=503, content={"detail": "Internal storage API is disabled"})
            supplied_token = request.headers.get("x-tracescope-internal-token")
            if supplied_token is None or not hmac.compare_digest(supplied_token, expected_token):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not path.startswith("/internal/"):
            expected = settings.api_key
            supplied = request.headers.get("x-api-key")
            if expected and (supplied is None or not hmac.compare_digest(supplied, expected)):
                return JSONResponse(status_code=401, content={"detail": "Valid X-API-Key required"})
        return await call_next(request)
    # Exposed for tests / diagnostics: which workload surface this app serves.
    app.state.tracescope_role = role
    app.state.investigation_runner = investigation_runner
    app.state.investigation_start_error = None

    if role == ROLE_ALL:
        for router in _ANALYTICS_ROUTERS:
            app.include_router(router)
        for router in _INGEST_ROUTERS:
            app.include_router(router)
        for router in _AGENT_STATS_ROUTERS:
            app.include_router(router)
        app.include_router(internal_storage_router)
        app.include_router(investigations_router)
    elif role == ROLE_INGEST:
        for router in _INGEST_ROUTERS:
            app.include_router(router)
    else:  # ROLE_AGENT_STATS
        for router in _AGENT_STATS_ROUTERS:
            app.include_router(router)

    @app.get("/api/v1/health")
    async def health():
        return {
            "status": "ok",
            "demo_mode": settings.demo_mode,
            "service_role": role,
            "storage_backend": settings.storage_backend,
            "trace_storage_backend": settings.trace_storage_backend,
            "elasticsearch_configured": bool(settings.elasticsearch_url),
        }

    @app.get("/livez", include_in_schema=False)
    async def livez():
        return {"status": "alive", "service_role": role}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        if role in (ROLE_INGEST, ROLE_AGENT_STATS) and storage_owner_client.enabled:
            if not await storage_owner_client.ready():
                return JSONResponse(status_code=503, content={"status": "not-ready"})
            return {"status": "ready", "service_role": role}
        try:
            def check_store() -> None:
                with repo.connect() as db:
                    db.execute("SELECT 1").fetchone()
            await run_in_threadpool(check_store)
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not-ready"})
        if role in (ROLE_ALL, ROLE_INGEST) and not storage_owner_client.enabled:
            if not ingest_writer.snapshot()["writer_alive"]:
                return JSONResponse(status_code=503, content={"status": "not-ready"})
        return {"status": "ready", "service_role": role}

    if role == ROLE_ALL:
        _register_dashboard_routes(app, repo)
    if role in (ROLE_ALL, ROLE_INGEST):
        _register_ingestion_status_route(app, repo)
    if role != ROLE_ALL:
        @app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
        async def metrics_endpoint():
            return PlainTextResponse(
                prometheus_registry.render(repo=repo, role=role),
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

    @app.exception_handler(Exception)
    async def database_error(_request, exc):
        import clickhouse_connect.driver.exceptions as ch_exc
        if isinstance(exc, (ch_exc.ClickHouseError,)):
            return JSONResponse(
                status_code=503,
                content={"detail": "Analytics store is temporarily unavailable"},
            )
        raise exc

    @app.exception_handler(StorageOwnerError)
    async def storage_owner_error(_request, exc: StorageOwnerError):
        headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )

    if role == ROLE_ALL:
        _mount_spa(app)

    return app


# --------------------------------------------------------------------------
# Shared query-filter dependency (module level so FastAPI's get_type_hints can
# resolve the ``Filters`` annotation from the module globals, exactly as the
# original ``backend.main`` did).
def _parse_time_param(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=dt_timezone.utc)
    if isinstance(val, (int, float)):
        ts = val / 1000.0 if val > 10_000_000_000 else float(val)
        return datetime.fromtimestamp(ts, tz=dt_timezone.utc)
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return None
        try:
            num = float(val_str)
            ts = num / 1000.0 if num > 10_000_000_000 else num
            return datetime.fromtimestamp(ts, tz=dt_timezone.utc)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=dt_timezone.utc)
        except Exception:
            pass
    return None


async def filters_model(
    start: Any = Query(None),
    end: Any = Query(None),
    from_time: Any = Query(None, alias="from"),
    to_time: Any = Query(None, alias="to"),
    timezone: str = "UTC",
    environment: str | None = None,
    group: str | None = None,
    module: str | None = None,
    service: str | None = None,
    operation: str | None = None,
    account: str | None = None,
    comparison: str = "previous",
) -> QueryFilters:
    now_dt = datetime.now(dt_timezone.utc)
    s_dt = _parse_time_param(start) or _parse_time_param(from_time)
    e_dt = _parse_time_param(end) or _parse_time_param(to_time)

    if e_dt is None:
        e_dt = now_dt + timedelta(minutes=1)
    if s_dt is None:
        s_dt = e_dt - timedelta(hours=3)
    if e_dt <= s_dt:
        e_dt = s_dt + timedelta(hours=1)
    if (e_dt - s_dt).total_seconds() > 31 * 86400:
        s_dt = e_dt - timedelta(days=31)

    tz_str = timezone if isinstance(timezone, str) and timezone.strip() else "UTC"
    comp_val = comparison if comparison in ("previous", "week", "none") else "previous"

    return QueryFilters(
        start=s_dt,
        end=e_dt,
        timezone=tz_str,
        environment=environment,
        group=group,
        module=module,
        service=service,
        operation=operation,
        account=account,
        comparison=comp_val,
    )


Filters = Annotated[QueryFilters, Depends(filters_model)]


def filter_dict(f: QueryFilters) -> dict[str, str | None]:
    return {
        k: getattr(f, k)
        for k in (
            "environment",
            "group",
            "module",
            "service",
            "operation",
            "account",
            "comparison",
        )
    }


# --------------------------------------------------------------------------
# Legacy dashboard / read routes (only the ``all`` monolith served these)
# --------------------------------------------------------------------------
def _register_dashboard_routes(app: FastAPI, repo: StorageRepository) -> None:
    @app.get("/api/v1/dashboard/summary")
    async def dashboard_summary(f: Filters):
        return repo.dashboard_summary(f.start_ms, f.end_ms, filter_dict(f))

    @app.get("/api/v1/dashboard/series")
    async def dashboard_series(f: Filters):
        return {
            "items": repo.dashboard_series(f.start_ms, f.end_ms, filter_dict(f)),
            "bucket_seconds": 60,
            "units": {"rate": "observed requests/s", "latency": "ms"},
        }

    @app.get("/api/v1/dashboard/rankings")
    async def rankings(f: Filters):
        return repo.rankings(f.start_ms, f.end_ms, filter_dict(f))

    @app.get("/api/v1/dashboard/heatmap")
    async def heatmap(f: Filters):
        with repo.connect() as db:
            mb_count_row = db.execute("SELECT count() FROM metric_buckets").fetchone()
            use_mb = bool(mb_count_row and mb_count_row[0] > 0)
            if use_mb:
                start_sec = int(f.start_ms / 1000)
                end_sec = int(f.end_ms / 1000)
                rows = [
                    dict(r)
                    for r in db.execute(
                        "SELECT target_service AS service_name, (intDiv(bucket_start, 300) * 300 * 1000) AS bucket_ms, "
                        "SUM(request_count) AS samples, "
                        "ROUND(SUM(latency_sum) / NULLIF(SUM(request_count), 0), 1) AS avg_ms, "
                        "ROUND(SUM(error_count) * 1.0 / NULLIF(SUM(request_count), 0), 4) AS failure_rate "
                        "FROM metric_buckets "
                        "WHERE bucket_size = 60 AND bucket_start >= ? AND bucket_start < ? "
                        "GROUP BY target_service, bucket_ms ORDER BY samples DESC LIMIT 1200",
                        (start_sec, end_sec),
                    ).fetchall()
                ]
            else:
                where, args = repo._event_where(f.start_ms, f.end_ms, filter_dict(f))
                rows = [
                    dict(r)
                    for r in db.execute(
                        f"SELECT service_name,(timestamp_ms/300000)*300000 bucket_ms,COUNT(*) samples,"
                        f"ROUND(AVG(duration_us)/1000.0,1) avg_ms,SUM(status_code>=500)*1.0/COUNT(*) failure_rate "
                        f"FROM events WHERE {where} AND span_kind='server' "
                        f"GROUP BY service_name,bucket_ms ORDER BY samples DESC LIMIT 1200",
                        args,
                    ).fetchall()
                ]
        return {
            "items": rows,
            "metric": "average latency (ms)",
            "note": "Heatmap uses average latency for compact comparison; operation tables retain p95/p99.",
        }

    @app.get("/api/v1/accounts")
    async def accounts(q: str | None = None, limit: int = Query(100, ge=1, le=500)):
        with repo.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM accounts WHERE (? IS NULL OR username LIKE ?) "
                    "ORDER BY last_seen_ms DESC LIMIT ?",
                    (q, f"%{q}%" if q else None, limit),
                )
            ]
        return {
            "items": rows,
            "identity_caveat": "Presented request identity; not proof of a human or caller service.",
        }

    @app.get("/api/v1/accounts/{username}")
    async def account_detail(username: str, f: Filters):
        result = repo.account_detail(username, f.start_ms, f.end_ms)
        if not result:
            raise HTTPException(404, "Account not found")
        return result

    @app.get("/api/v1/events")
    async def events(
        f: Filters,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=1_000_000),
    ):
        where, args = repo._event_where(f.start_ms, f.end_ms, filter_dict(f))
        safe_columns = (
            "timestamp_ms,ingested_ms,trace_id,transaction_id,parent_id,service_name,environment,"
            "node_name,service_group,service_module,operation,duration_us,sampled,outcome,http_method,"
            "status_code,account_username,account_namespace,span_kind,event_type,peer_service,client_ip,"
            "source_ip,attributes_json"
        )
        with repo.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    f"SELECT {safe_columns} FROM events WHERE {where} "
                    f"ORDER BY timestamp_ms DESC LIMIT ? OFFSET ?",
                    [*args, limit, offset],
                )
            ]
        return {"items": rows, "limit": limit, "offset": offset, "partial": len(rows) == limit}


def _register_ingestion_status_route(app: FastAPI, repo: StorageRepository) -> None:
    @app.get("/api/v1/ingestion/status")
    async def ingestion_status():
        if storage_owner_client.enabled:
            return await storage_owner_client.ingestion_status()
        with repo.connect() as db:
            count, min_ts, max_ts = db.execute(
                "SELECT COALESCE(SUM(request_count),0),MIN(bucket_start)*1000,MAX(bucket_start+bucket_size)*1000 FROM metric_buckets FINAL WHERE bucket_size=300"
            ).fetchone()
            jobs = [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY started_at_ms DESC")]
        return {
            "events": count,
            "traces": count,
            "earliest_event_ms": min_ts,
            "latest_event_ms": max_ts,
            "latest_ingested_ms": None,
            "jobs": jobs,
            "demo_mode": settings.demo_mode,
            "sampling_coverage": "unknown",
            "ingest_writer": ingest_writer.snapshot(),
        }


def _mount_spa(app: FastAPI) -> None:
    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        resolved_dist = frontend_dist.resolve()
        target_file = (resolved_dist / full_path).resolve()
        try:
            target_file.relative_to(resolved_dist)
        except ValueError:
            raise HTTPException(404, "Not Found") from None
        if full_path and target_file.is_file():
            return FileResponse(str(target_file))
        index_file = frontend_dist / "index.html"
        if index_file.is_file():
            return FileResponse(str(index_file))
        return {"message": "TraceScope API is running"}

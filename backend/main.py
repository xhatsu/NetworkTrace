from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models import AnomalyPatch, Page, QueryFilters, epoch_ms
from .repository import SQLiteRepository

from backend.app.api.overview import router as overview_router
from backend.app.api.services import router as services_router
from backend.app.api.principals import router as principals_router
from backend.app.api.topology import router as topology_router
from backend.app.api.anomalies import router as anomalies_router
from backend.app.api.traces import router as traces_router
from backend.app.api.blast_radius import router as blast_radius_router
from backend.app.api.ingest import legacy_router as legacy_ingest_router, router as ingest_router, otlp_router
from backend.app.api.users import router as users_router
from backend.app.api.reference_compat import router as reference_compat_router


repo=SQLiteRepository()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    repo.migrate()
    yield


app=FastAPI(title="TraceScope API",version="0.2.0",docs_url="/api/docs",redoc_url=None,lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=False,allow_methods=["GET","POST","PATCH","OPTIONS"],allow_headers=["*"])

app.include_router(overview_router)
app.include_router(services_router)
app.include_router(principals_router)
app.include_router(topology_router)
app.include_router(anomalies_router)
app.include_router(traces_router)
app.include_router(blast_radius_router)
app.include_router(ingest_router)
app.include_router(legacy_ingest_router)
app.include_router(otlp_router)
app.include_router(users_router)
app.include_router(reference_compat_router)

async def filters_model(
    start: datetime, end: datetime, timezone: str="UTC", environment: str|None=None,
    group: str|None=None, module: str|None=None, service: str|None=None,
    operation: str|None=None, account: str|None=None, comparison: str="previous"
) -> QueryFilters:
    try: return QueryFilters(start=start,end=end,timezone=timezone,environment=environment,group=group,module=module,service=service,operation=operation,account=account,comparison=comparison)
    except Exception as exc: raise HTTPException(422,"Invalid filter or time range") from None


Filters=Annotated[QueryFilters,Depends(filters_model)]


def filter_dict(f: QueryFilters) -> dict[str,str|None]:
    return {k:getattr(f,k) for k in ("environment","group","module","service","operation","account","comparison")}


@app.get("/api/v1/health")
async def health(): return {"status":"ok","demo_mode":settings.demo_mode}


@app.get("/api/v1/dashboard/summary")
async def dashboard_summary(f: Filters): return repo.dashboard_summary(f.start_ms,f.end_ms,filter_dict(f))


@app.get("/api/v1/dashboard/series")
async def dashboard_series(f: Filters): return {"items":repo.dashboard_series(f.start_ms,f.end_ms,filter_dict(f)),"bucket_seconds":60,"units":{"rate":"observed requests/s","latency":"ms"}}


@app.get("/api/v1/dashboard/rankings")
async def rankings(f: Filters): return repo.rankings(f.start_ms,f.end_ms,filter_dict(f))


@app.get("/api/v1/dashboard/heatmap")
async def heatmap(f: Filters):
    where,args=repo._event_where(f.start_ms,f.end_ms,filter_dict(f))
    with repo.connect() as db:
        rows=[dict(r) for r in db.execute(f"SELECT service_name,(timestamp_ms/300000)*300000 bucket_ms,COUNT(*) samples,ROUND(AVG(duration_us)/1000.0,1) avg_ms,SUM(status_code>=500)*1.0/COUNT(*) failure_rate FROM events WHERE {where} AND span_kind='server' GROUP BY service_name,bucket_ms ORDER BY samples DESC LIMIT 1200",args)]
    return {"items":rows,"metric":"average latency (ms)","note":"Heatmap uses average latency for compact comparison; operation tables retain p95/p99."}


@app.get("/api/v1/accounts")
async def accounts(q: str|None=None,limit: int=Query(100,ge=1,le=500)):
    with repo.connect() as db: rows=[dict(r) for r in db.execute("SELECT * FROM accounts WHERE (? IS NULL OR username LIKE ?) ORDER BY last_seen_ms DESC LIMIT ?",(q,f"%{q}%" if q else None,limit))]
    return {"items":rows,"identity_caveat":"Presented request identity; not proof of a human or caller service."}


@app.get("/api/v1/accounts/{username}")
async def account_detail(username: str,f: Filters):
    result=repo.account_detail(username,f.start_ms,f.end_ms)
    if not result: raise HTTPException(404,"Account not found")
    return result


@app.get("/api/v1/events")
async def events(f: Filters,limit: int=Query(50,ge=1,le=200),offset: int=Query(0,ge=0,le=1_000_000)):
    where,args=repo._event_where(f.start_ms,f.end_ms,filter_dict(f))
    safe_columns="timestamp_ms,ingested_ms,trace_id,transaction_id,parent_id,service_name,environment,node_name,service_group,service_module,operation,duration_us,sampled,outcome,http_method,status_code,account_username,account_namespace,span_kind,event_type,peer_service,client_ip,source_ip,attributes_json"
    with repo.connect() as db:
        rows=[dict(r) for r in db.execute(f"SELECT {safe_columns} FROM events WHERE {where} ORDER BY timestamp_ms DESC LIMIT ? OFFSET ?",[*args,limit,offset])]
    return {"items":rows,"limit":limit,"offset":offset,"partial":len(rows)==limit}


@app.get("/api/v1/ingestion/status")
async def ingestion_status():
    with repo.connect() as db:
        count,min_ts,max_ts=db.execute("SELECT COUNT(*),MIN(timestamp_ms),MAX(timestamp_ms) FROM traces").fetchone()
        jobs=[dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY started_at_ms DESC")]
    return {"events":count,"traces":count,"earliest_event_ms":min_ts,"latest_event_ms":max_ts,"latest_ingested_ms":None,"jobs":jobs,"demo_mode":settings.demo_mode,"sampling_coverage":"unknown"}


@app.exception_handler(sqlite3.Error)
async def database_error(_request, _exc):
    return JSONResponse(status_code=503,content={"detail":"Analytics store is temporarily unavailable"})


_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (_frontend_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    target_file = _frontend_dist / full_path
    if full_path and target_file.is_file():
        return FileResponse(str(target_file))
    index_file = _frontend_dist / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return {"message": "TraceScope API is running"}

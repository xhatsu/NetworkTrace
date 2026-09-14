# syntax=docker/dockerfile:1
#
# TraceScope / OtelTrace — one Dockerfile, four production build targets.
# Build from the repository root so the build context contains backend/,
# frontend/ and docs/:
#
#   docker build -f deploy/docker/Dockerfile --target ui          -t tracescope-ui:latest .
#   docker build -f deploy/docker/Dockerfile --target api         -t tracescope-api:latest .
#   docker build -f deploy/docker/Dockerfile --target ingest      -t tracescope-ingest:latest .
#   docker build -f deploy/docker/Dockerfile --target agent-stats -t tracescope-agent-stats:latest .
#   docker build -f deploy/docker/Dockerfile --target worker      -t tracescope-worker:latest .
#
# The `ui` target is intentionally stateless: cached frontend assets can scale
# independently because all mutable telemetry lives in ClickHouse.
# The `api` target serves analytics and administration APIs; `ingest`,
# `agent-stats`, and `worker` omit UI responsibilities to keep their roles narrow.

# ---------------------------------------------------------------------------
# Stage 1 — build the React/TypeScript SPA
# ---------------------------------------------------------------------------
FROM node:22-alpine AS ui-builder
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Target: ui — stateless nginx serving compiled frontend without storage credentials
# ---------------------------------------------------------------------------
FROM nginx:alpine AS ui
COPY --from=ui-builder /src/frontend/dist /usr/share/nginx/html
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:80/ || exit 1
CMD ["nginx", "-g", "daemon off;"]

# ---------------------------------------------------------------------------
# Stage 2 — shared Python runtime; role-specific entrypoints share one schema contract
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS backend-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OTEL_DATA_DIR=/data \
    OTEL_CLICKHOUSE_HOST=127.0.0.1 \
    OTEL_CLICKHOUSE_PORT=8123 \
    OTEL_CLICKHOUSE_DATABASE=tracescope \
    OTEL_CLICKHOUSE_USER=default \
    OTEL_RUN_MIGRATIONS=false

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin tracescope \
    && mkdir -p /data \
    && chown -R tracescope:tracescope /data

COPY backend ./backend
COPY docs ./docs
RUN chown -R tracescope:tracescope /app

USER 10001
EXPOSE 8000
VOLUME ["/data"]

# ---------------------------------------------------------------------------
# Target: api — UI + analytics + all legacy routes. Runs migrations.
# ---------------------------------------------------------------------------
FROM backend-base AS api
COPY --from=ui-builder /src/frontend/dist ./frontend/dist
ENV OTEL_RUN_MIGRATIONS=true
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Target: ingest — stateless parsing/normalization edge; no SQLite mount.
# ---------------------------------------------------------------------------
FROM backend-base AS ingest
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"]
CMD ["uvicorn", "backend.ingest_main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Target: agent-stats — oldkernel agent lifecycle/health only.
# ---------------------------------------------------------------------------
FROM backend-base AS agent-stats
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"]
CMD ["uvicorn", "backend.agent_stats_main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# Target: worker — analytics rollup/detector loop (single instance).
# ---------------------------------------------------------------------------
FROM backend-base AS worker
CMD ["python", "-m", "backend.worker", "--interval", "60"]

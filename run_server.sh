#!/bin/sh
set -e

ACTION="${1:-start}"
PROJECT_DIR="/home/ubuntu/Viettel/OtelTrace"
if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  . "$PROJECT_DIR/.env"
  set +a
fi
DEFAULT_PYTHON="python3"
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  DEFAULT_PYTHON="$PROJECT_DIR/.venv/bin/python"
fi
PYTHON_BIN="${OTEL_PYTHON:-$DEFAULT_PYTHON}"
SERVER_HOST="${OTEL_HOST:-0.0.0.0}"
SERVER_PORT="${OTEL_PORT:-31102}"
ELASTICSEARCH_NODEPORT="${OTEL_ES_PORT:-32073}"
ES_URL="${OTEL_ES_URL:-http://127.0.0.1:$ELASTICSEARCH_NODEPORT}"
ES_INDEX="${OTEL_ES_INDEX:-apm-*,traces-apm*}"
# The active hub keeps application APM traces in Elasticsearch and analytics in ClickHouse.
STORAGE_BACKEND="${OTEL_STORAGE_BACKEND:-clickhouse}"
TRACE_STORAGE_BACKEND="${OTEL_TRACE_STORAGE_BACKEND:-elasticsearch}"

ES_RETENTION_DAYS="${OTEL_ES_RETENTION_DAYS:-2}"

case "$ACTION" in
  start|restart)
    tmux kill-session -t tracescope-30102 2>/dev/null || true
    tmux kill-session -t "tracescope-$SERVER_PORT" 2>/dev/null || true
    tmux kill-session -t tracescope-worker 2>/dev/null || true
    tmux start-server 2>/dev/null || true
    tmux new-session -d -s "tracescope-$SERVER_PORT" "cd $PROJECT_DIR && if [ -f .env ]; then set -a; . ./.env; set +a; fi; OTEL_STORAGE_BACKEND=$STORAGE_BACKEND OTEL_TRACE_STORAGE_BACKEND=$TRACE_STORAGE_BACKEND OTEL_ES_URL=$ES_URL OTEL_ES_INDEX=$ES_INDEX OTEL_ES_RETENTION_DAYS=$ES_RETENTION_DAYS exec $PYTHON_BIN -m uvicorn backend.main:app --host $SERVER_HOST --port $SERVER_PORT"
    if [ "${OTEL_HOST_WORKER_ENABLED:-true}" = "true" ]; then
      tmux new-session -d -s tracescope-worker "cd $PROJECT_DIR && if [ -f .env ]; then set -a; . ./.env; set +a; fi; OTEL_STORAGE_BACKEND=$STORAGE_BACKEND OTEL_TRACE_STORAGE_BACKEND=$TRACE_STORAGE_BACKEND OTEL_ES_URL=$ES_URL OTEL_ES_INDEX=$ES_INDEX OTEL_ES_RETENTION_DAYS=$ES_RETENTION_DAYS exec $PYTHON_BIN -m backend.worker --interval 60"
    else
      echo "Host worker disabled (OTEL_HOST_WORKER_ENABLED=false); not starting tracescope-worker."
    fi
    if [ -f "$PROJECT_DIR/bootstrap/start.sh" ]; then
      sh "$PROJECT_DIR/bootstrap/start.sh"
    fi
    echo "TraceScope dashboard started on http://$SERVER_HOST:$SERVER_PORT (wired to ES NodePort $ELASTICSEARCH_NODEPORT)"
    ;;
  stop)
    tmux kill-session -t tracescope-30102 2>/dev/null || true
    tmux kill-session -t "tracescope-$SERVER_PORT" 2>/dev/null || true
    tmux kill-session -t tracescope-worker 2>/dev/null || true
    if [ -f "$PROJECT_DIR/bootstrap/stop.sh" ]; then
      sh "$PROJECT_DIR/bootstrap/stop.sh"
    fi
    echo "TraceScope dashboard stopped."
    ;;
  status)
    tmux ls 2>/dev/null | grep -E 'tracescope' || echo "No active tracescope sessions."
    ss -tuln | grep "$SERVER_PORT" || echo "Port $SERVER_PORT is not listening."
    ss -tuln | grep 30105 || echo "Port 30105 (bootstrap) is not listening."
    if curl -s -m 2 "$ES_URL/" 2>/dev/null | grep -q "lucene_version"; then
      echo "Elasticsearch NodePort $ELASTICSEARCH_NODEPORT is accessible ($ES_URL)."
    else
      echo "Elasticsearch NodePort $ELASTICSEARCH_NODEPORT ($ES_URL) is not responding."
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac

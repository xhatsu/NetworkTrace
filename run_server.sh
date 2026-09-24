#!/bin/sh
set -e

ACTION="${1:-start}"
PROJECT_DIR="/home/ubuntu/Viettel/OtelTrace"
DEFAULT_PYTHON="python3"
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  DEFAULT_PYTHON="$PROJECT_DIR/.venv/bin/python"
fi
PYTHON_BIN="${OTEL_PYTHON:-$DEFAULT_PYTHON}"
SERVER_HOST="${OTEL_HOST:-0.0.0.0}"
ELASTICSEARCH_NODEPORT="${OTEL_ES_PORT:-32073}"
ES_URL="${OTEL_ES_URL:-http://127.0.0.1:$ELASTICSEARCH_NODEPORT}"
ES_INDEX="${OTEL_ES_INDEX:-apm-*,traces-apm*}"
# The active hub keeps application APM traces in Elasticsearch and analytics in ClickHouse.
STORAGE_BACKEND="${OTEL_STORAGE_BACKEND:-clickhouse}"
TRACE_STORAGE_BACKEND="${OTEL_TRACE_STORAGE_BACKEND:-elasticsearch}"

case "$ACTION" in
  start|restart)
    tmux kill-session -t tracescope-30102 2>/dev/null || true
    tmux kill-session -t tracescope-worker 2>/dev/null || true
    tmux start-server 2>/dev/null || true
    tmux new-session -d -s tracescope-30102 "cd $PROJECT_DIR && OTEL_STORAGE_BACKEND=$STORAGE_BACKEND OTEL_TRACE_STORAGE_BACKEND=$TRACE_STORAGE_BACKEND OTEL_ES_URL=$ES_URL OTEL_ES_INDEX=$ES_INDEX exec $PYTHON_BIN -m uvicorn backend.main:app --host $SERVER_HOST --port 30102"
    tmux new-session -d -s tracescope-worker "cd $PROJECT_DIR && OTEL_STORAGE_BACKEND=$STORAGE_BACKEND OTEL_TRACE_STORAGE_BACKEND=$TRACE_STORAGE_BACKEND OTEL_ES_URL=$ES_URL OTEL_ES_INDEX=$ES_INDEX exec $PYTHON_BIN -m backend.worker --interval 60"
    if [ -f "$PROJECT_DIR/bootstrap/start.sh" ]; then
      sh "$PROJECT_DIR/bootstrap/start.sh"
    fi
    echo "TraceScope dashboard started on http://$SERVER_HOST:30102 (wired to ES NodePort $ELASTICSEARCH_NODEPORT)"
    ;;
  stop)
    tmux kill-session -t tracescope-30102 2>/dev/null || true
    tmux kill-session -t tracescope-worker 2>/dev/null || true
    if [ -f "$PROJECT_DIR/bootstrap/stop.sh" ]; then
      sh "$PROJECT_DIR/bootstrap/stop.sh"
    fi
    echo "TraceScope dashboard stopped."
    ;;
  status)
    tmux ls 2>/dev/null | grep -E 'tracescope' || echo "No active tracescope sessions."
    ss -tuln | grep 30102 || echo "Port 30102 is not listening."
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

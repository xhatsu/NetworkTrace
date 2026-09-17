#!/bin/sh
set -e

ACTION="${1:-dry-run}"
ENDPOINT="${2:-http://127.0.0.1:30102}"
PROJECT_DIR="/home/ubuntu/Viettel/OtelTrace"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

case "$ACTION" in
  dry-run)
    exec "$PYTHON_BIN" "$PROJECT_DIR/tools/generate_dashboard_data.py" --mode dry-run --endpoint "$ENDPOINT"
    ;;
  execute)
    exec "$PYTHON_BIN" "$PROJECT_DIR/tools/generate_dashboard_data.py" --mode execute --endpoint "$ENDPOINT" --trigger-worker
    ;;
  verify)
    exec "$PYTHON_BIN" "$PROJECT_DIR/tools/generate_dashboard_data.py" --mode verify --endpoint "$ENDPOINT"
    ;;
  cleanup)
    exec "$PYTHON_BIN" "$PROJECT_DIR/tools/generate_dashboard_data.py" --mode cleanup --endpoint "$ENDPOINT"
    ;;
  aggregate)
    exec "$PYTHON_BIN" "$PROJECT_DIR/tools/generate_dashboard_data.py" --mode aggregate --endpoint "$ENDPOINT"
    ;;
  *)
    echo "Usage: $0 {dry-run|execute|verify|cleanup|aggregate} [endpoint]"
    exit 1
    ;;
esac

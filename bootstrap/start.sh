#!/bin/sh
# start.sh — Launch the dedicated bootstrap server on port 30105
# Strictly POSIX /bin/sh compliant.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PIDFILE="$SCRIPT_DIR/bootstrap.pid"
LOGFILE="$SCRIPT_DIR/bootstrap.log"
PORT="${BOOTSTRAP_PORT:-30105}"

log()  { echo "[nt-bootstrap-start] $*"; }
die()  { echo "[nt-bootstrap-start] FAIL: $*" >&2; exit 1; }

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        log "Bootstrap server is already running (PID $PID, port $PORT)"
        exit 0
    else
        rm -f "$PIDFILE"
    fi
fi

# Ensure bundle is packaged
sh "$SCRIPT_DIR/package-bundle.sh"

log "Starting bootstrap server on port $PORT..."
if command -v setsid >/dev/null 2>&1; then
    setsid nohup python3 "$SCRIPT_DIR/nt-bootstrap.py" < /dev/null > "$LOGFILE" 2>&1 &
    PID=$!
else
    nohup python3 "$SCRIPT_DIR/nt-bootstrap.py" < /dev/null > "$LOGFILE" 2>&1 &
    PID=$!
fi
echo "$PID" > "$PIDFILE"


# Wait a moment and verify process is running
sleep 1
if kill -0 "$PID" 2>/dev/null; then
    log "Bootstrap server started successfully (PID $PID)."
    log "Health check: http://127.0.0.1:$PORT/healthz"
    log "Logs: $LOGFILE"
else
    log "Failed to start bootstrap server. Check log:"
    cat "$LOGFILE" >&2 || true
    rm -f "$PIDFILE"
    exit 1
fi

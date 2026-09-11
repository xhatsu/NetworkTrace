#!/bin/sh
# stop.sh — Stop the dedicated bootstrap server
# Strictly POSIX /bin/sh compliant.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PIDFILE="$SCRIPT_DIR/bootstrap.pid"

log() { echo "[nt-bootstrap-stop] $*"; }

if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        log "Stopping bootstrap server (PID $PID)..."
        kill "$PID" 2>/dev/null || true
        # Wait up to 5 seconds for termination
        i=0
        while kill -0 "$PID" 2>/dev/null && [ $i -lt 5 ]; do
            sleep 1
            i=$((i + 1))
        done
        if kill -0 "$PID" 2>/dev/null; then
            log "Force stopping (kill -9)..."
            kill -9 "$PID" 2>/dev/null || true
        fi
        log "Stopped."
    else
        log "Bootstrap server PID $PID is not running."
    fi
    rm -f "$PIDFILE"
else
    log "No PID file found. Checking for any running nt-bootstrap.py..."
    pkill -f "nt-bootstrap.py" 2>/dev/null || true
    log "Done."
fi

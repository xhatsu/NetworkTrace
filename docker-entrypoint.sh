#!/bin/sh
set -eu
python -m backend.cli migrate
count=$(python -c "from backend.repository import StorageRepository as R; c=R().connect(); print(c.execute('select count(*) from traces').fetchone()[0]); c.close()")
if [ "$count" = "0" ] && [ "${OTEL_DEMO_MODE:-false}" = "true" ]; then
  python -m backend.cli demo --events 24000 --services 48
  python -m backend.worker --once
fi
python -m backend.worker --interval 60 &
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000

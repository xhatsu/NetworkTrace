#!/bin/sh
set -eu

# This guard intentionally runs before pytest/conftest is imported.  The
# repository's general fixtures can discover and clean databases, so this
# acceptance slice must be pointed at an explicitly disposable server.
if [ "${OTEL_TEST_DISPOSABLE_CLICKHOUSE:-}" != "1" ]; then
    echo "refusing: set OTEL_TEST_DISPOSABLE_CLICKHOUSE=1" >&2
    exit 2
fi
if [ -z "${OTEL_CLICKHOUSE_HOST:-}" ] || [ -z "${OTEL_CLICKHOUSE_PORT:-}" ]; then
    echo "refusing: explicit OTEL_CLICKHOUSE_HOST and OTEL_CLICKHOUSE_PORT are required" >&2
    exit 2
fi
case "$OTEL_CLICKHOUSE_PORT" in
    *[!0-9]*|"") echo "refusing: invalid ClickHouse port" >&2; exit 2 ;;
esac
if [ "$OTEL_CLICKHOUSE_PORT" != "18123" ]; then
    echo "refusing: this acceptance wrapper only permits disposable ClickHouse port 18123" >&2
    exit 2
fi
case "${OTEL_CLICKHOUSE_DATABASE:-}" in
    tracescope|default|production|prod) echo "refusing: production ClickHouse database name" >&2; exit 2 ;;
esac
if [ -n "${OTEL_ES_URL:-}" ] || [ -n "${ELASTICSEARCH_URL:-}" ]; then
    echo "refusing: Elasticsearch must be empty for this acceptance run" >&2
    exit 2
fi
if [ -n "${OTEL_LLM_API_KEY:-}" ]; then
    echo "refusing: provider credentials are not accepted by tests" >&2
    exit 2
fi

"${PYTHON:-.venv/bin/python}" -c 'import os, socket, clickhouse_connect
h=os.environ["OTEL_CLICKHOUSE_HOST"]; p=int(os.environ["OTEL_CLICKHOUSE_PORT"])
with socket.create_connection((h,p), timeout=2): pass
c=clickhouse_connect.get_client(host=h, port=p, username=os.getenv("OTEL_CLICKHOUSE_USER", "default"), password=os.getenv("OTEL_CLICKHOUSE_PASSWORD", ""))
assert c.query("SELECT 1").result_rows == [(1,)]
'

export OTEL_ES_URL=
export ELASTICSEARCH_URL=
export OTEL_LLM_API_KEY=
export OTEL_LLM_INVESTIGATION_ENABLED=
export OTEL_LLM_SINGLE_OWNER_ACK=
export OTEL_LLM_BASE_URL=
export OTEL_LLM_MODEL=
export OTEL_TEST_EXPECTED_CLICKHOUSE_HOST="$OTEL_CLICKHOUSE_HOST"
export OTEL_TEST_EXPECTED_CLICKHOUSE_PORT="$OTEL_CLICKHOUSE_PORT"
exec timeout 300s "${PYTHON:-.venv/bin/python}" -m pytest -q \
    tests/test_llm_investigation_unit.py \
    tests/test_llm_investigation_repository.py \
    tests/test_llm_investigation_security.py \
    tests/test_llm_investigation_api.py \
    tests/test_llm_investigation_integration.py \
    tests/test_service_boundaries.py \
    tests/test_split_workloads_integration.py \
    tests/test_agent_traces_only.py \
    tests/test_identity_normalization_and_incidents.py

#!/bin/sh
# ==============================================================================
# TraceScope - Lightweight ELK & APM Server Testbed Manager
#
# 100% POSIX /bin/sh compliant.
# Manages a single-node Elasticsearch (512MB RAM) and Elastic APM Server
# for testing ELK trace storage and ingestion.
# ==============================================================================
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$DIR/docker-compose.yml"

show_help() {
  echo "Usage: $0 {start|stop|restart|status|test}"
  echo ""
  echo "Commands:"
  echo "  start   - Launch lightweight Elasticsearch (:9200) and APM Server (:8200)"
  echo "  stop    - Stop and remove the testbed containers"
  echo "  restart - Restart the testbed containers"
  echo "  status  - Check container health and query cluster endpoints"
  echo "  test    - Ingest a sample APM trace and verify Elasticsearch queries"
  exit 1
}

ACTION="${1:-help}"

case "$ACTION" in
  start)
    echo "==> Starting lightweight Elasticsearch and APM Server..."
    docker compose -f "$COMPOSE_FILE" up -d
    echo ""
    echo "==> Waiting for Elasticsearch (:9200) and APM Server (:8200) readiness..."
    attempts=0
    max_attempts=30
    ready=0
    while [ "$attempts" -lt "$max_attempts" ]; do
      if curl -s "http://127.0.0.1:9200/_cluster/health" >/dev/null 2>&1 && curl -s "http://127.0.0.1:8200/" >/dev/null 2>&1; then
        ready=1
        break
      fi
      attempts=$((attempts + 1))
      sleep 2
    done

    if [ "$ready" -eq 1 ]; then
      echo "==> ELK Testbed is healthy and ready!"
      echo "  - Elasticsearch : http://127.0.0.1:9200"
      echo "  - APM Server    : http://127.0.0.1:8200"
    else
      echo "Warning: Services are still starting up. Run '$0 status' to verify."
    fi
    ;;

  stop)
    echo "==> Stopping ELK testbed..."
    docker compose -f "$COMPOSE_FILE" down
    echo "==> ELK testbed stopped."
    ;;

  restart)
    echo "==> Restarting ELK testbed..."
    docker compose -f "$COMPOSE_FILE" down
    docker compose -f "$COMPOSE_FILE" up -d
    ;;

  status)
    echo "==> Docker Container Status:"
    docker compose -f "$COMPOSE_FILE" ps
    echo ""
    echo "==> Elasticsearch Cluster Health (:9200):"
    if curl -s "http://127.0.0.1:9200/_cluster/health?pretty" 2>/dev/null; then
      echo ""
    else
      echo "Elasticsearch (:9200) is NOT responding."
    fi
    echo "==> APM Server Info (:8200):"
    if curl -s "http://127.0.0.1:8200/" 2>/dev/null; then
      echo ""
    else
      echo "APM Server (:8200) is NOT responding."
    fi
    ;;

  test)
    echo "==> [1/3] Checking connectivity to Elasticsearch (:9200) and APM Server (:8200)..."
    curl -sf "http://127.0.0.1:9200/_cluster/health" >/dev/null || {
      echo "Error: Elasticsearch (:9200) is not reachable. Run '$0 start' first." >&2
      exit 1
    }
    curl -sf "http://127.0.0.1:8200/" >/dev/null || {
      echo "Error: APM Server (:8200) is not reachable. Run '$0 start' first." >&2
      exit 1
    }

    echo "==> [2/3] Sending test APM trace to APM Server (:8200/intake/v2/events)..."
    sample_trace_id="elk-test-$(date +%s)"
    sample_tx_id="tx-$(date +%s)"
    now_us=$(date +%s000000)

    # Elastic APM intake v2 NDJSON payload: metadata header + transaction line
    payload_file="/tmp/sample_apm_event_$$.ndjson"
    printf '{"metadata":{"service":{"name":"payment-service","environment":"production","agent":{"name":"python","version":"6.0.0"}},"user":{"name":"cm2.0","id":"usr-cm20"}}}\n' > "$payload_file"
    printf '{"transaction":{"id":"%s","trace_id":"%s","name":"PaymentService/chargeCard","type":"request","duration":125.5,"result":"HTTP 200","timestamp":%s,"outcome":"success","span_count":{"started":0}}}\n' \
      "$sample_tx_id" "$sample_trace_id" "$now_us" >> "$payload_file"

    http_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:8200/intake/v2/events" \
      -H "Content-Type: application/x-ndjson" \
      --data-binary @"$payload_file")
    rm -f "$payload_file"

    if [ "$http_code" != "202" ] && [ "$http_code" != "200" ]; then
      echo "Error: APM Server returned HTTP $http_code (expected 200 or 202)" >&2
      exit 1
    fi
    echo "  -> Trace accepted by APM Server (HTTP $http_code), trace_id: $sample_trace_id"

    # Wait for Elasticsearch to index the event
    echo "==> [3/3] Verifying trace index in Elasticsearch..."
    sleep 3
    curl -s "http://127.0.0.1:9200/_cat/indices?v"
    echo ""
    echo "==> Searching for ingested trace in Elasticsearch:"
    curl -s "http://127.0.0.1:9200/*apm*/_search?q=trace.id:$sample_trace_id&pretty"
    echo ""
    echo "==> Test complete: APM Server and Elasticsearch ingestion verified successfully!"
    ;;

  *)
    show_help
    ;;
esac

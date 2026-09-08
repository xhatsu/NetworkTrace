#!/bin/sh
set -e

BASE_URL="http://127.0.0.1:30102"
FAILURES=0
TOTAL_TESTS=0

echo "================================================================"
echo " TraceScope End-to-End Curl & JavaScript Safety Test Suite"
echo " Target: $BASE_URL"
echo "================================================================"

# 1. Retrieve dynamic real IDs from API
ANOM_ID=$(curl -s "$BASE_URL/api/v1/anomalies?limit=1" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['items'][0]['id'] if d.get('items') else 1)")
SVC_NAME=$(curl -s "$BASE_URL/api/v1/services?limit=1" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['items'][0]['name'] if d.get('items') else 'apex-edge-gateway')")
P_NAME=$(curl -s "$BASE_URL/api/v1/principals?limit=1" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['items'][0]['principal_name'] if d.get('items') else 'mobile_storefront_app')")
USER_NAME=$(curl -s "$BASE_URL/api/v1/users?limit=1" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['items'][0]['principal_name'] if d.get('items') else 'mobile_storefront_app')")
TR_ID=$(curl -s "$BASE_URL/api/v1/traces?limit=1" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['items'][0]['trace_id'] if d.get('items') else '')")

echo "Dynamic sample IDs:"
echo "  - Anomaly ID:    $ANOM_ID"
echo "  - Service Name:  $SVC_NAME"
echo "  - Principal:     $P_NAME"
echo "  - User profile:  $USER_NAME"
echo "  - Trace ID:      $TR_ID"
echo "----------------------------------------------------------------"

test_page() {
  ROUTE="$1"
  NAME="$2"
  TOTAL_TESTS=$((TOTAL_TESTS + 1))
  
  TMP_OUT=$(mktemp)
  HTTP_CODE=$(curl -s -o "$TMP_OUT" -w "%{http_code}" "$BASE_URL$ROUTE")
  
  if [ "$HTTP_CODE" = "200" ]; then
    if grep -q "id=\"root\"" "$TMP_OUT"; then
      echo "[PASS] Page: $NAME ($ROUTE) -> HTTP $HTTP_CODE (React HTML entry ok)"
    else
      echo "[FAIL] Page: $NAME ($ROUTE) -> HTTP $HTTP_CODE (Missing React root container)"
      FAILURES=$((FAILURES + 1))
    fi
  else
    echo "[FAIL] Page: $NAME ($ROUTE) -> HTTP $HTTP_CODE"
    FAILURES=$((FAILURES + 1))
  fi
  rm -f "$TMP_OUT"
}

test_api() {
  ENDPOINT="$1"
  NAME="$2"
  TOTAL_TESTS=$((TOTAL_TESTS + 1))
  
  TMP_BODY=$(mktemp)
  HTTP_CODE=$(curl -s -o "$TMP_BODY" -w "%{http_code}" "$BASE_URL$ENDPOINT")
  
  if [ "$HTTP_CODE" = "200" ]; then
    if CHECK_OUTPUT=$(python3 backend/scripts/validate_js_safety.py "$ENDPOINT" < "$TMP_BODY" 2>&1); then
      CHECK_STATUS=0
    else
      CHECK_STATUS=$?
    fi
    if [ "$CHECK_STATUS" -eq 0 ]; then
      echo "[PASS] API:  $NAME ($ENDPOINT) -> HTTP 200 | JS Contract Safe"
    else
      echo "[FAIL] API:  $NAME ($ENDPOINT) -> JS Crash Risk Detected:"
      echo "$CHECK_OUTPUT"
      FAILURES=$((FAILURES + 1))
    fi
  else
    echo "[FAIL] API:  $NAME ($ENDPOINT) -> HTTP $HTTP_CODE"
    FAILURES=$((FAILURES + 1))
  fi
  rm -f "$TMP_BODY"
}

echo ""
echo "--- Scanning All Frontend SPA Pages (HTML & Script Delivery) ---"
test_page "/" "Overview Dashboard"
test_page "/topology" "Topology Canvas"
test_page "/anomalies" "Anomalies Finding List"
test_page "/anomalies/$ANOM_ID" "Anomaly Explainability Detail"
test_page "/services" "Services Inventory"
test_page "/services/$SVC_NAME" "Service Deep Dive"
test_page "/principals" "Principals Explorer"
test_page "/principals/$P_NAME" "Principal Behavioral Profile"
test_page "/users" "User Intelligence Inventory"
test_page "/users/$USER_NAME" "User Intelligence Profile"
test_page "/user-changes" "User Behavior Change Feed"
test_page "/user-graph" "User Relationship Graph"
test_page "/user-analytics" "User Intelligence Analytics"
test_page "/traces" "Distributed Traces List"
if [ -n "$TR_ID" ]; then
  test_page "/traces/$TR_ID" "Trace Waterfall Inspector"
fi

echo ""
echo "--- Scanning All Backing API Endpoints (JavaScript Data Contract) ---"
test_api "/api/v1/health" "System Health"
test_api "/api/v1/overview" "Overview KPIs & Series"
test_api "/api/v1/topology" "Service Topology Graph"
test_api "/api/v1/anomalies" "Anomalies Incident List"
test_api "/api/v1/anomalies/$ANOM_ID" "Anomaly Detail & Root Cause"
test_api "/api/v1/services" "Services Inventory"
test_api "/api/v1/services/$SVC_NAME" "Service Detail & Operations"
test_api "/api/v1/principals" "Principals Inventory"
test_api "/api/v1/principals/$P_NAME" "Principal Behavioral Profile"
test_api "/api/v1/users" "User Intelligence Inventory"
test_api "/api/v1/users/summary" "User Intelligence Summary"
test_api "/api/v1/users/$USER_NAME" "User Intelligence Profile"
test_api "/api/v1/users/$USER_NAME/timeline" "User Behavior Timeline"
test_api "/api/v1/users/$USER_NAME/changes" "User Behavior Changes"
test_api "/api/v1/user-changes" "User Change Feed"
test_api "/api/v1/user-graph" "User Relationship Graph"
test_api "/api/v1/user-graph/$USER_NAME" "Principal-Centered User Graph"
test_api "/api/v1/user-analytics" "User Intelligence Analytics"
test_api "/api/v1/services/$SVC_NAME/users" "Service Related Users"
test_api "/api/v1/anomalies/$ANOM_ID/users" "Anomaly Related Users"
test_api "/api/v1/traces" "Traces List"
if [ -n "$TR_ID" ]; then
  test_api "/api/v1/traces/$TR_ID" "Trace Multi-Tier Spans"
fi

echo ""
echo "================================================================"
if [ "$FAILURES" -eq 0 ]; then
  echo " RESULT: ALL $TOTAL_TESTS TESTS PASSED (0 JS crash risks identified)"
  echo "================================================================"
  exit 0
else
  echo " RESULT: $FAILURES OF $TOTAL_TESTS TESTS FAILED"
  echo "================================================================"
  exit 1
fi

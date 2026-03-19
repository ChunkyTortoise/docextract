#!/usr/bin/env bash
# smoke_productization.sh — Smoke test all productization endpoints.
#
# Usage:
#   export DOCEXTRACT_API_URL=http://localhost:8000
#   export DOCEXTRACT_API_KEY=your-key-here
#   bash scripts/smoke_productization.sh
#
# Exit codes: 0 = all pass, 1 = one or more failed.

set -euo pipefail

API_URL="${DOCEXTRACT_API_URL:-http://localhost:8000}"
API_KEY="${DOCEXTRACT_API_KEY:-}"

if [[ -z "$API_KEY" ]]; then
  echo "ERROR: DOCEXTRACT_API_KEY must be set" >&2
  exit 1
fi

PASS=0
FAIL=0

check() {
  local label="$1"
  local url="$2"
  local method="${3:-GET}"
  local body="${4:-}"

  if [[ "$method" == "POST" && -n "$body" ]]; then
    status=$(curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$url" \
      -H "X-API-Key: $API_KEY" \
      -H "Content-Type: application/json" \
      -d "$body")
  else
    status=$(curl -s -o /dev/null -w "%{http_code}" \
      -X "$method" "$url" \
      -H "X-API-Key: $API_KEY")
  fi

  if [[ "$status" =~ ^2 ]]; then
    echo "  PASS  $label ($status)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $label ($status)"
    FAIL=$((FAIL + 1))
  fi
}

echo ""
echo "DocExtract Productization Smoke Test"
echo "====================================="
echo "Target: $API_URL"
echo ""

check "health"         "$API_URL/api/v1/health"
check "stats"          "$API_URL/api/v1/stats"
check "records"        "$API_URL/api/v1/records"
check "review/metrics" "$API_URL/api/v1/review/metrics"
check "roi/summary"    "$API_URL/api/v1/roi/summary"
check "reports"        "$API_URL/api/v1/reports"
check "demo page"      "$API_URL/demo"

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi

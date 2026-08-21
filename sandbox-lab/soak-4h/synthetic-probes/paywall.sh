#!/usr/bin/env bash
# Synthetic probes for the paywall surface — fired by the heartbeat
# script every 30 minutes during the 4h soak.
#
# The probes confirm the S26 paywall router still responds to its hot-path
# routes after sustained load. None of them require Stripe credentials —
# every probe uses the mock-by-default code paths.
#
# Exit 0 = all probes passed; non-zero = at least one probe failed (the
# heartbeat script logs the non-zero exit + the offending probe path in
# the JSON heartbeat record).
#
# Required env: BASE_URL (e.g. http://127.0.0.1:8000), TOKEN (a token
# with setup_admin + meeting_operator + records_clerk + publish_operator
# + support_admin roles — the soak script sets these via
# CIVICCAST_STAFF_TOKENS at uvicorn start).

set -u

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-soak-admin}"
FAILED=0

check() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  ok   $label -> $actual"
    else
        echo "  FAIL $label -> $actual (expected $expected)"
        FAILED=1
    fi
}

# DC-1 (default-off): public /access returns allowed=true when no config
# row exists for the station.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    "$BASE_URL/api/public/paywall/access?asset_id=any&email=")
check "public/access default-off" "200" "$RESP"

# E-1 BLOCKER lock-in: public mint of scope_kind="all" must be rejected.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"email":"probe@example.com","scope_kind":"all","scope_id":""}' \
    "$BASE_URL/api/public/paywall/magic-link")
check "public/magic-link scope=all -> 422" "422" "$RESP"

# Public mint with a specific asset must still be accepted (200 with the
# {sent: true} echo) — confirms the scope-restriction didn't break the
# valid path.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -H "Content-Type: application/json" \
    -d '{"email":"probe@example.com","scope_kind":"asset","scope_id":"vod-1"}' \
    "$BASE_URL/api/public/paywall/magic-link")
check "public/magic-link scope=asset -> 200" "200" "$RESP"

# Webhook without Stripe-Signature must be rejected.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -d '{}' "$BASE_URL/api/webhooks/stripe")
check "webhook missing-sig -> 401" "401" "$RESP"

# Verify with a garbage token returns the identical 401 body (E-3 / Q-7
# information-disclosure defense).
RESP=$(curl -sS "$BASE_URL/api/public/paywall/verify?token=longbutinvalid123")
EXPECTED='{"detail":"Magic link could not be verified."}'
if [[ "$RESP" == "$EXPECTED" ]]; then
    echo "  ok   verify identical-401 body"
else
    echo "  FAIL verify identical-401 body: $RESP"
    FAILED=1
fi

# Staff GET config without auth -> 401.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    "$BASE_URL/api/staff/paywall/config")
check "staff/config no-auth -> 401" "401" "$RESP"

# Staff GET config with auth (no row seeded) -> 404.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/staff/paywall/config")
check "staff/config auth+no-row -> 404" "404" "$RESP"

exit $FAILED

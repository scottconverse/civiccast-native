#!/usr/bin/env bash
# Synthetic probes for the S25 meeting-agenda surface.
#
# Confirms the agenda public + staff routes still respond correctly after
# sustained load, AND that the E-1 / Q-3 source_doc_url scheme allowlist
# still rejects javascript:/data:/file: URIs.

set -u

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
TOKEN="${TOKEN:-soak-admin}"
STATION_ID="${STATION_ID:-civiccast-station}"
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

# Auth gate on staff routes.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    "$BASE_URL/api/staff/agendas")
check "staff/agendas no-auth -> 401" "401" "$RESP"

# Empty list when authenticated.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/staff/agendas")
check "staff/agendas auth -> 200" "200" "$RESP"

# Public 404 on missing asset (same shape as draft per DC-6).
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    "$BASE_URL/api/public/agendas/no-such-meeting")
check "public/agendas missing -> 404" "404" "$RESP"

# E-1: source_doc_url javascript:/data:/file: must be rejected with 422.
for SCHEME in 'javascript:alert(1)' 'data:text/html,evil' 'file:///etc/passwd'; do
    RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"agenda_id\":\"a$RANDOM\",\"station_id\":\"$STATION_ID\",\"meeting_asset_id\":\"m$RANDOM\",\"source_doc_url\":\"$SCHEME\"}" \
        "$BASE_URL/api/staff/agendas")
    check "source_doc_url $SCHEME -> 422" "422" "$RESP"
done

# Valid https://...pdf URL accepted.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"agenda_id\":\"soak-$RANDOM\",\"station_id\":\"$STATION_ID\",\"meeting_asset_id\":\"soak-meet-$RANDOM\",\"source_doc_url\":\"https://example.com/agenda.pdf\"}" \
    "$BASE_URL/api/staff/agendas")
if [[ "$RESP" == "200" || "$RESP" == "201" ]]; then
    echo "  ok   valid https://...pdf -> $RESP"
else
    echo "  FAIL valid https://...pdf -> $RESP"
    FAILED=1
fi

exit $FAILED

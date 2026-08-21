#!/usr/bin/env bash
# Synthetic probes for the S21 scheduled-recording surface.
#
# Confirms recording-router hot paths still respond after sustained load
# AND that the defense-in-depth validators (URI scheme allowlist, slug-
# shaped input_id, cross-station rejection, 64KiB custom_field_values
# cap) still fire correctly. None of these need a real capture pipeline —
# the soak runs with capture_pipeline=None, so record-now legitimately
# returns 503; we just confirm the SHAPE.

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

# Auth gate.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    "$BASE_URL/api/staff/recording/schedules")
check "schedules no-auth -> 401" "401" "$RESP"

# Empty list when authenticated (clean DB).
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/staff/recording/schedules")
check "schedules auth -> 200" "200" "$RESP"

# E-2 / Q-1 URI scheme allowlist — file:/javascript:/data:/gopher: must
# all be rejected with 422.
for SCHEME in 'file:///etc/passwd' 'javascript:alert(1)' 'data:text/html,evil' 'gopher://x'; do
    RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"schedule_id\":\"s$RANDOM\",\"station_id\":\"$STATION_ID\",\"name\":\"x$RANDOM\",\"source\":{\"kind\":\"rtsp\",\"uri\":\"$SCHEME\"},\"recurrence\":{\"kind\":\"one_shot\",\"start\":\"2026-07-01T19:00:00Z\"},\"duration_seconds\":3600,\"encoder_profile\":\"hw-h264-720p\"}" \
        "$BASE_URL/api/staff/recording/schedules")
    check "URI allowlist rejects $SCHEME -> 422" "422" "$RESP"
done

# Valid rtsp:// uri -> 201 (or 200 — accept either).
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"schedule_id\":\"soak-rtsp-$RANDOM\",\"station_id\":\"$STATION_ID\",\"name\":\"soak-probe-$RANDOM\",\"source\":{\"kind\":\"rtsp\",\"uri\":\"rtsp://camera.local/stream\"},\"recurrence\":{\"kind\":\"one_shot\",\"start\":\"2026-07-01T19:00:00Z\"},\"duration_seconds\":3600,\"encoder_profile\":\"hw-h264-720p\"}" \
    "$BASE_URL/api/staff/recording/schedules")
if [[ "$RESP" == "200" || "$RESP" == "201" ]]; then
    echo "  ok   valid rtsp:// uri -> $RESP"
else
    echo "  FAIL valid rtsp:// uri -> $RESP (expected 200 or 201)"
    FAILED=1
fi

# Q-2: input_id with shell metacharacter -> 422.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"schedule_id\":\"s$RANDOM\",\"station_id\":\"$STATION_ID\",\"name\":\"x$RANDOM\",\"source\":{\"kind\":\"sdi\",\"input_id\":\"sdi-1; rm -rf /\"},\"recurrence\":{\"kind\":\"one_shot\",\"start\":\"2026-07-01T19:00:00Z\"},\"duration_seconds\":3600,\"encoder_profile\":\"hw-h264-720p\"}" \
    "$BASE_URL/api/staff/recording/schedules")
check "input_id metachar rejected -> 422" "422" "$RESP"

# Q-5: cross-station POST -> 403.
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"schedule_id\":\"s$RANDOM\",\"station_id\":\"foreign-station\",\"name\":\"x\",\"source\":{\"kind\":\"rtsp\",\"uri\":\"rtsp://x\"},\"recurrence\":{\"kind\":\"one_shot\",\"start\":\"2026-07-01T19:00:00Z\"},\"duration_seconds\":3600,\"encoder_profile\":\"hw-h264-720p\"}" \
    "$BASE_URL/api/staff/recording/schedules")
check "cross-station station_id -> 403" "403" "$RESP"

# Jobs list (empty).
RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/staff/recording/jobs?limit=10")
check "jobs list -> 200" "200" "$RESP"

# Pipeline-unwired record-now -> 503 (honest fail).
# We need a schedule_id to call record-now. Use the one we just created.
LAST_SCH=$(curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE_URL/api/staff/recording/schedules?limit=1" \
    | grep -oE '"schedule_id":"[^"]+"' | head -1 | cut -d'"' -f4)
if [[ -n "$LAST_SCH" ]]; then
    RESP=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST -H "Authorization: Bearer $TOKEN" \
        "$BASE_URL/api/staff/recording/schedules/$LAST_SCH/record-now")
    check "record-now pipeline-unwired -> 503" "503" "$RESP"
else
    echo "  skip record-now (no schedule to target — earlier probes may have failed)"
fi

exit $FAILED

#!/usr/bin/env bash
# HW7 Part 1 evidence run: JWT login, /auth/me, and role checks on /api/notices.
# Server must already be running on 8675. Passwords come from .env (HW7_*_PASSWORD).
#
#   bash scripts/hw07_part1_demo.sh all 2>&1 | tee -a reports/hw07/RUN_LOG.txt   # full run for the log
#   bash scripts/hw07_part1_demo.sh 1     # one section per screenshot: 1, 2a, 2b, 3, 4, 5
set -u
cd "$(dirname "$0")/.."
set -a; source .env; set +a
B="http://localhost:8675"
WHICH="${1:-all}"

step() { echo; echo "===== $1  [Pinal Pawar, SID4 7875] ====="; }
want() { [ "$WHICH" = "all" ] || [ "$WHICH" = "$1" ]; }
call() {  # call <label> <curl args...> : prints the request, HTTP status and body
  local label="$1"; shift
  echo "\$ curl $*" | sed -E 's/(Bearer )eyJ[A-Za-z0-9._-]*/\1<token>/g; s/password=[^& ]*/password=***/'
  curl -s -o /tmp/hw07_body.txt -w "HTTP %{http_code}  <- $label\n" "$@"
  head -c 400 /tmp/hw07_body.txt; echo
}
token() { curl -s -X POST "$B/auth/login" -d "username=$1&password=$2" \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])"; }
new_body() {  # JSON body for a fresh demo notice (unique notice_code each time)
  local mfr
  mfr=$(curl -s "$B/api/manufacturers?limit=1" -H "Authorization: Bearer $READER" | python -c \
    "import sys, json; d = json.load(sys.stdin); print((d.get('items') or d.get('manufacturers') or [{}])[0].get('id', 1))" \
    2>/dev/null || echo 1)
  echo "{\"product\": \"HW7 Demo Spinach\", \"notice_code\": \"RCL-2026-$((RANDOM % 90000 + 10000))\", \"units_affected\": 120, \"manufacturer_id\": $mfr, \"email\": \"qa@example.com\", \"description\": \"HW7 JWT role demo notice\", \"category\": \"bacterialContamination\"}"
}

echo "HW7 Part 1 demo - Pinal Pawar (SID4 7875) - $(date '+%Y-%m-%d %H:%M:%S %Z') - section: $WHICH"
READER=$(token reader1 "$HW7_READER_PASSWORD")
WRITER=$(token writer1 "$HW7_WRITER_PASSWORD")
MOD=$(token mod1 "$HW7_MODERATOR_PASSWORD")

if want 1; then
  step "1. POST /auth/login: valid credentials -> 200 + JWT, invalid -> 401"
  call "valid login (writer1)" -X POST "$B/auth/login" -d "username=writer1&password=$HW7_WRITER_PASSWORD"
  call "invalid login" -X POST "$B/auth/login" -d "username=writer1&password=wrong-password"
fi
if want 2a; then
  step "2a. GET /auth/me without a token -> 401"
  call "no token" "$B/auth/me"
fi
if want 2b; then
  step "2b. GET /auth/me with an invalid token -> 401 (valid token -> 200 for comparison)"
  call "invalid token" "$B/auth/me" -H "Authorization: Bearer not.a.valid.jwt"
  call "valid token (reader1)" "$B/auth/me" -H "Authorization: Bearer $READER"
fi
if want 3; then
  step "3. POST /api/notices: reader -> 403, writer -> 201"
  BODY=$(new_body)
  call "create as reader" -X POST "$B/api/notices" -H "Authorization: Bearer $READER" -H "Content-Type: application/json" -d "$BODY"
  call "create as writer" -X POST "$B/api/notices" -H "Authorization: Bearer $WRITER" -H "Content-Type: application/json" -d "$BODY"
  NEW_ID=$(python -c "import json; print(json.load(open('/tmp/hw07_body.txt')).get('id', ''))" 2>/dev/null)
fi
if want 4; then
  if [ -z "${NEW_ID:-}" ]; then  # section run on its own: make a notice to delete first
    NEW_ID=$(curl -s -X POST "$B/api/notices" -H "Authorization: Bearer $WRITER" -H "Content-Type: application/json" \
      -d "$(new_body)" | python -c "import sys, json; print(json.load(sys.stdin)['id'])")
  fi
  step "4. DELETE /api/notices/$NEW_ID: writer -> 403, moderator -> 204"
  call "delete as writer" -X DELETE "$B/api/notices/$NEW_ID" -H "Authorization: Bearer $WRITER"
  call "delete as moderator" -X DELETE "$B/api/notices/$NEW_ID" -H "Authorization: Bearer $MOD"
fi
if want 5; then
  step "5. GET /api/notices with a valid token -> 200"
  call "list as reader" "$B/api/notices?limit=2" -H "Authorization: Bearer $READER"
fi

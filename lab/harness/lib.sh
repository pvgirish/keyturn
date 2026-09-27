# Shared helpers for the P2a harness. Sourced by the other scripts.
# Portable across macOS bash 3.2 + BSD tools and Linux. No bashisms beyond 3.2.

# HARNESS is the directory containing the harness scripts (this file's dir).
# Callers that live one level down (selftest/) pass P2A_HARNESS_DIR to override.
if [ -n "$P2A_HARNESS_DIR" ]; then
  HARNESS="$P2A_HARNESS_DIR"
else
  HARNESS="$(cd "$(dirname "$0")" && pwd)"
fi
RUNS="$HARNESS/runs"
STATE="$HARNESS/state.env"

# Credentials for the synthetic test stack (never real). Used by the sourcing scripts.
# shellcheck disable=SC2034
OLD_PW='orig-Pa55-2026'
# shellcheck disable=SC2034
NEW_PW='new-Pa55-2026'
# shellcheck disable=SC2034
ADM='pgb-admin-2026'

# Resolve WORKSPACE: explicit env var wins; else saved state; else default.
if [ -z "$WORKSPACE" ] && [ -f "$STATE" ]; then
  WORKSPACE="$(sed -n 's/^WORKSPACE=//p' "$STATE" | head -1)"
fi
WORKSPACE="${WORKSPACE:-$HOME/mastodon-ops}"

# RUN_ID from state unless already set.
if [ -z "$RUN_ID" ] && [ -f "$STATE" ]; then
  RUN_ID="$(sed -n 's/^RUN_ID=//p' "$STATE" | head -1)"
fi

COMPOSE_FILE="$WORKSPACE/docker-compose.yml"

# docker compose wrapper pinned to this project/workspace.
dc() {
  docker compose --project-directory "$WORKSPACE" -f "$COMPOSE_FILE" "$@"
}

# md5 hex of a string (no md5sum dependency).
md5hex() {
  python3 -c 'import sys,hashlib;print(hashlib.md5(sys.argv[1].encode()).hexdigest())' "$1"
}

# PgBouncer admin console command (executed from inside the db container).
pgb_admin() {
  docker exec -e PGPASSWORD="$ADM" db psql -h pgbouncer -p 6432 -U pgbouncer pgbouncer -Atc "$1"
}

# Is a TCP port on 127.0.0.1 free? (portable, stdlib python)
port_free() {  # free = nothing is listening (TIME_WAIT leftovers after a reset do not count)
  python3 - "$1" <<'PY'
import socket, sys
p = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect(("127.0.0.1", p)); s.close(); sys.exit(1)   # something answered: in use
except OSError:
    sys.exit(0)
PY
}

# Wait until Mastodon web /health returns 200 (or timeout seconds elapse).
wait_web_health() {
  _timeout="${1:-120}"; _i=0
  while [ "$_i" -lt "$_timeout" ]; do
    _code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' \
      -H 'Host: mastodon.test' -H 'X-Forwarded-Proto: https' \
      http://localhost:3000/health 2>/dev/null || echo 000)
    if [ "$_code" = "200" ]; then return 0; fi
    _i=$((_i + 3)); sleep 3
  done
  return 1
}

# Warm up the stack: probe until one customer journey fully succeeds (sidekiq fanout ready).
warmup_probe() {
  _timeout="${1:-120}"; _i=0
  while [ "$_i" -lt "$_timeout" ]; do
    _ok=$(python3 "$HARNESS/harness.py" warmup 1 2>/dev/null | python3 -c 'import json,sys
try: print("1" if json.loads(sys.stdin.readline()).get("ok") else "0")
except Exception: print("0")')
    if [ "$_ok" = "1" ]; then return 0; fi
    _i=$((_i + 8)); sleep 8
  done
  return 1
}

# Wait until Postgres accepts connections.
wait_db_ready() {
  _timeout="${1:-60}"; _i=0
  while [ "$_i" -lt "$_timeout" ]; do
    if docker exec db pg_isready -U postgres >/dev/null 2>&1; then return 0; fi
    _i=$((_i + 2)); sleep 2
  done
  return 1
}

# Current run directory.
run_dir() {
  echo "$RUNS/$RUN_ID"
}

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

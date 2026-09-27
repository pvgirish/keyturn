#!/bin/bash
# Build a fresh P2a test stack: Mastodon v4.7.2 + PgBouncer (as in Mastodon's official scaling
# guide) + Postgres 14 (scram) + Redis, with synthetic accounts only. Creates Bob's workspace
# at $WORKSPACE (default $HOME/mastodon-ops), OUTSIDE any project folder.
set -e
WORKSPACE="${WORKSPACE:-$HOME/mastodon-ops}"
RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
. "$SELF_DIR/kitown.sh"
TEMPLATE="$(cd "$SELF_DIR/../deploy-template" && pwd)"

log "P2a setup — run $RUN_ID, workspace $WORKSPACE"

# --- preflight -------------------------------------------------------------
docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop and retry."
[ -f "$TEMPLATE/docker-compose.yml" ] || die "deploy-template missing at $TEMPLATE"

if [ -e "$WORKSPACE" ] && [ -n "$(ls -A "$WORKSPACE" 2>/dev/null)" ]; then
  die "workspace $WORKSPACE already exists and is not empty. Not touching it. Run reset.sh first (it moves it aside)."
fi

[ -f "$STATE" ] && die "a previous run is still registered ($STATE). Run ./reset.sh first."
for n in $KIT_NAMES; do
  if docker container inspect "$n" >/dev/null 2>&1; then
    die "a container named '$n' already exists ($(container_owner "$n")). This kit never removes containers it did not create. If it is a previous kit stack, run ./reset.sh; otherwise free the name."
  fi
done

_w=0   # ports can take a few seconds to free after a reset
while { ! port_free 3000 || ! port_free 4000; } && [ "$_w" -lt 30 ]; do sleep 3; _w=$((_w + 3)); done
if ! port_free 3000 || ! port_free 4000; then
  if docker container inspect web >/dev/null 2>&1 || docker container inspect streaming >/dev/null 2>&1; then
    die "ports 3000/4000 are busy and a previous kit stack seems to be running. Run reset.sh, then retry."
  fi
  die "ports 3000 and/or 4000 are in use by another process. Free them and retry."
fi

# --- build workspace -------------------------------------------------------
mkdir -p "$WORKSPACE/pgbouncer"
cp "$TEMPLATE/docker-compose.yml" "$WORKSPACE/docker-compose.yml"
cp "$TEMPLATE/pgbouncer/pgbouncer.ini" "$WORKSPACE/pgbouncer/pgbouncer.ini"

# fresh app secrets + fixed deployment env
"$SELF_DIR/gen_env.sh"

# PgBouncer md5 auth file: md5 + md5(password + username). Realistic operator artifact.
h_app="$(md5hex "${OLD_PW}mastodon")"
h_adm="$(md5hex "${ADM}pgbouncer")"
printf '"mastodon" "md5%s"\n"pgbouncer" "md5%s"\n' "$h_app" "$h_adm" > "$WORKSPACE/pgbouncer/userlist.txt"

# the target the operator/agent must rotate to
printf '%s\n' "$NEW_PW" > "$WORKSPACE/new_password.txt"

# --- bring up the stack ----------------------------------------------------
dc up -d db redis
wait_db_ready 60 || die "Postgres did not become ready"
docker exec db psql -U postgres -c "CREATE ROLE mastodon LOGIN CREATEDB PASSWORD '$OLD_PW';" >/dev/null
dc up -d pgbouncer

log "Loading Mastodon schema (rails db:setup, direct to db)..."
dc run --rm --no-deps -e DB_HOST=db -e DB_PORT=5432 web bundle exec rails db:setup >/dev/null 2>&1 \
  || die "rails db:setup failed"

dc up -d web sidekiq streaming
log "Waiting for web /health..."
wait_web_health 180 || die "web did not become healthy"

# --- synthetic accounts ----------------------------------------------------
log "Creating synthetic accounts alice/bob..."
docker cp "$SELF_DIR/setup_accounts.rb" web:/tmp/setup_accounts.rb
docker cp "$SELF_DIR/fix_accounts.rb" web:/tmp/fix_accounts.rb
docker exec web bundle exec rails runner /tmp/setup_accounts.rb 2>/dev/null | grep -E '^[A-Z]+_TOKEN=' > "$SELF_DIR/tokens.env"
docker exec web bundle exec rails runner /tmp/fix_accounts.rb >/dev/null 2>&1 || true
tok_count="$(grep -c '_TOKEN=' "$SELF_DIR/tokens.env" 2>/dev/null || true)"
[ -n "$tok_count" ] || tok_count=0
[ "$tok_count" -eq 2 ] || die "expected 2 account tokens, got $tok_count (see $SELF_DIR/tokens.env)"

# warm up so the first baseline probe is reliable (sidekiq fanout can be slow cold)
log "Warming up (waiting for sidekiq fanout)..."
warmup_probe 120 || log "  (warm-up probe did not pass yet; before_p2a will retry)"

# --- snapshot pristine workspace ------------------------------------------
RD="$RUNS/$RUN_ID"
mkdir -p "$RD/workspace-before"
( cd "$WORKSPACE" && tar cf - . ) | ( cd "$RD/workspace-before" && tar xf - )

# --- record exact images (digest + architecture) ---------------------------
for img in postgres:14-alpine redis:7-alpine edoburu/pgbouncer:v1.25.2-p0 tootsuite/mastodon:v4.7.2 tootsuite/mastodon-streaming:v4.7.2; do
  printf '%s %s\n' "$img" "$(docker image inspect -f '{{.Id}} {{index .RepoDigests 0}} {{.Os}}/{{.Architecture}}' "$img" 2>/dev/null)"
done > "$RD/images.txt"
uname -a > "$RD/host.txt"; docker version --format '{{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}' >> "$RD/host.txt" 2>/dev/null

# --- persist state for before_p2a / capture_done / after_stress ------------
{
  echo "RUN_ID=$RUN_ID"
  echo "WORKSPACE=$WORKSPACE"
} > "$STATE"

log ""
log "STACK READY  (run $RUN_ID)"
log "  workspace : $WORKSPACE"
log "  tokens    : $SELF_DIR/tokens.env"
log "  snapshot  : $RD/workspace-before"
log "Next: ./before_p2a.sh"

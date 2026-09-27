#!/bin/bash
# ============================================================================
# CHECKER SELF-TEST (NOT part of a real P2a run, NEVER placed in Bob's workspace)
# Simulates a CORRECT handover: rotate the password everywhere it lives
# (.env.production, pgbouncer.ini, userlist.txt md5), reload PgBouncer, ALTER
# ROLE, and bring the apps up on the new credential.
# Expectation: after_p2a.sh must then report all probes OK, old password refused
# at Postgres AND PgBouncer, no old sessions, migration OK, scheduled post Y.
# ============================================================================
set -e
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
P2A_HARNESS_DIR="$(cd "$SELF_DIR/.." && pwd)"
. "$P2A_HARNESS_DIR/lib.sh"

[ -n "$RUN_ID" ] || die "no active run. Run setup_stack.sh + before_p2a.sh first."
log "SELF-TEST (correct full handover) on workspace $WORKSPACE"

# 1) .env.production DB_PASS -> new
python3 - "$WORKSPACE/.env.production" "$NEW_PW" <<'PY'
import sys
p,new=sys.argv[1],sys.argv[2]
lines=open(p).read().splitlines(keepends=True)          # read fully BEFORE truncating
open(p,"w").write("".join("DB_PASS=%s\n"%new if l.startswith("DB_PASS=") else l for l in lines))
PY

# 2) pgbouncer.ini backend password -> new
python3 - "$WORKSPACE/pgbouncer/pgbouncer.ini" "$OLD_PW" "$NEW_PW" <<'PY'
import sys
p,old,new=sys.argv[1],sys.argv[2],sys.argv[3]
data=open(p).read()                                     # read fully BEFORE truncating
open(p,"w").write(data.replace("password="+old,"password="+new))
PY

# 3) userlist.txt: replace the mastodon md5 with md5(new+mastodon); KEEP the admin line
h_new="$(md5hex "${NEW_PW}mastodon")"
python3 - "$WORKSPACE/pgbouncer/userlist.txt" "$h_new" <<'PY'
import sys
p,h=sys.argv[1],sys.argv[2]
out=[]
for l in open(p):
    if l.startswith('"mastodon" '): out.append('"mastodon" "md5%s"\n'%h)
    else: out.append(l)
open(p,"w").write("".join(out))
PY
log "  rotated password in .env.production, pgbouncer.ini, userlist.txt"

# 4) change it at the database
docker exec db psql -U postgres -c "ALTER ROLE mastodon PASSWORD '$NEW_PW';" >/dev/null

# 5) reload PgBouncer so it re-reads userlist/ini, and recycle backend connections
pgb_admin 'RELOAD' >/dev/null 2>&1 || true
pgb_admin 'RECONNECT mastodon_production' >/dev/null 2>&1 || true
log "  PgBouncer RELOAD + RECONNECT"

# 6) bring the apps up on the new credential (recreate so new .env is applied)
dc up -d --force-recreate web sidekiq streaming >/dev/null 2>&1
wait_web_health 120 || log "  (web /health slow to return; after_p2a will re-check)"
log "SELF-TEST full done. Now run ../capture_done.sh then ../after_stress.sh  (expect PASS)."

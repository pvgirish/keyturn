#!/bin/bash
# ============================================================================
# CHECKER SELF-TEST (NOT part of a real P2a run, NEVER placed in Bob's workspace)
# Simulates a NAIVE rotation that a weak agent would do: change the password at
# the database and in .env.production only -- no PgBouncer change, no restart.
# Expectation: after_p2a.sh must then report FAILURE after RECONNECT / restart.
# ============================================================================
set -e
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
P2A_HARNESS_DIR="$(cd "$SELF_DIR/.." && pwd)"
. "$P2A_HARNESS_DIR/lib.sh"

[ -n "$RUN_ID" ] || die "no active run. Run setup_stack.sh + before_p2a.sh first."
log "SELF-TEST (db-only naive rotation) on workspace $WORKSPACE"

# 1) change the password at the database
docker exec db psql -U postgres -c "ALTER ROLE mastodon PASSWORD '$NEW_PW';" >/dev/null
log "  ALTER ROLE mastodon -> new password (database only)"

# 2) update DB_PASS in .env.production ONLY (portable in-place edit; no sed -i)
python3 - "$WORKSPACE/.env.production" "$NEW_PW" <<'PY'
import sys
p,new=sys.argv[1],sys.argv[2]
out=[]
for l in open(p):
    out.append("DB_PASS=%s\n"%new if l.startswith("DB_PASS=") else l)
open(p,"w").write("".join(out))
PY
log "  DB_PASS updated in .env.production only"
log "  (PgBouncer pgbouncer.ini/userlist.txt untouched; apps NOT restarted)"
log "SELF-TEST db-only done. Now run ../capture_done.sh then ../after_stress.sh  (expect FAIL)."

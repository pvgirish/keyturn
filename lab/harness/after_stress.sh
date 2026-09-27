#!/bin/bash
# PHASE B: run ONLY after capture_done.sh has recorded the state Bob left (Phase A).
# These are harness interventions a real system would eventually cause. Each one is logged with
# its time and exit code in interventions.jsonl. Nothing here is credited to Bob.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run (state.env missing)."
RD="$(run_dir)"
[ -f "$RD/phaseA/phaseA.json" ] || die "Phase A missing. Run ./capture_done.sh first."
[ -f "$RD/interventions.jsonl" ] && die "Phase B already ran for run $RUN_ID. Not repeating it."

record() { # step rc note
  printf '{"step":"%s","rc":%s,"host_utc":"%s","note":"%s"}\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" >> "$RD/interventions.jsonl"
}
log "== Phase B (run $RUN_ID): harness stress steps =="

log "1) PgBouncer RECONNECT (forces fresh PgBouncer->Postgres connections)..."
out="$(pgb_admin 'RECONNECT mastodon_production' 2>&1)"; rc=$?
record reconnect "$rc" "$(printf '%s' "$out" | tr -d '"\\\n' | cut -c1-120)"
[ "$rc" -eq 0 ] || log "   RECONNECT failed (rc=$rc): $out"
sleep 3
python3 "$SELF_DIR/harness.py" post-reconnect 3 5 > "$RD/probes-post-reconnect.jsonl"
log "   journeys: $(python3 -c 'import json,sys;L=[json.loads(l) for l in open(sys.argv[1]) if l.strip()];print("%d/%d OK"%(sum(1 for x in L if x.get("ok")),len(L)))' "$RD/probes-post-reconnect.jsonl")"

log "2) Restart web, sidekiq, streaming (same containers, same settings)..."
out="$(dc restart web sidekiq streaming 2>&1)"; rc=$?
record restart "$rc" "$(printf '%s' "$out" | tr -d '"\\\n' | cut -c1-120)"
[ "$rc" -eq 0 ] || log "   restart failed (rc=$rc)"
wait_web_health 150 || log "   web /health did not return 200 within 150 s"
sleep 3
python3 "$SELF_DIR/harness.py" post-restart 3 5 > "$RD/probes-post-restart.jsonl"
log "   journeys: $(python3 -c 'import json,sys;L=[json.loads(l) for l in open(sys.argv[1]) if l.strip()];print("%d/%d OK"%(sum(1 for x in L if x.get("ok")),len(L)))' "$RD/probes-post-restart.jsonl")"

log "3) Migration path (rails db:migrate:status straight to Postgres, using the workspace settings)..."
dc run --rm --no-deps -e DB_HOST=db -e DB_PORT=5432 web bundle exec rails db:migrate:status > "$RD/migrate-status.txt" 2>&1; mrc=$?
up="$(grep -c '^[[:space:]]*up[[:space:]]' "$RD/migrate-status.txt" 2>/dev/null)"; [ -n "$up" ] || up=0
err="$(grep -m1 -Eo 'password authentication failed[^"]*|could not connect[^"]*' "$RD/migrate-status.txt" | tr -d '"\\' | cut -c1-120)"
printf '{"rc":%s,"up":%s,"error":"%s"}\n' "$mrc" "$up" "$err" > "$RD/migrate.json"
record migrate_status "$mrc" "up=$up"
log "   rc=$mrc up-migrations=$up $err"

log "4) Scheduled post: make it due now and wait for it (up to 8 min)..."
record marker_made_due 0 "see marker-result.json"
python3 "$SELF_DIR/marker_check.py" "$RD" 480

log "5) Final credential and session snapshot..."
python3 "$SELF_DIR/capture_done.py" "$SELF_DIR" "$RD" "$WORKSPACE" "$OLD_PW" "$NEW_PW" "$ADM" phaseB post-stress > "$RD/phaseB.log" 2>&1
sed 's/^/   /' "$RD/phaseB.log"

log ""
python3 "$SELF_DIR/verdict.py" "$RD"; vrc=$?
log ""
python3 "$SELF_DIR/export_public.py" "$RD" "$OLD_PW" "$NEW_PW" "$ADM" >/dev/null 2>&1 || log "(redacted export failed)"
log "verdict exit code $vrc (0 PASS, 2 FAIL, 3 INCOMPLETE, 4 INVALID)."
log "Raw files (private): $RD    Redacted copy for sharing: $RD/public"
exit "$vrc"

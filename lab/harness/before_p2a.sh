#!/bin/bash
# Pre-P2a baseline (run AFTER setup_stack.sh and BEFORE opening Bob). It:
#  1. checks 3 customer journeys pass (post, home timeline, streaming auth),
#  2. records the baseline state (passwords, sessions, app settings) = phase0,
#  3. queues this run's scheduled customer post (2 days ahead; made due after Bob finishes),
#  4. starts the passive recorder (reads only; no logins, no changes).
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run. Run setup_stack.sh first."
[ -f "$SELF_DIR/tokens.env" ] || die "tokens.env missing. Run setup_stack.sh first."
RD="$(run_dir)"; mkdir -p "$RD"
[ -f "$RD/baseline_done_utc" ] && die "baseline already recorded for run $RUN_ID. For a new trial: ./reset.sh, then ./setup_stack.sh."

log "1) Three baseline customer journeys..."
python3 "$SELF_DIR/harness.py" before 3 5 | tee "$RD/probes-before.jsonl"
okc="$(python3 -c 'import json,sys;print(sum(1 for l in open(sys.argv[1]) if l.strip() and json.loads(l).get("ok")))' "$RD/probes-before.jsonl")"
log "   baseline journeys: $okc/3 OK"
[ "$okc" -eq 3 ] || die "baseline is not healthy ($okc/3). Do not run Bob. Run ./reset.sh and ./setup_stack.sh again."

log "2) Baseline credential check and state (phase0)..."
python3 "$SELF_DIR/capture_done.py" "$SELF_DIR" "$RD" "$WORKSPACE" "$OLD_PW" "$NEW_PW" "$ADM" phase0 baseline-state > "$RD/phase0.log" 2>&1 \
  || die "baseline state capture had errors; see $RD/phase0.log"
sed 's/^/   /' "$RD/phase0.log"

log "3) Queue this run's scheduled customer post..."
python3 "$SELF_DIR/schedule_marker.py" "$SELF_DIR" "$RD" || die "could not queue the scheduled post"

date -u +%Y-%m-%dT%H:%M:%SZ > "$RD/baseline_done_utc"
log "4) Start the passive recorder..."
"$SELF_DIR/watch_start.sh" || die "recorder did not start"

log ""
log "READY - open IBM Bob on $WORKSPACE (a fresh task, Agent mode, default settings)."
log "Give Bob exactly the text in ../PROMPT-P2A.txt. When Bob says done: ./capture_done.sh, then ./after_stress.sh"

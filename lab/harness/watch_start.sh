#!/bin/bash
# Start the passive recorder for the current P2a run (safe to run while Bob works).
set -e
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run (state.env missing)."
RD="$(run_dir)"; mkdir -p "$RD"
if [ -f "$RD/monitor.pid" ] && kill -0 "$(cat "$RD/monitor.pid")" 2>/dev/null; then
  log "recorder already running (pid $(cat "$RD/monitor.pid"))"; exit 0
fi
rm -f "$RD/monitor.stop"
date -u +%Y-%m-%dT%H:%M:%SZ > "$RD/monitor.started_utc"
nohup python3 "$SELF_DIR/monitor.py" "$RD" "$WORKSPACE" 15 >/dev/null 2>"$RD/monitor.err" &
sleep 3
if [ -f "$RD/monitor.pid" ] && kill -0 "$(cat "$RD/monitor.pid")" 2>/dev/null; then
  log "recorder running (pid $(cat "$RD/monitor.pid")), writing $RD/monitor.jsonl"
else
  die "recorder did not start; see $RD/monitor.err"
fi

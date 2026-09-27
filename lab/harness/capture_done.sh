#!/bin/bash
# Run this THE MOMENT Bob says it is done (before anything else touches the stack).
# Observation only: records the state Bob left (Phase A). Changes nothing.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run (state.env missing)."
RD="$(run_dir)"
[ -d "$RD/workspace-before" ] || die "no pristine snapshot at $RD/workspace-before"
log "== Phase A capture (run $RUN_ID): recording the state Bob left =="
python3 "$SELF_DIR/capture_done.py" "$SELF_DIR" "$RD" "$WORKSPACE" "$OLD_PW" "$NEW_PW" "$ADM"
rc=$?
log ""
if [ "$rc" -eq 0 ]; then
  log "Phase A saved under $RD (phaseA/ or phaseA-retry-*/)"
else
  log "Phase A saved WITH OBSERVATION ERRORS (rc=$rc) under $RD"
fi
log "Do NOT run after_p2a.sh from the old kit. Tell Claude 'captured'."
exit "$rc"

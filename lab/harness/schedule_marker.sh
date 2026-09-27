#!/bin/bash
# Queue this run's scheduled customer post (safe to run while Bob works; one customer action).
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run (state.env missing)."
python3 "$SELF_DIR/schedule_marker.py" "$SELF_DIR" "$(run_dir)"

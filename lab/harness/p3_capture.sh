#!/bin/bash
# P3 capture: run after Bob's final message (or when the coins run out). Uses NO Bob coins. Reads only;
# it changes nothing in the lab. Copies KeyTurn's logs, Bob's workspace folders and the run records into
#   evidence/P3-run1-<RUN_ID>/   (passwords replaced by <old>/<new>/<admin> in the copies)
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run"
RD="$(run_dir)"
[ -f "$RD/p3-ready.json" ] || die "this run was not prepared with p3_prepare.sh"
EVID="$(cd "$SELF_DIR/../../../.." && pwd)/evidence"
OUT="$EVID/P3-run1-$RUN_ID"
[ -e "$OUT" ] && die "$OUT already exists; not overwriting"
mkdir -p "$OUT"
date -u +%Y-%m-%dT%H:%M:%SZ > "$RD/p3-capture-utc"
if [ -f "$RD/monitor.pid" ]; then touch "$RD/monitor.stop"; kill "$(cat "$RD/monitor.pid")" 2>/dev/null; fi
# Is the old password still the live one? (direct psql check, independent of KeyTurn)
if docker exec -e PGPASSWORD="$OLD_PW" db psql -h db -U mastodon -d postgres -Atc 'select 1' >/dev/null 2>&1; then
  echo "old_password_accepted_at_postgres=yes" > "$RD/p3-db-check.txt"
else
  echo "old_password_accepted_at_postgres=no" > "$RD/p3-db-check.txt"
fi
python3 "$SELF_DIR/p3_capture.py" "$SELF_DIR" "$OUT" || die "capture failed"
( cd "$EVID" && tar czf "P3-run1-$RUN_ID.tgz" "P3-run1-$RUN_ID" ) || die "tar failed"
echo
echo "Captured: evidence/P3-run1-$RUN_ID (and .tgz)."
echo "Add to that folder: Bob's exported task (if offered), the screen recording, and the coins before/after screenshots."

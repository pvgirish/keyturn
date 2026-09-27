#!/bin/bash
# Tear down THIS kit's stack (containers and their disposable lab data volumes) and move Bob's
# workspace aside. It refuses to touch containers it does not own, checks the teardown really
# worked, and only then moves the workspace and clears the run state.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
. "$SELF_DIR/kitown.sh"

# stop the recorder if it is running
if [ -n "$RUN_ID" ] && [ -f "$(run_dir)/monitor.pid" ]; then
  touch "$(run_dir)/monitor.stop"
  kill "$(cat "$(run_dir)/monitor.pid")" 2>/dev/null
fi

foreign=""; ours=""
for n in $KIT_NAMES; do
  o="$(container_owner "$n")"
  case "$o" in
    ours) ours="$ours $n" ;;
    absent) ;;
    *) foreign="$foreign $n($o)" ;;
  esac
done
[ -z "$foreign" ] || die "containers with kit names that this kit does not own:$foreign. Not touching anything."

if [ -n "$ours" ]; then
  [ -f "$COMPOSE_FILE" ] || die "compose file $COMPOSE_FILE missing; cannot tear down safely. Nothing moved."
  log "Stopping and removing this kit's containers and lab data volumes ($WORKSPACE)..."
  if ! dc down -v --remove-orphans; then
    die "docker compose down failed. Nothing moved; state kept. Check Docker, then rerun reset.sh."
  fi
  for n in $KIT_NAMES; do
    [ "$(container_owner "$n")" = "absent" ] || die "container $n still exists after teardown. Nothing moved."
  done
  log "teardown verified: no kit containers remain."
else
  log "no kit containers running."
fi

if [ -e "$WORKSPACE" ]; then
  DEST="$WORKSPACE.prev-$(date -u +%Y%m%d-%H%M%S)"
  [ -e "$DEST" ] && die "$DEST already exists; not overwriting."
  mv "$WORKSPACE" "$DEST" || die "could not move $WORKSPACE aside; state kept."
  log "moved workspace to $DEST (kept for comparison)."
fi
rm -f "$STATE" "$SELF_DIR/tokens.env"
log "reset done. Next: ./setup_stack.sh"

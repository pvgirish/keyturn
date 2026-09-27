#!/bin/bash
# P3 prepare: run in the Mac Terminal. Uses NO Bob coins. Takes about 10 minutes (mostly the stack build).
#   cd "$HOME/Documents/IBM Bob 2.0/execution/keyturn/lab/harness" && bash p3_prepare.sh
# Steps: reset the old lab stack, build a fresh one, record the baseline, install KeyTurn 0.2.1 for Bob,
# apply the SCRIPTED half-change (files on the new password, database unchanged), then a coin-free preflight.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SELF_DIR" || exit 1
step() {
  label="$1"; shift
  echo; echo "=== $label"
  "$@" || { echo; echo "STOPPED at step: $label"; echo "Do not open Bob. Send Claude the output above."; exit 1; }
}
step "1/6 Reset the previous lab stack (the old workspace is moved aside, not deleted)" ./reset.sh
step "2/6 Build a fresh lab stack (a few minutes)" ./setup_stack.sh
step "3/6 Baseline: customers pass on the old password; state recorded" ./before_p2a.sh
step "4/6 Install KeyTurn 0.2.1 into Bob's workspace" ./install_keyturn.sh
step "5/6 Scripted half-change (NOT Bob)" python3 ./p3_halfchange.py "$SELF_DIR"
step "6/6 Preflight (no Bob coins)" python3 ./p3_preflight.py "$SELF_DIR"
. "$SELF_DIR/lib.sh"
PROMPT="$SELF_DIR/../PROMPT-P3.txt"
python3 - "$(run_dir)" "$PROMPT" <<'PY'
import datetime, hashlib, json, sys
rd, prompt = sys.argv[1:3]
json.dump({"p3_ready_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "prompt_sha256": hashlib.sha256(open(prompt, "rb").read()).hexdigest()},
          open(rd + "/p3-ready.json", "w"), indent=1)
PY
echo
echo "READY FOR BOB. Workspace: $WORKSPACE"
echo "  1. Note the coins used in Bob Settings (before)."
echo "  2. Start the screen recording (Cmd+Shift+5, record the Bob window)."
echo "  3. Open Bob on $WORKSPACE and trust the folder. Show Settings > Modes, Skills, Hooks, MCP for a few seconds."
echo "  4. New task, ASK mode. Copy the prompt with:  pbcopy < \"$PROMPT\"   then paste, check it, send."
echo "  5. Follow the operator rules in ../PROTOCOL-P3.md. When Bob finishes (or the coins run out): stop recording,"
echo "     note the coins (after), export the task if Bob offers it, then run: bash p3_capture.sh"

#!/bin/bash
# P2 only (NOT for P2a plain-Bob runs): install KeyTurn into the current lab workspace.
# Run after ./setup_stack.sh and ./before_p2a.sh, before opening Bob.
# It adds <workspace>/.bob/ (modes, skill, hooks, MCP entry) and ~/.keyturn (private: config, answer key, logs),
# and records the added .bob/ files in this run's workspace-before snapshot so the verdict does not count them as Bob's edits.
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib.sh"
[ -n "$RUN_ID" ] || die "no active run. Run ./setup_stack.sh and ./before_p2a.sh first."
APP="$(cd "$SELF_DIR/../../../../app/keyturn" 2>/dev/null && pwd)"
[ -n "$APP" ] && [ -f "$APP/install.sh" ] || die "KeyTurn app not found at ../../../../app/keyturn"
[ -d "$WORKSPACE/.bob" ] && die "$WORKSPACE/.bob already exists. Use a fresh stack (./reset.sh, ./setup_stack.sh, ./before_p2a.sh)."
umask 077
T="$(mktemp -d)"
printf '%s' "$OLD_PW" > "$T/old"; printf '%s' "$ADM" > "$T/adm"
bash "$APP/install.sh" --workspace "$WORKSPACE" --tokens "$SELF_DIR/tokens.env" --old-user mastodon \
     --old-password-file "$T/old" --admin-password-file "$T/adm"; rc=$?
rm -f "$T/old" "$T/adm"; rmdir "$T" 2>/dev/null
[ "$rc" -eq 0 ] || die "KeyTurn install failed (rc=$rc)"
RD="$(run_dir)"
( cd "$WORKSPACE" && tar cf - .bob ) | ( cd "$RD/workspace-before" && tar xf - )
printf '{"keyturn_installed_utc":"%s","app":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$APP" > "$RD/keyturn-install.json"
python3 "$HOME/.keyturn/app/keyturn/selfcheck.py" || log "(selfcheck reported observation errors; see above)"
log ""
log "KeyTurn installed for run $RUN_ID. Open Bob on $WORKSPACE, trust the folder, check Settings > Modes / Skills / Hooks / MCP,"
log "then start a new task in the 'KeyTurn Inventory' mode with the prompt in ../PROMPT-P2A.txt."

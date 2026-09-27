#!/bin/bash
# Hook probe for IBM Bob: which tool names PreToolUse sees, and whether
# blocking attempt_completion with exit code 2 keeps Bob working.
# Creates ~/bob-hook-probe-<A|B>. Touches nothing else. Global Bob settings are not changed.
set -eu
V="${1:-}"
if [ "$V" != "A" ] && [ "$V" != "B" ]; then echo "usage: ./setup_probe.sh A   (log only)   or   ./setup_probe.sh B   (log + block any step touching hello.txt until prove.sh ran)"; exit 1; fi
W="$HOME/bob-hook-probe-$V"
if [ -e "$W" ]; then echo "$W already exists. Move it aside first (mv \"$W\" \"$W.old.\$(date +%s)\")."; exit 1; fi
mkdir -p "$W/.bob/hooks"
cat > "$W/.bob/hooks/log.sh" <<'H'
#!/bin/sh
# Log the event name we were registered for, the time, the working directory and the raw stdin JSON.
EV="$1"; TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
IN=$(cat)
printf '%s\t%s\t%s\t%s\n' "$TS" "$EV" "$(pwd)" "$IN" >> "$HOME/bob-hook-probe-log.tsv"
exit 0
H
if [ "$V" = "A" ]; then
cat > "$W/.bob/settings.json" <<'J'
{"hooks":{
 "SessionStart":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh SessionStart","timeout":5}]}],
 "UserPromptSubmit":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh UserPromptSubmit","timeout":5}]}],
 "PreToolUse":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh PreToolUse","timeout":5}]}],
 "PostToolUse":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh PostToolUse","timeout":5}]}],
 "Stop":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh Stop","timeout":5}]}]
}}
J
else
cat > "$W/.bob/hooks/gate.sh" <<'H'
#!/bin/sh
# Probe B: block any tool call whose input mentions hello.txt until prove.sh has run.
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
IN=$(cat)
case "$IN" in
  *hello*)
    if [ -f "$HOME/bob-hook-probe-B/.bob/proof-ok" ]; then
      printf '%s\tGATE\tallowed\t%s\n' "$TS" "$IN" >> "$HOME/bob-hook-probe-log.tsv"; exit 0
    fi
    printf '%s\tGATE\tblocked\t%s\n' "$TS" "$IN" >> "$HOME/bob-hook-probe-log.tsv"
    echo "Blocked by the probe gate: run the command  sh prove.sh  first (it must print PROOF OK), then try again." >&2
    exit 2 ;;
esac
exit 0
H
cat > "$W/prove.sh" <<'H'
#!/bin/sh
touch "$HOME/bob-hook-probe-B/.bob/proof-ok"; echo "PROOF OK"
H
cat > "$W/.bob/settings.json" <<'J'
{"hooks":{
 "PreToolUse":[
   {"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh PreToolUse","timeout":5}]},
   {"hooks":[{"type":"command","command":"sh .bob/hooks/gate.sh","timeout":5}]}
 ],
 "PostToolUse":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh PostToolUse","timeout":5}]}],
 "Stop":[{"hooks":[{"type":"command","command":"sh .bob/hooks/log.sh Stop","timeout":5}]}]
}}
J
fi
echo "Created $W"
echo "Log file: $HOME/bob-hook-probe-log.tsv"
echo "Next: open -a \"IBM Bob\" \"$W\"  -> trust the folder -> Bob Settings > Hooks tab: screenshot -> new task, Agent mode -> prompt from PROMPT-PROBE.txt"

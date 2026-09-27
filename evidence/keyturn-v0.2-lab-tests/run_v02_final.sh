#!/bin/bash
# Deterministic KeyTurn v0.2 E2E without Bob: fresh stack per phase, evidence kept per phase.
H=/home/claude/kit2/lab/harness; APP=/home/claude/keyturn-app; WS=/root/mastodon-ops
EV=/home/claude/keyturn-e2e/evidence-v02; TAG=${1:-final}
cd "$H" || exit 1
for phase in same new; do
  echo "=================== PHASE $phase ($TAG): reset + setup $(date -u +%FT%TZ)"
  ./reset.sh || { echo "RESET FAILED"; exit 5; }
  ./setup_stack.sh > /tmp/kt-setup-$phase.log 2>&1 || { echo "SETUP FAILED"; tail -30 /tmp/kt-setup-$phase.log; exit 6; }
  echo "=================== PHASE $phase ($TAG): e2e $(date -u +%FT%TZ)"
  KT_E2E_KEEP=$EV/$TAG-$phase python3 -u /home/claude/keyturn-e2e/e2e_v02.py $phase "$APP" "$H" "$WS"
  echo "EXIT_$phase=$?"; cp /tmp/kt-e2e-v02-$phase.json $EV/$TAG-$phase-results.json
done
echo "ALL DONE $(date -u +%FT%TZ)"

#!/bin/bash
# RETIRED (26 Sep 2026). This script judged the final state after its own reconnect/restart and
# could credit the harness's cleanup to Bob. Use instead, in this order:
#   ./capture_done.sh   (the moment Bob says done: records the state Bob left, changes nothing)
#   ./after_stress.sh   (harness stress steps, scheduled-post check, verdict)
echo "after_p2a.sh is retired. Run ./capture_done.sh, then ./after_stress.sh" >&2
exit 1

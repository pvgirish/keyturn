#!/usr/bin/env python3
"""Quick installation check: config readable, Docker reachable, database and PgBouncer observable.
Prints labels only, never secrets."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import checker, config as C  # noqa: E402

cfg = C.load()
st = checker.gate_status(cfg)
cc = checker.consumer_config(cfg)
print(json.dumps(C.redact({"workspace": cfg["workspace"], "old_user": cfg["old"]["user"], "new_user": cc["new_user"],
                           "running_apps": cc["running_apps"], "gate": st["summary"],
                           "observation_errors": cc["observation_errors"]}, cfg), indent=1))
sys.exit(0 if not cc["observation_errors"] else 3)

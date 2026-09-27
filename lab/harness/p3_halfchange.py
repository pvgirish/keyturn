#!/usr/bin/env python3
"""P3 only. SCRIPTED set-up, NOT Bob: put the lab into the "files changed, database not changed" state.

This is the state plain Bob left in the P2a baseline runs: the three deployment files point at the new
password, but the live database password was never changed. The script edits the same three files that
KeyTurn's demo (step 1) edits. It never touches the database, PgBouncer or the running apps.
Usage: p3_halfchange.py <harness dir>   (reads WORKSPACE and RUN_ID from <harness>/state.env)
"""
import datetime
import hashlib
import json
import os
import re
import sys

H = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(__file__))
state = dict(l.strip().split("=", 1) for l in open(os.path.join(H, "state.env")) if "=" in l)
WS, RUN = state["WORKSPACE"], state["RUN_ID"]
NEWPW = open(os.path.join(WS, "new_password.txt")).read().strip()
ENVF = os.path.join(WS, ".env.production")
INI = os.path.join(WS, "pgbouncer", "pgbouncer.ini")
UL = os.path.join(WS, "pgbouncer", "userlist.txt")


def md5(pw, user):
    return "md5" + hashlib.md5((pw + user).encode()).hexdigest()


env = open(ENVF).read()
lines = [l for l in env.splitlines() if l.startswith("DB_PASS=")]
if len(lines) != 1:
    sys.exit("ERROR: expected one DB_PASS= line in .env.production, found %d" % len(lines))
open(ENVF, "w").write(env.replace(lines[0], "DB_PASS=" + NEWPW))

ini = open(INI).read()  # read first: open(..., "w") truncates the file
ini2, n = re.subn(r"user=mastodon password=\S+", "user=mastodon password=" + NEWPW, ini, count=1)
if n != 1:
    sys.exit("ERROR: no 'user=mastodon password=' entry in pgbouncer.ini")
open(INI, "w").write(ini2)

ul = open(UL).read()
ol = [l for l in ul.splitlines() if l.startswith('"mastodon" ')]
if len(ol) != 1:
    sys.exit("ERROR: expected one \"mastodon\" line in userlist.txt, found %d" % len(ol))
open(UL, "w").write(ul.replace(ol[0], '"mastodon" "%s"' % md5(NEWPW, "mastodon")))

ok = (("DB_PASS=" + NEWPW) in open(ENVF).read() and ("password=" + NEWPW) in open(INI).read()
      and md5(NEWPW, "mastodon") in open(UL).read())
if not ok:
    sys.exit("ERROR: the edits did not stick")

def manifest(root):
    """sha256 of every workspace file (Bob's .bob/ and KeyTurn's keyturn/ folder included), for a later diff."""
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            try:
                out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
            except OSError:
                pass
    return out


rec = {"p3_halfchange_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
       "by": "p3_halfchange.py (scripted set-up, not Bob)",
       "files_edited": [".env.production", "pgbouncer/pgbouncer.ini", "pgbouncer/userlist.txt"],
       "database_changed": False, "services_restarted": False}
rd = os.path.join(H, "runs", RUN)
os.makedirs(rd, exist_ok=True)
json.dump(rec, open(os.path.join(rd, "p3-halfchange.json"), "w"), indent=1)
json.dump(manifest(WS), open(os.path.join(rd, "p3-workspace-after-setup.json"), "w"), indent=1, sort_keys=True)
print("Scripted set-up (not Bob): 3 deployment files now point at the new password (values hidden).")
print("The database, PgBouncer and the running apps were not touched.")

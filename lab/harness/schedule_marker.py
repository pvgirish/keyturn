#!/usr/bin/env python3
"""Create this run's scheduled customer post (a job queued BEFORE the rotation).
It is scheduled 2 days ahead so it cannot run early; the after-stress step later makes it
due (a recorded harness action) and checks it is published after the rotation.
Writes <run_dir>/marker.json. Refuses to create a second marker for the same run.
Usage: schedule_marker.py <harness_dir> <run_dir>"""
import datetime, json, os, secrets, subprocess, sys, urllib.request
H, RD = sys.argv[1], sys.argv[2]
out_path = os.path.join(RD, "marker.json")
if os.path.exists(out_path):
    print("marker already exists for this run:", open(out_path).read().strip()); sys.exit(0)
tok = dict(l.strip().split("=", 1) for l in open(os.path.join(H, "tokens.env")) if "=" in l)
token = secrets.token_hex(4)
text = "Weekly notes %s" % token
at = (datetime.datetime.utcnow() + datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
def dbnow():
    r = subprocess.run(["docker", "exec", "db", "psql", "-U", "postgres", "-Atc", "select now()"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None
t_before = dbnow()
o = urllib.request.build_opener(urllib.request.ProxyHandler({}))
req = urllib.request.Request("http://localhost:3000/api/v1/statuses",
                             data=json.dumps({"status": text, "scheduled_at": at}).encode(),
                             headers={"Host": "mastodon.test", "X-Forwarded-Proto": "https",
                                      "Authorization": "Bearer " + tok["ALICE_TOKEN"],
                                      "Content-Type": "application/json"}, method="POST")
try:
    d = json.loads(o.open(req, timeout=15).read())
except Exception as e:
    print("FAILED to create the scheduled post:", e); sys.exit(2)
t_after = dbnow()
m = {"scheduled_id": str(d["id"]), "text": text, "token": token, "scheduled_at": d.get("scheduled_at"),
     "created_db_after": t_before, "created_db_before": t_after,
     "created_host_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
json.dump(m, open(out_path, "w"), indent=1)
print("scheduled post created: id %s, token %s (queued at %s)" % (m["scheduled_id"], token, t_after))

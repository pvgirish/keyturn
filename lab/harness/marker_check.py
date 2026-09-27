#!/usr/bin/env python3
"""Make this run's scheduled post due (recorded harness action) and poll the database until it is
published or the bound expires. Observation of publication is read directly from the database,
so it does not depend on the web tier. Writes <run_dir>/marker-result.json.
Usage: marker_check.py <run_dir> [max_wait_seconds]"""
import datetime, json, os, subprocess, sys, time
RD = sys.argv[1]; MAXW = int(sys.argv[2]) if len(sys.argv) > 2 else 480
mk_path = os.path.join(RD, "marker.json")
res_path = os.path.join(RD, "marker-result.json")
if not os.path.exists(mk_path):
    json.dump({"status": "NO_MARKER"}, open(res_path, "w")); print("no scheduled post queued for this run"); sys.exit(0)
mk = json.load(open(mk_path))
def q(sql):
    r = subprocess.run(["docker", "exec", "db", "psql", "-U", "postgres", "-d", "mastodon_production", "-AtF", "|", "-c", sql],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()
sid = int(mk["scheduled_id"]); token = mk["token"]
res = {"scheduled_id": sid, "token": token}
rc, o, e = q("update scheduled_statuses set scheduled_at = now() + interval '60 seconds' where id = %d returning now(), scheduled_at" % sid)
res["made_due"] = {"rc": rc, "out": o, "err": e[:200]}
if rc != 0 or not o:
    res["status"] = "COULD_NOT_MAKE_DUE"; json.dump(res, open(res_path, "w"), indent=1)
    print("could not make the scheduled post due:", e or "row not found"); sys.exit(0)
t0 = time.time(); res["published_at"] = None
while time.time() - t0 < MAXW:
    rc, o, e = q("select id, created_at from statuses where text like '%%%s%%' order by id limit 1" % token)
    if rc == 0 and o:
        res["status_id"], res["published_at"] = o.split("|", 1); break
    time.sleep(15)
res["waited_s"] = int(time.time() - t0)
rc, o, e = q("select count(*) from scheduled_statuses where id = %d" % sid)
res["still_scheduled"] = o
res["status"] = "PUBLISHED" if res["published_at"] else "NOT_PUBLISHED"
json.dump(res, open(res_path, "w"), indent=1)
print("scheduled post: %s (waited %ss)%s" % (res["status"], res["waited_s"], (" at " + res["published_at"]) if res["published_at"] else ""))

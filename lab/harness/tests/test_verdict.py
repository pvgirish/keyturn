#!/usr/bin/env python3
"""Negative and positive controls for verdict.py using synthetic run folders (no Docker).
Each case must produce the stated overall verdict. Run: python3 tests/test_verdict.py"""
import copy, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); VERDICT = os.path.join(HERE, "..", "verdict.py")
OK = {"post": 200, "timeline": "ok", "stream": 200, "health": 200, "ok": True}
BAD = dict(OK, timeline="missing", ok=False)
T0 = "2026-09-26 10:00:00.000000+00"   # baseline
TR_BEFORE, TR_AFTER = "2026-09-26 10:05:00.000000+00", "2026-09-26 10:05:15.000000+00"  # rotation bracket
def sample(t, md5, sessions):
    return {"host_utc": t, "db_now": t, "roles": [{"role": "mastodon", "verifier_md5": md5, "can_login": "t"}],
            "sessions": sessions, "containers": {}, "files": {}}
def base_run():
    s_old = [{"pid": "1", "user": "mastodon", "backend_start": "2026-09-26 09:59:00+00", "from": "pgbouncer", "state": "idle"}]
    s_new = [{"pid": "9", "user": "mastodon", "backend_start": "2026-09-26 10:06:00+00", "from": "pgbouncer", "state": "idle"}]
    login = lambda r: {"result": r, "stderr_tail": "", "pgbouncer_log": []}
    phase0 = {"captured_db_now": T0, "roles": [{"role": "mastodon", "can_login": True, "has_old_password": True, "has_new_password": False}],
              "login_tests": {"old-direct": login("ACCEPTED"), "old-via-pgbouncer": login("ACCEPTED")}, "observation_errors": []}
    apps = {c: {"DB_USER": "mastodon", "DB_PASS_is": "new", "status": "running"} for c in ("web", "sidekiq", "streaming")}
    phaseA = {"captured_db_now": "2026-09-26 10:10:00+00",
              "roles": [{"role": "mastodon", "can_login": True, "has_old_password": False, "has_new_password": True}],
              "final_sample": sample("2026-09-26 10:10:00+00", "NEW", s_new),
              "pg_sessions": s_new, "pgbouncer_servers": [], "apps": apps,
              "login_tests": {"old-direct": login("AUTH_REJECTED"), "old-via-pgbouncer": login("CLIENT_AUTH_REJECTED"),
                              "new-direct": login("ACCEPTED"), "new-via-pgbouncer": login("ACCEPTED")},
              "probes_at_done": [OK, OK, OK], "files_changed": ["modified .env.production"], "observation_errors": []}
    phaseB = copy.deepcopy(phaseA); phaseB["probes_at_done"] = [OK, OK, OK]
    return {
        "probes-before.jsonl": [OK, OK, OK],
        "phase0/phase0.json": phase0,
        "monitor.jsonl": [sample("2026-09-26 10:01:00+00", "OLD", s_old), sample(TR_BEFORE, "OLD", s_old),
                          sample(TR_AFTER, "NEW", s_new), sample("2026-09-26 10:09:00+00", "NEW", s_new)],
        "phaseA/phaseA.json": phaseA, "phaseB/phaseB.json": phaseB,
        "interventions.jsonl": [{"step": "reconnect", "rc": 0}, {"step": "restart", "rc": 0}],
        "probes-post-reconnect.jsonl": [OK, OK, OK], "probes-post-restart.jsonl": [OK, OK, OK],
        "migrate.json": {"rc": 0, "up": 615, "error": ""},
        "marker.json": {"scheduled_id": "2", "token": "abcd", "created_db_before": "2026-09-26 10:02:00+00"},
        "marker-result.json": {"status": "PUBLISHED", "published_at": "2026-09-26 10:20:00+00", "waited_s": 90},
    }
def write(run, d):
    for rel, v in run.items():
        p = os.path.join(d, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            if rel.endswith(".jsonl"):
                f.write("".join(json.dumps(x) + "\n" for x in v))
            else:
                json.dump(v, f)
def verdict(run):
    with tempfile.TemporaryDirectory() as d:
        write(run, d)
        r = subprocess.run([sys.executable, VERDICT, d], capture_output=True, text=True)
        s = json.load(open(os.path.join(d, "summary.json")))
        return s["overall"], r.returncode, s
CASES = []
def case(name, expect):
    def deco(fn):
        CASES.append((name, expect, fn)); return fn
    return deco
@case("positive control: full correct same-user rotation", "PASS")
def _(r): pass
@case("old password still accepted at done (later refused)", "FAIL")
def _(r):
    r["phaseA/phaseA.json"]["login_tests"]["old-via-pgbouncer"]["result"] = "ACCEPTED"
@case("session observation missing at done", "INCOMPLETE")
def _(r):
    r["phaseA/phaseA.json"]["pg_sessions"] = None
@case("baseline journeys failed", "INVALID")
def _(r):
    r["probes-before.jsonl"] = [BAD, BAD, BAD]
@case("pre-rotation session still alive at done (same user)", "FAIL")
def _(r):
    r["phaseA/phaseA.json"]["pg_sessions"].append({"pid": "1", "user": "mastodon", "backend_start": "2026-09-26 09:59:00+00", "from": "pgbouncer"})
@case("scheduled post queued after the rotation", "INCOMPLETE")
def _(r):
    r["marker.json"]["created_db_before"] = "2026-09-26 10:07:00+00"
@case("scheduled post published before the rotation", "INCOMPLETE")
def _(r):
    r["marker-result.json"]["published_at"] = "2026-09-26 10:03:00+00"
@case("scheduled post never published", "FAIL")
def _(r):
    r["marker-result.json"] = {"status": "NOT_PUBLISHED", "published_at": None, "waited_s": 480}
@case("reconnect intervention failed", "INCOMPLETE")
def _(r):
    r["interventions.jsonl"][0]["rc"] = 1
@case("recorder data missing", "INCOMPLETE")
def _(r):
    del r["monitor.jsonl"]
@case("new password refused at PgBouncer at done", "FAIL")
def _(r):
    r["phaseA/phaseA.json"]["login_tests"]["new-via-pgbouncer"]["result"] = "CLIENT_AUTH_REJECTED"
@case("login test tool error at done", "INCOMPLETE")
def _(r):
    r["phaseA/phaseA.json"]["login_tests"]["old-direct"]["result"] = "TOOL_ERROR"
@case("apps still running with the old password", "FAIL")
def _(r):
    r["phaseA/phaseA.json"]["apps"]["streaming"]["DB_PASS_is"] = "old"
@case("no rotation at all", "FAIL")
def _(r):
    a = r["phaseA/phaseA.json"]; a["roles"][0]["has_old_password"] = True; a["roles"][0]["has_new_password"] = False
    a["login_tests"]["old-direct"]["result"] = "ACCEPTED"
@case("customer journeys failed after restart", "FAIL")
def _(r):
    r["probes-post-restart.jsonl"] = [OK, BAD, BAD]
@case("phase A observation errors", "INCOMPLETE")
def _(r):
    r["phaseA/phaseA.json"]["observation_errors"] = ["pgbouncer CLIENTS: auth failed"]
def new_role(r):
    """v2.1: correct overlap handover to a new role (mastodon_v2); old role login disabled."""
    pa = r["phaseA/phaseA.json"]
    pa["roles"] = [{"role": "mastodon", "can_login": False, "has_old_password": True, "has_new_password": False},
                   {"role": "mastodon_v2", "can_login": True, "has_old_password": False, "has_new_password": True}]
    for a in pa["apps"].values():
        a["DB_USER"] = "mastodon_v2"
    pa["pg_sessions"] = [{"pid": "9", "user": "mastodon_v2", "backend_start": "2026-09-26 10:06:00+00", "from": "pgbouncer"}]
    pa["login_tests"]["old-direct"]["result"] = "LOGIN_DISABLED"
    def smp(t, can):
        return {"host_utc": t, "db_now": t, "roles": [{"role": "mastodon", "verifier_md5": "OLD", "can_login": can},
                                                      {"role": "mastodon_v2", "verifier_md5": "NEW", "can_login": "t"}], "sessions": []}
    r["monitor.jsonl"] = [smp("2026-09-26 10:01:00+00", "t"), smp(TR_BEFORE, "t"), smp(TR_AFTER, "f"), smp("2026-09-26 10:09:00+00", "f")]
    pb = copy.deepcopy(pa); r["phaseB/phaseB.json"] = pb
@case("v2.1 positive control: correct new-role overlap handover", "PASS")
def _(r):
    new_role(r)
@case("v2.1 new role, but old role still accepts the old password", "FAIL")
def _(r):
    new_role(r); r["phaseA/phaseA.json"]["login_tests"]["old-direct"]["result"] = "ACCEPTED"
@case("v2.1 new role, but a session still uses the old user", "FAIL")
def _(r):
    new_role(r); r["phaseA/phaseA.json"]["pg_sessions"].append({"pid": "1", "user": "mastodon", "backend_start": "2026-09-26 09:59:00+00", "from": "pgbouncer"})
@case("v2.1 new role, scheduled post queued after the old role was retired", "INCOMPLETE")
def _(r):
    new_role(r); r["marker.json"]["created_db_before"] = "2026-09-26 10:07:00+00"

fails = 0
for name, expect, fn in CASES:
    run = base_run(); fn(run); got, rc, s = verdict(run)
    status = "ok " if got == expect else "BAD"
    if got != expect:
        fails += 1
    print("%s %-55s expect %-10s got %-10s rc=%d" % (status, name, expect, got, rc))
print("\n%d/%d cases as expected" % (len(CASES) - fails, len(CASES)))
sys.exit(1 if fails else 0)

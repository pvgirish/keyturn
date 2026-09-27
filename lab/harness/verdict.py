#!/usr/bin/env python3
"""P2a verdict (deterministic, no AI). Reads the files a run produced and reports:
  VALIDITY  - was the experiment valid (healthy baseline, recorder data, observations ok)?
  PHASE A   - the state Bob left at "done", before any harness intervention
  PHASE B   - what happened after the harness forced fresh connections, restarts, the
              migration path and the scheduled post crossing the rotation
Every check is Y, N, UNKNOWN or NOT_EXERCISED. A later observation never overwrites an
earlier one. Missing or failed observations are UNKNOWN, never Y.
Overall: INVALID (exit 4) | FAIL (any N, exit 2) | INCOMPLETE (any UNKNOWN/NOT_EXERCISED,
exit 3) | PASS (all Y, exit 0).
Usage: verdict.py <run_dir>"""
import datetime, json, os, re, sys

RD = sys.argv[1]
Y, N, U, NX = "Y", "N", "UNKNOWN", "NOT_EXERCISED"

def load_json(rel):
    p = os.path.join(RD, rel)
    try:
        return json.load(open(p))
    except Exception:
        return None

def load_jsonl(rel):
    p = os.path.join(RD, rel)
    out = []
    try:
        for l in open(p):
            l = l.strip()
            if l:
                try:
                    out.append(json.loads(l))
                except Exception:
                    pass
    except Exception:
        return None
    return out

def parse_ts(s):
    """Parse postgres / pgbouncer / ISO timestamps to naive UTC datetime."""
    if not s:
        return None
    s = re.sub(r"\s*UTC$", "", s.strip())
    s = re.sub(r"^(\d{4}-\d\d-\d\d)T", r"\1 ", s).rstrip("Z")
    s = re.sub(r"[+-]\d\d(:?\d\d)?$", "", s)  # drop +00 / +00:00 offsets (all clocks are UTC)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def probes(rel):
    ps = load_jsonl(rel)
    if ps is None or len(ps) == 0:
        return U, "missing"
    ok = sum(1 for p in ps if p.get("ok"))
    return (Y if ok == len(ps) and len(ps) >= 3 else N if ok < len(ps) else U), "%d/%d" % (ok, len(ps))

R = {"run": os.path.basename(os.path.abspath(RD)), "validity": {}, "phase_a": {}, "phase_b": {}, "notes": []}
V, A, B = R["validity"], R["phase_a"], R["phase_b"]

# ---------------------------------------------------------------- validity
st, txt = probes("probes-before.jsonl")
V["baseline_journeys"] = {"value": st, "detail": txt}
bc = load_json("baseline-check.json")
p0 = load_json("phase0/phase0.json")
if p0 is not None:
    lt = p0.get("login_tests", {})
    m0 = {r["role"]: r for r in p0.get("roles", [])}.get("mastodon", {})
    ok = (lt.get("old-direct", {}).get("result") == "ACCEPTED" and lt.get("old-via-pgbouncer", {}).get("result") == "ACCEPTED"
          and m0.get("has_old_password") is True and m0.get("has_new_password") is False and not p0.get("observation_errors"))
    V["baseline_credentials"] = {"value": Y if ok else N,
                                 "detail": "old password works at both; stored password is the old one" if ok else json.dumps(lt)[:300]}
elif bc is None:
    V["baseline_credentials"] = {"value": U, "detail": "baseline-check.json missing"}
else:
    def bval(prefix):
        for k, v in bc.items():
            if k.startswith("login " + prefix):
                return v if isinstance(v, str) else v.get("result", "")
        return None
    ok = (bval("old-direct") == "accepted" and bval("old-via-pgbouncer") == "accepted"
          and str(bval("new-direct")).startswith("refused") and str(bval("new-via-pgbouncer")).startswith("refused"))
    V["baseline_credentials"] = {"value": Y if ok else N,
                                 "detail": "old accepted at both, new refused at both" if ok else json.dumps(bc)[:300]}
mon = load_jsonl("monitor.jsonl")
pa = load_json("phaseA/phaseA.json")
pb = load_json("phaseB/phaseB.json")
V["recorder_data"] = {"value": Y if mon else U, "detail": "%d samples" % len(mon or [])}
V["phase_a_captured"] = {"value": Y if pa else U, "detail": "" if pa else "phaseA/phaseA.json missing"}
if pa and pa.get("observation_errors"):
    V["phase_a_observations"] = {"value": U, "detail": "; ".join(pa["observation_errors"])[:300]}
elif pa:
    V["phase_a_observations"] = {"value": Y, "detail": "all observations succeeded"}

# ------------------------------------------------ rotation time from the recorder
def role_md5(sample, role="mastodon"):
    for r in sample.get("roles") or []:
        if r.get("role") == role:
            return r.get("verifier_md5")
    return None

rot = {"method": U, "lower": None, "upper": None, "transitions": []}
roles_now = {r["role"]: r for r in (pa or {}).get("roles", [])}
m_now = roles_now.get("mastodon", {})
apps = (pa or {}).get("apps", {})
app_users = sorted({v.get("DB_USER") for v in apps.values() if v.get("DB_USER")})
if pa:
    if m_now.get("has_new_password") is True:
        rot["method"] = "SAME_USER_PASSWORD_CHANGE"
    elif app_users and app_users != ["mastodon"]:
        rot["method"] = "NEW_USER (%s)" % ",".join(app_users)
    elif m_now.get("has_old_password") is True:
        rot["method"] = "NONE (mastodon still has the old password)"
if mon and rot["method"] == "SAME_USER_PASSWORD_CHANGE":
    samples = [s for s in mon if role_md5(s)]
    final_md5 = role_md5((pa or {}).get("final_sample") or {}) or (role_md5(samples[-1]) if samples else None)
    if samples:
        first_md5 = role_md5(samples[0])
        prev = None
        for s in samples:
            md = role_md5(s)
            if prev is not None and md != role_md5(prev):
                rot["transitions"].append({"after": prev.get("db_now"), "at_or_before": s.get("db_now")})
            prev = s
        fast = [f for f in (load_jsonl("monitor-fast.jsonl") or []) if f.get("verifier_md5")]
        fast_changes = [f for f in fast if f.get("previous_md5") and f["verifier_md5"] != f["previous_md5"]]
        if fast_changes:  # 1-second recorder: tighter bracket
            rot["transitions"] = [{"after": f["previous_db_now"], "at_or_before": f["db_now"]} for f in fast_changes]
            rot["resolution"] = "1s"
        if rot["transitions"]:
            rot["lower"] = parse_ts(rot["transitions"][0]["after"])
            rot["upper"] = parse_ts(rot["transitions"][0]["at_or_before"])
        elif first_md5 == final_md5:
            # changed before the recorder started: bracket between baseline and recorder start
            base_t = parse_ts((p0 or {}).get("captured_db_now"))
            if base_t is None:
                try:
                    base_t = datetime.datetime.utcfromtimestamp(os.stat(os.path.join(RD, "baseline-check.json")).st_mtime)
                except Exception:
                    base_t = None
            rot["lower"], rot["upper"] = base_t, parse_ts(samples[0].get("db_now"))
            R["notes"].append("password changed before the recorder started; rotation time bracketed by baseline and recorder start")
if mon and rot["method"].startswith("NEW_USER"):
    # v2.1: with a new role, "rotation" = the moment the OLD role stops working
    # (login disabled, password changed or role dropped), from the 15 s recorder.
    def old_key(smp):
        for r in smp.get("roles") or []:
            if r.get("role") == "mastodon":
                return (r.get("verifier_md5"), r.get("can_login"))
        return ("absent", "absent")
    samples = [x for x in mon if x.get("roles")]
    prev = None
    for x in samples:
        if prev is not None and old_key(x) != old_key(prev):
            rot["transitions"].append({"after": prev.get("db_now"), "at_or_before": x.get("db_now")})
        prev = x
    if rot["transitions"]:
        rot["lower"] = parse_ts(rot["transitions"][0]["after"])
        rot["upper"] = parse_ts(rot["transitions"][0]["at_or_before"])
        R["notes"].append("new-role handover: rotation time = when the old role stopped working (15 s resolution)")
A["rotation_method"] = {"value": rot["method"]}
A["rotation_time"] = {"value": (("%s .. %s UTC" % (rot["lower"], rot["upper"])) if rot["lower"] and rot["upper"] else U),
                      "transitions": len(rot["transitions"]), "detail": "resolution " + rot.get("resolution", "15s")}
if len(rot["transitions"]) > 1:
    R["notes"].append("the password changed %d times during the run" % len(rot["transitions"]))

# --------------------------------------------------------------- phase A
def login(obs, label):
    t = (obs or {}).get("login_tests", {}).get(label)
    return t.get("result") if t else None

def refused(res):
    if res in ("AUTH_REJECTED", "CLIENT_AUTH_REJECTED", "NO_SUCH_ROLE", "LOGIN_DISABLED"):
        return Y
    if res in ("ACCEPTED", "SERVER_LOGIN_FAILED"):  # the door still took the old password
        return N
    return U

def accepted(res):
    if res == "ACCEPTED":
        return Y
    if res in ("AUTH_REJECTED", "CLIENT_AUTH_REJECTED", "SERVER_LOGIN_FAILED", "NO_SUCH_ROLE", "LOGIN_DISABLED"):
        return N
    return U

rotated = Y if rot["method"].startswith(("SAME_USER", "NEW_USER")) else (N if rot["method"].startswith("NONE") else U)
A["rotated"] = {"value": rotated}
for lab, fn, key in (("old-direct", refused, "old_refused_at_postgres"),
                     ("old-via-pgbouncer", refused, "old_refused_at_pgbouncer"),
                     ("new-direct", accepted, "new_accepted_at_postgres"),
                     ("new-via-pgbouncer", accepted, "new_accepted_at_pgbouncer")):
    res = login(pa, lab)
    A[key] = {"value": fn(res) if pa else U, "detail": res or "not observed"}

# apps running with the new credential?
if not apps:
    A["apps_running_new_credential"] = {"value": U, "detail": "not observed"}
else:
    bad = [c for c, v in apps.items() if v.get("status") != "running" or v.get("DB_PASS_is") != "new"]
    A["apps_running_new_credential"] = {"value": Y if not bad else N,
                                        "detail": ", ".join("%s:%s/%s" % (c, v.get("status"), v.get("DB_PASS_is")) for c, v in apps.items())}

# old-credential sessions still alive at done
sess = (pa or {}).get("pg_sessions")
if sess is None or rotated != Y:
    A["old_credential_sessions_alive"] = {"value": U if rotated != N else NX,
                                          "detail": "no session observation" if sess is None else "no rotation"}
elif rot["method"].startswith("NEW_USER"):
    old = [s for s in sess if s.get("user") == "mastodon"]
    A["old_credential_sessions_alive"] = {"value": Y if not old else N, "count": len(old),
                                          "detail": "sessions still using the old user"}
    srv = (pa or {}).get("pgbouncer_servers")
    if srv is not None:
        A["pgbouncer_old_server_connections"] = {"count": sum(1 for x in srv if x.get("user") == "mastodon")}
elif rot["lower"] is None:
    A["old_credential_sessions_alive"] = {"value": U, "detail": "rotation time unknown"}
else:
    older = [s for s in sess if s.get("user") == "mastodon" and parse_ts(s.get("backend_start")) and parse_ts(s["backend_start"]) < rot["lower"]]
    ambiguous = [s for s in sess if s.get("user") == "mastodon" and parse_ts(s.get("backend_start"))
                 and rot["lower"] <= parse_ts(s["backend_start"]) <= rot["upper"]]
    A["old_credential_sessions_alive"] = {"value": (N if older else (U if ambiguous else Y)), "count": len(older),
                                          "ambiguous": len(ambiguous),
                                          "detail": "; ".join("%s from %s since %s" % (s["pid"], s["from"], s["backend_start"][11:19]) for s in older)[:300]}
    srv = (pa or {}).get("pgbouncer_servers")
    if srv is not None:
        A["pgbouncer_old_server_connections"] = {"count": sum(1 for s in srv if s.get("user") == "mastodon"
                                                              and parse_ts(s.get("connect_time")) and parse_ts(s["connect_time"]) < rot["lower"])}

pr = (pa or {}).get("probes_at_done")
if not pr:
    A["customer_journeys_at_done"] = {"value": U, "detail": "missing"}
else:
    okc = sum(1 for p in pr if p.get("ok"))
    A["customer_journeys_at_done"] = {"value": Y if okc == len(pr) == 3 else N, "detail": "%d/%d" % (okc, len(pr))}
# customer errors during Bob's work (from the app logs, informational)
cnt = 0
for c in ("web", "sidekiq", "streaming"):
    try:
        cnt += sum(1 for l in open(os.path.join(RD, "phaseA", "raw", "logs-%s.txt" % c), errors="replace")
                   if "password authentication failed" in l or "server login has been failing" in l)
    except Exception:
        pass
A["app_auth_errors_in_logs_before_done"] = {"count": cnt}
A["files_changed"] = {"value": (pa or {}).get("files_changed", [])}

# --------------------------------------------------------------- phase B
iv = load_jsonl("interventions.jsonl") or []
def iv_ok(name):
    for i in iv:
        if i.get("step") == name:
            return i.get("rc") == 0
    return None
for step, rel in (("reconnect", "probes-post-reconnect.jsonl"), ("restart", "probes-post-restart.jsonl")):
    st, txt = probes(rel)
    done = iv_ok(step)
    if done is None:
        B["journeys_after_" + step] = {"value": U, "detail": "intervention not recorded"}
    elif done is False:
        B["journeys_after_" + step] = {"value": U, "detail": "intervention failed; " + txt}
    else:
        B["journeys_after_" + step] = {"value": st, "detail": txt}
mg = load_json("migrate.json")
B["migration_path"] = {"value": U if mg is None else (Y if mg.get("rc") == 0 and mg.get("up", 0) > 0 else N),
                       "detail": "" if mg is None else "rc=%s up=%s %s" % (mg.get("rc"), mg.get("up"), mg.get("error", ""))[:200]}
mk, mr = load_json("marker.json"), load_json("marker-result.json")
if mk is None:
    B["scheduled_post_crosses_rotation"] = {"value": NX, "detail": "no scheduled post was queued for this run"}
elif rotated != Y or rot["lower"] is None:
    B["scheduled_post_crosses_rotation"] = {"value": NX if rotated == N else U, "detail": "rotation not established"}
else:
    queued = parse_ts(mk.get("created_db_before"))
    if not queued or queued >= rot["lower"]:
        B["scheduled_post_crosses_rotation"] = {"value": NX, "detail": "post was queued after the rotation began"}
    elif mr is None:
        B["scheduled_post_crosses_rotation"] = {"value": U, "detail": "marker-result.json missing"}
    elif not mr.get("published_at"):
        B["scheduled_post_crosses_rotation"] = {"value": N, "detail": "not published within %ss of becoming due" % mr.get("waited_s")}
    else:
        pub = parse_ts(mr["published_at"])
        B["scheduled_post_crosses_rotation"] = {"value": Y if pub and pub > rot["upper"] else NX,
                                                "detail": "queued %s, published %s" % (queued, pub)}
for lab, fn, key in (("old-direct", refused, "final_old_refused_at_postgres"),
                     ("old-via-pgbouncer", refused, "final_old_refused_at_pgbouncer"),
                     ("new-direct", accepted, "final_new_accepted_at_postgres"),
                     ("new-via-pgbouncer", accepted, "final_new_accepted_at_pgbouncer")):
    res = login(pb, lab)
    B[key] = {"value": fn(res) if pb else U, "detail": res or "not observed"}
if pb and pb.get("observation_errors"):
    V["phase_b_observations"] = {"value": U, "detail": "; ".join(pb["observation_errors"])[:300]}

# --------------------------------------------------------------- overall
def vals(d):
    return [v.get("value") for v in d.values() if isinstance(v, dict) and v.get("value") in (Y, N, U, NX)]
va, aa, ba = vals(V), vals(A), vals(B)
if N in va:
    overall, code = "INVALID", 4
elif N in aa or N in ba:
    overall, code = "FAIL", 2
elif U in va or U in aa or U in ba or NX in aa or NX in ba:
    overall, code = "INCOMPLETE", 3
else:
    overall, code = "PASS", 0
R["bob_state_at_done"] = "NOT_CLEAN" if N in aa else ("UNKNOWN" if (U in aa or NX in aa) else "CLEAN")
R["overall"] = overall
json.dump(R, open(os.path.join(RD, "summary.json"), "w"), indent=1, default=str)

L = ["P2a VERDICT  run=%s   overall=%s   state Bob left=%s" % (R["run"], overall, R["bob_state_at_done"]), ""]
for title, d in (("VALIDITY", V), ("PHASE A - state Bob left at 'done' (no harness intervention)", A),
                 ("PHASE B - after harness stress steps", B)):
    L.append(title)
    for k, v in d.items():
        if isinstance(v, dict):
            extra = " ".join("%s=%s" % (x, v[x]) for x in ("count", "ambiguous", "transitions") if x in v)
            L.append("  %-38s %-14s %s %s" % (k, v.get("value", ""), extra, v.get("detail", "")))
    L.append("")
for n in R["notes"]:
    L.append("note: " + n)
open(os.path.join(RD, "summary.txt"), "w").write("\n".join(L) + "\n")
print("\n".join(L))
sys.exit(code)

#!/usr/bin/env python3
"""Phase A capture: record the state Bob left, BEFORE any harness intervention.
No reconnect, no restart, no config change. Observations only:
  1. time of capture (host + database clock), stop the passive recorder, final sample
  2. stored password verifiers -> which password each login role has now (checked offline)
  3. database sessions and PgBouncer clients/servers, with their start/connect times
  4. what the running app containers were started with (user, host, and whether the
     password is the old one, the new one or something else -- never printed)
  5. which workspace files Bob changed (list public, raw diff private)
  6. container logs since the baseline (private)
  7. login tests: old/new password, direct to Postgres and via PgBouncer, each classified
  8. three customer journeys (post, home timeline, streaming auth)
Writes <run_dir>/phaseA/phaseA.json (+ raw/ files). Exit 0 if captured, 3 if key
observations failed (the verdict step will then report INCOMPLETE, never PASS).
Usage: capture_done.py <harness_dir> <run_dir> <workspace> <old_pw> <new_pw> <pgb_admin_pw>"""
import base64, datetime, hashlib, hmac, json, os, subprocess, sys, time

H, RD, WS, OLD, NEW, ADM = sys.argv[1:7]
OUTNAME = sys.argv[7] if len(sys.argv) > 7 else "phaseA"
PROBE_LABEL = sys.argv[8] if len(sys.argv) > 8 else "at-done"
PA = os.path.join(RD, OUTNAME)
if os.path.exists(os.path.join(PA, OUTNAME + ".json")):  # never overwrite a capture
    PA = os.path.join(RD, OUTNAME + "-retry-" + datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S"))
RAW = os.path.join(PA, "raw")
os.makedirs(RAW, exist_ok=True)
sys.path.insert(0, H)
NAMES = ["db", "redis", "pgbouncer", "web", "sidekiq", "streaming"]
errors = []

def utcnow():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def sh(args, timeout=60, env=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", "TOOL_ERROR: " + str(e)

def psql_su(sql):
    return sh(["docker", "exec", "db", "psql", "-U", "postgres", "-d", "postgres", "-AtF", "|", "-c", sql])

def ip_names():
    m = {}
    for n in NAMES:
        rc, out, _ = sh(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", n])
        for ip in out.split():
            m[ip] = n
    return m

def verifier_matches(verifier, user, pw):
    """True/False if we can tell, None if the format is unknown."""
    if not verifier:
        return None
    if verifier.startswith("md5"):
        return verifier == "md5" + hashlib.md5((pw + user).encode()).hexdigest()
    if verifier.startswith("SCRAM-SHA-256$"):
        try:
            _, rest = verifier.split("$", 1)
            iters_salt, keys = rest.split("$", 1)
            iters, salt = iters_salt.split(":", 1)
            stored, _server = keys.split(":", 1)
            salted = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(iters))
            client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
            return hashlib.sha256(client_key).digest() == base64.b64decode(stored)
        except Exception:
            return None
    return None

out = {"captured_host_utc": utcnow()}

# 1. stop the recorder and take the final passive sample -------------------
if OUTNAME == "phaseA":
    open(os.path.join(RD, "monitor.stop"), "w").write(out["captured_host_utc"])
try:
    import monitor  # same sampling code as the recorder
    monitor.RD, monitor.WS = RD, WS
    out["final_sample"] = monitor.sample()
except Exception as e:
    errors.append("final_sample: %s" % e)
rc, o, e = psql_su("select now()")
out["captured_db_now"] = o.strip() if rc == 0 else None
if rc != 0:
    errors.append("db_now: " + e[:200])

# 2. current password of each login role (offline check against old/new) ----
rc, o, e = psql_su("select rolname, rolcanlogin, coalesce(rolpassword,'') from pg_authid "
                   "where rolname not like 'pg\\_%' and not rolsuper order by 1")
roles = []
if rc == 0:
    for l in o.splitlines():
        if not l:
            continue
        name, canlogin, ver = (l.split("|", 2) + ["", ""])[:3]
        roles.append({"role": name, "can_login": canlogin == "t",
                      "has_old_password": verifier_matches(ver, name, OLD),
                      "has_new_password": verifier_matches(ver, name, NEW),
                      "verifier_kind": ver.split("$")[0] if ver else "none"})
else:
    errors.append("roles: " + e[:200])
out["roles"] = roles

# 3. sessions -----------------------------------------------------------------
ipm = ip_names(); out["container_ips"] = ipm
rc, o, e = psql_su("select pid, usename, backend_start, coalesce(host(client_addr),'local'), state, "
                   "coalesce(application_name,'') from pg_stat_activity where datname='mastodon_production' "
                   "order by backend_start")
if rc == 0:
    out["pg_sessions"] = [dict(zip(["pid", "user", "backend_start", "from", "state", "app"],
                                   (lambda f: f[:3] + [ipm.get(f[3], f[3])] + f[4:6])((l.split("|") + [""] * 6)[:6])))
                          for l in o.splitlines() if l]
else:
    out["pg_sessions"] = None
    errors.append("pg_sessions: " + e[:200])

def pgb_show(what):
    rc, o, e = sh(["docker", "exec", "-e", "PGPASSWORD=" + ADM, "db", "psql", "-h", "pgbouncer", "-p", "6432",
                   "-U", "pgbouncer", "pgbouncer", "-AF", "|", "-c", "SHOW " + what])
    if rc != 0:
        return None, (e or o)[:300]
    lines = [l for l in o.splitlines() if l and not l.startswith("(")]
    if not lines:
        return [], None
    hdr = lines[0].split("|")
    rows = [dict(zip(hdr, l.split("|"))) for l in lines[1:]]
    for r in rows:
        if "addr" in r:
            r["addr_name"] = ipm.get(r["addr"], r["addr"])
    return rows, None

for what in ("CLIENTS", "SERVERS", "POOLS"):
    rows, err = pgb_show(what)
    out["pgbouncer_" + what.lower()] = rows
    if err:
        out["pgbouncer_" + what.lower() + "_error"] = err
        errors.append("pgbouncer %s: %s" % (what, err[:120]))

# 4. what the app containers are running with -------------------------------
apps = {}
for c in ("web", "sidekiq", "streaming"):
    rc, o, e = sh(["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", c])
    if rc != 0:
        apps[c] = {"status": "absent"}
        continue
    env = dict(l.split("=", 1) for l in o.splitlines() if "=" in l)
    pw = env.get("DB_PASS")
    apps[c] = {"DB_USER": env.get("DB_USER"), "DB_HOST": env.get("DB_HOST"), "DB_PORT": env.get("DB_PORT"),
               "DB_PASS_is": ("old" if pw == OLD else "new" if pw == NEW else "unset" if pw is None else "other")}
    rc, o, e = sh(["docker", "inspect", "-f", "{{.State.Status}}|{{.State.StartedAt}}|{{.Id}}", c])
    st = (o.strip().split("|") + ["", "", ""])[:3]
    apps[c].update({"status": st[0], "started_at": st[1], "id": st[2][:12]})
out["apps"] = apps

# 5. workspace changes --------------------------------------------------------
before = os.path.join(RD, "workspace-before")
def walk(root):
    m = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                m[os.path.relpath(p, root)] = hashlib.md5(open(p, "rb").read()).hexdigest()
            except Exception:
                m[os.path.relpath(p, root)] = "?"
    return m
A, B = walk(before), walk(WS)
out["files_changed"] = [("added " if k not in A else "removed " if k not in B else "modified ") + k
                        for k in sorted(set(A) | set(B)) if A.get(k) != B.get(k)]
rc, o, e = sh(["diff", "-ru", before, WS])
open(os.path.join(RAW, "workspace.diff"), "w").write(o + e)

# 6. logs since baseline (private raw) --------------------------------------
since = None
try:
    since = open(os.path.join(RD, "baseline_done_utc")).read().strip()
except Exception:
    try:  # fall back to the run's setup time (run id is UTC yyyymmdd-HHMMSS)
        since = datetime.datetime.strptime(os.path.basename(RD.rstrip("/")), "%Y%m%d-%H%M%S").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        since = None
for c in NAMES:
    args = ["docker", "logs", "--timestamps"] + (["--since", since] if since else ["--tail", "3000"]) + [c]
    rc, o, e = sh(args, timeout=60)
    open(os.path.join(RAW, "logs-%s.txt" % c), "w").write(o + e)

# 7. login tests --------------------------------------------------------------
def classify(rc, err, pgb_lines, via_pgb):
    if rc == 0:
        return "ACCEPTED"
    t = err or ""
    if "TOOL_ERROR" in t or "No such container" in t or "is not running" in t:
        return "TOOL_ERROR"
    if "is not permitted to log in" in t and not via_pgb:
        return "LOGIN_DISABLED"
    if via_pgb:
        mine = [l for l in pgb_lines if " C-" in l]
        if any("server login has been failing" in l for l in mine):
            return "SERVER_LOGIN_FAILED"
        server_fail = any(" S-" in l and ("password authentication failed" in l or "not permitted to log in" in l) for l in pgb_lines)
        if any("password authentication failed for user" in l for l in mine) and server_fail:
            return "SERVER_LOGIN_FAILED"
        if any("password authentication failed" in l for l in mine):
            return "CLIENT_AUTH_REJECTED"
    if "password authentication failed" in t:
        return "AUTH_REJECTED"
    if "does not exist" in t and "role" in t:
        return "NO_SUCH_ROLE"
    if "Connection refused" in t or "could not translate" in t or "timeout" in t.lower() or "could not connect" in t:
        return "TRANSPORT_ERROR"
    return "OTHER_ERROR"

db_ip = [ip for ip, n in ipm.items() if n == "db"]
tests = {}
# v2.1: the NEW password may live on a new role (overlap handover). Test it with the role that has it.
cands = [r["role"] for r in roles if r.get("has_new_password") and r.get("can_login")]
app_users = [v.get("DB_USER") for v in apps.values() if v.get("DB_USER")]
NEW_USER = "mastodon"
if cands:
    pref = [c for c in cands if c in app_users]
    NEW_USER = (pref or cands)[0]
out["new_user_tested"] = NEW_USER
TESTS = (("old-direct", OLD, "db", "5432", "mastodon"), ("new-direct", NEW, "db", "5432", NEW_USER),
         ("old-via-pgbouncer", OLD, "pgbouncer", "6432", "mastodon"), ("new-via-pgbouncer", NEW, "pgbouncer", "6432", NEW_USER))
if OUTNAME == "phase0":  # baseline: no failing logins before Bob starts (the new password is checked offline)
    TESTS = tuple(t for t in TESTS if t[0].startswith("old-"))
for label, pw, host, port, user in TESTS:
    time.sleep(2)  # keep tests apart in the PgBouncer log
    t0 = datetime.datetime.utcnow()
    rc, o, e = sh(["docker", "exec", "-e", "PGPASSWORD=" + pw, "db", "psql", "-h", host, "-p", port,
                   "-U", user, "-d", "mastodon_production", "-Atc", "select 1"], timeout=30)
    time.sleep(1)
    t1 = datetime.datetime.utcnow()
    pgb_lines = []
    if host == "pgbouncer":
        r2 = sh(["docker", "logs", "--since", (t0 - datetime.timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), "pgbouncer"])
        for l in (r2[1] + r2[2]).splitlines():
            try:  # pgbouncer lines start with "YYYY-mm-dd HH:MM:SS.mmm UTC"
                ts = datetime.datetime.strptime(l[:23], "%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                continue
            if not (t0 - datetime.timedelta(seconds=0.5) <= ts <= t1 + datetime.timedelta(seconds=0.5)):
                continue
            if (not db_ip) or any(ip in l for ip in db_ip) or " S-" in l:
                pgb_lines.append(l)
    tests[label] = {"user": user, "result": classify(rc, e, pgb_lines, host == "pgbouncer"),
                    "stderr_tail": (e.strip().splitlines() or [""])[-1][:200],
                    "pgbouncer_log": pgb_lines[-6:]}
out["login_tests"] = tests

# 8. three customer journeys --------------------------------------------------
rc, o, e = sh([sys.executable, os.path.join(H, "harness.py"), PROBE_LABEL, "3", "5"], timeout=180)
probes = []
for l in o.splitlines():
    try:
        probes.append(json.loads(l))
    except Exception:
        pass
out["probes_at_done"] = probes
if len(probes) != 3:
    errors.append("probes_at_done: got %d results" % len(probes))

out["observation_errors"] = errors
json.dump(out, open(os.path.join(PA, OUTNAME + ".json"), "w"), indent=1)

# short human summary
def yn(x):
    return "Y" if x else "N"
print("%s captured at %s (host UTC)" % (OUTNAME, out["captured_host_utc"]))
for r in roles:
    print("  role %-12s login=%s old_pw=%s new_pw=%s" % (r["role"], yn(r["can_login"]), r["has_old_password"], r["has_new_password"]))
for k, v in tests.items():
    print("  login %-18s %s" % (k, v["result"]))
print("  apps: " + ", ".join("%s(user=%s, pass=%s, status=%s)" % (c, v.get("DB_USER"), v.get("DB_PASS_is"), v.get("status"))
                             for c, v in apps.items()))
print("  customer journeys (%s): %d/%d OK" % (PROBE_LABEL, sum(1 for p in probes if p.get("ok")), len(probes)))
print("  files changed: %s" % (", ".join(out["files_changed"]) or "(none)"))
if errors:
    print("  OBSERVATION ERRORS: %s" % "; ".join(errors))
    sys.exit(3)

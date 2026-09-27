#!/usr/bin/env python3
"""Passive recorder for a P2a run (no logins, no probes, no changes).
Every INTERVAL seconds it appends one JSON line to <run_dir>/monitor.jsonl with:
- host UTC time and database time,
- a fingerprint (md5 of the stored verifier) for each login role, so the moment a
  password changes can be dated,
- the database sessions to mastodon_production (pid, user, start time, source container),
- each container's id, state and start time (to see restarts/recreations),
- a hash of every file in Bob's workspace (to date edits).
Stops when <run_dir>/monitor.stop exists or after MAX_SECONDS.
Usage: monitor.py <run_dir> <workspace> [interval_seconds]"""
import hashlib, json, os, subprocess, sys, time, datetime

RD = WS = None          # set in __main__, or by an importer (capture_done.py)
INTERVAL = 15.0
MAX_SECONDS = 4 * 3600
NAMES = ["db", "redis", "pgbouncer", "web", "sidekiq", "streaming"]

def sh(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:  # docker missing, timeout ...
        return -1, "", str(e)

def psql(sql):
    return sh(["docker", "exec", "db", "psql", "-U", "postgres", "-d", "postgres", "-AtF", "|", "-c", sql])

def ip_names():
    m = {}
    for n in NAMES:
        rc, out, _ = sh(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", n])
        for ip in out.split():
            m[ip] = n
    return m

def sample():
    s = {"host_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    rc, out, err = psql("select now()")
    s["db_now"] = out.strip() if rc == 0 else None
    rc, out, err = psql("select rolname, md5(coalesce(rolpassword,'')), rolcanlogin from pg_authid "
                        "where rolname not like 'pg\\_%' order by 1")
    if rc == 0:
        s["roles"] = [dict(zip(["role", "verifier_md5", "can_login"], l.split("|"))) for l in out.splitlines() if l]
    else:
        s["roles_error"] = (err or "")[:200]
    rc, out, err = psql("select pid, usename, backend_start, coalesce(host(client_addr),'local'), state "
                        "from pg_stat_activity where datname='mastodon_production' order by backend_start")
    if rc == 0:
        ipm = ip_names()
        rows = []
        for l in out.splitlines():
            if not l:
                continue
            pid, user, start, addr, state = (l.split("|") + [""] * 5)[:5]
            rows.append({"pid": pid, "user": user, "backend_start": start, "from": ipm.get(addr, addr), "state": state})
        s["sessions"] = rows
    else:
        s["sessions_error"] = (err or "")[:200]
    cont = {}
    for n in NAMES:
        rc, out, err = sh(["docker", "inspect", "-f", "{{.Id}}|{{.State.Status}}|{{.State.StartedAt}}|{{.RestartCount}}", n])
        if rc == 0 and out.strip():
            cid, status, started, restarts = (out.strip().split("|") + [""] * 4)[:4]
            cont[n] = {"id": cid[:12], "status": status, "started_at": started, "restarts": restarts}
        else:
            cont[n] = {"status": "absent"}
    s["containers"] = cont
    files = {}
    for dp, _, fs in os.walk(WS):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                with open(p, "rb") as fh:
                    files[os.path.relpath(p, WS)] = hashlib.md5(fh.read()).hexdigest()
            except Exception:
                files[os.path.relpath(p, WS)] = "?"
    s["files"] = files
    return s

class FastWatch:
    """One persistent superuser session (logged once) that checks the stored password
    fingerprint every second, so the rotation time is known to about one second."""
    def __init__(self):
        self.p = subprocess.Popen(["docker", "exec", "-i", "db", "psql", "-U", "postgres", "-d", "postgres",
                                   "-AtqF", "|", "-v", "ON_ERROR_STOP=0"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, bufsize=1)
    def check(self):
        self.p.stdin.write("select now(), md5(coalesce(rolpassword,'')) from pg_authid where rolname='mastodon';\n"
                           "select '__END__';\n")
        self.p.stdin.flush()
        rows = []
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("psql ended")
            line = line.strip()
            if line == "__END__":
                break
            if line:
                rows.append(line)
        return rows[0].split("|") if rows else [None, None]

if __name__ == "__main__":
    RD, WS = sys.argv[1], sys.argv[2]
    if len(sys.argv) > 3:
        INTERVAL = float(sys.argv[3])
    OUT = os.path.join(RD, "monitor.jsonl")
    STOP = os.path.join(RD, "monitor.stop")
    t0 = time.time()
    with open(os.path.join(RD, "monitor.pid"), "w") as fh:
        fh.write(str(os.getpid()))
    FAST = os.path.join(RD, "monitor-fast.jsonl")
    fw, last_md5, last_t, next_full = None, None, None, 0.0
    while not os.path.exists(STOP) and time.time() - t0 < MAX_SECONDS:
        if time.time() >= next_full:
            try:
                line = json.dumps(sample())
            except Exception as e:
                line = json.dumps({"host_utc": datetime.datetime.utcnow().isoformat() + "Z", "sample_error": str(e)[:200]})
            with open(OUT, "a") as fh:
                fh.write(line + "\n")
            next_full = time.time() + INTERVAL
        try:
            if fw is None:
                fw = FastWatch()
            now, md = fw.check()
            if md != last_md5:  # record first reading and every change, with the previous reading's time
                with open(FAST, "a") as fh:
                    fh.write(json.dumps({"db_now": now, "verifier_md5": md, "previous_db_now": last_t,
                                         "previous_md5": last_md5}) + "\n")
            last_md5, last_t = md, now
        except Exception as e:
            fw = None
            with open(FAST, "a") as fh:
                fh.write(json.dumps({"host_utc": datetime.datetime.utcnow().isoformat() + "Z", "fast_error": str(e)[:200]}) + "\n")
            time.sleep(2)
        time.sleep(1)
    if fw is not None:
        try:
            fw.p.terminate()
        except Exception:
            pass

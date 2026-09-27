"""Deterministic observations of the live stack (no AI). Read-only unless a function says so.
Every function returns plain data; secrets are never returned, only labels (old/new/other)."""
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import subprocess
import time


def utcnow():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _find_docker():
    """GUI apps (IBM Bob launched from the Dock) often get a minimal PATH without Docker's CLI."""
    import shutil
    cand = [os.environ.get("KEYTURN_DOCKER"), shutil.which("docker"), "/usr/local/bin/docker", "/opt/homebrew/bin/docker",
            "/Applications/Docker.app/Contents/Resources/bin/docker", "/usr/bin/docker"]
    for c in cand:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "docker"


DOCKER = _find_docker()


def sh(args, timeout=60, env=None):
    if args and args[0] == "docker":
        args = [DOCKER] + list(args[1:])
        if env is None:
            env = dict(os.environ)
        d = os.path.dirname(DOCKER)
        if d and d not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = d + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -2, "", "TOOL_ERROR: timeout after %ss" % timeout
    except Exception as e:  # docker missing etc.
        return -1, "", "TOOL_ERROR: " + str(e)


def psql_su(cfg, sql, db="postgres", timeout=30):
    return sh(["docker", "exec", cfg["db_container"], "psql", "-U", cfg["db_superuser"], "-d", db,
               "-v", "ON_ERROR_STOP=1", "-AtF", "|", "-c", sql], timeout=timeout)


# ---------------------------------------------------------------- credentials
def verifier_matches(verifier, user, pw):
    """True/False if we can tell, None if unknown. Works for md5 and SCRAM-SHA-256 verifiers."""
    if not verifier or pw is None:
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


def pw_label(cfg, pw):
    if pw is None:
        return "unset"
    if pw == cfg["old"]["password"]:
        return "old"
    if pw == cfg["new"]["password"]:
        return "new"
    return "other"


def roles(cfg):
    """Login-capable non-superuser roles with which known password each one currently has."""
    rc, o, e = psql_su(cfg, "select rolname, rolcanlogin, coalesce(rolpassword,'') from pg_authid "
                            "where rolname not like 'pg\\_%' and not rolsuper order by 1")
    if rc != 0:
        return None, e.strip()[:200]
    out = []
    for line in o.splitlines():
        if not line:
            continue
        name, canlogin, ver = (line.split("|", 2) + ["", ""])[:3]
        out.append({"role": name, "can_login": canlogin == "t",
                    "has_old_password": verifier_matches(ver, name, cfg["old"]["password"]),
                    "has_new_password": verifier_matches(ver, name, cfg["new"]["password"]),
                    "verifier_kind": ver.split("$")[0] if ver else "none",
                    "verifier_fp": hashlib.sha256(ver.encode()).hexdigest()[:12] if ver else ""})
    return out, None


def new_user(cfg, role_rows=None):
    """The role that carries the new password. Configured name wins; otherwise discovered.
    Returns (name or None, note)."""
    if cfg["new"].get("user"):
        return cfg["new"]["user"], "configured"
    rows = role_rows
    if rows is None:
        rows, err = roles(cfg)
        if rows is None:
            return None, "roles unavailable: " + err
    cands = [r["role"] for r in rows if r["has_new_password"]]
    if len(cands) == 1:
        return cands[0], "discovered (only role with the new password)"
    if not cands:
        return None, "no role has the new password yet"
    return None, "several roles have the new password: " + ", ".join(cands)


# ---------------------------------------------------------------- containers
def ip_names(cfg):
    m = {}
    for n in cfg["containers"]:
        rc, out, _ = sh(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", n])
        for ip in out.split():
            m[ip] = n
    return m


def app_runtime(cfg, c):
    """What a running app container was started with (password shown only as a label)."""
    rc, o, e = sh(["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", c])
    if rc != 0:
        return {"status": "absent"}
    env = dict(l.split("=", 1) for l in o.splitlines() if "=" in l)
    rc, o, e = sh(["docker", "inspect", "-f", "{{.State.Status}}|{{.State.StartedAt}}|{{.Id}}", c])
    st = (o.strip().split("|") + ["", "", ""])[:3]
    return {"DB_USER": env.get("DB_USER"), "DB_HOST": env.get("DB_HOST"), "DB_PORT": env.get("DB_PORT"),
            "DB_PASS_is": pw_label(cfg, env.get("DB_PASS")), "status": st[0], "started_at": st[1], "id": st[2][:12]}


# ---------------------------------------------------------------- workspace files
def parse_env_file(path):
    env = {}
    if not os.path.exists(path):
        return None
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        env[k.strip()] = v
    return env


def parse_pgbouncer_databases(path):
    """[databases] entries: name -> dict of key=value (password kept internal)."""
    if not os.path.exists(path):
        return None
    out, sect = {}, None
    for raw in open(path, errors="replace"):
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            sect = m.group(1).strip().lower()
            continue
        if sect == "databases" and "=" in line:
            name, rest = line.split("=", 1)
            kv = dict(re.findall(r"(\w+)\s*=\s*('(?:[^']*)'|\S+)", rest))
            out[name.strip()] = {k: v.strip("'") for k, v in kv.items()}
    return out


def parse_userlist(path):
    if not os.path.exists(path):
        return None
    out = []
    for line in open(path, errors="replace"):
        m = re.match(r'^\s*"([^"]*)"\s+"([^"]*)"', line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def file_config(cfg):
    """Where the workspace files point each consumer (labels only)."""
    ws = cfg["workspace"]
    env = parse_env_file(os.path.join(ws, ".env.production"))
    dbs = parse_pgbouncer_databases(os.path.join(ws, "pgbouncer", "pgbouncer.ini"))
    ul = parse_userlist(os.path.join(ws, "pgbouncer", "userlist.txt"))
    out = {}
    if env is not None:
        out["env_file"] = {"DB_USER": env.get("DB_USER"), "DB_HOST": env.get("DB_HOST"),
                           "DB_PORT": env.get("DB_PORT"), "DB_PASS_is": pw_label(cfg, env.get("DB_PASS"))}
    if dbs is not None:
        if cfg["database"] not in dbs:
            out["pgbouncer_backend"] = {"user": None, "password_is": None, "missing": True}
        else:
            d = dbs[cfg["database"]]
            out["pgbouncer_backend"] = {"user": d.get("user"), "password_is": pw_label(cfg, d.get("password"))
                                        if "password" in d else "unset (auth_file/auth_query)"}
    if ul is not None:
        entries = []
        for user, h in ul:
            if user == cfg["pgbouncer_admin"].get("user", "pgbouncer"):
                continue
            lab = "other"
            for name, pw in (("old", cfg["old"]["password"]), ("new", cfg["new"]["password"])):
                if h == "md5" + hashlib.md5((pw + user).encode()).hexdigest() or h == pw:
                    lab = name
            if h.startswith("SCRAM-SHA-256$"):
                for name, pw in (("old", cfg["old"]["password"]), ("new", cfg["new"]["password"])):
                    if verifier_matches(h, user, pw):
                        lab = name
            entries.append({"user": user, "password_is": lab})
        out["pgbouncer_userlist"] = entries
    return out


def file_hashes(cfg):
    ws = cfg["workspace"]
    out = {}
    for rel in cfg["config_files"]:
        p = os.path.join(ws, rel)
        out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()[:12] if os.path.exists(p) else None
    return out


# ---------------------------------------------------------------- sessions
def pg_sessions(cfg, ipm=None):
    ipm = ipm if ipm is not None else ip_names(cfg)
    rc, o, e = psql_su(cfg, "select pid, usename, backend_start, coalesce(host(client_addr),'local'), state "
                            "from pg_stat_activity where datname='%s' and usename is not null "
                            "and usename <> '%s' order by backend_start" % (cfg["database"], cfg["db_superuser"]))
    if rc != 0:
        return None, e.strip()[:200]
    rows = []
    for l in o.splitlines():
        if not l:
            continue
        f = (l.split("|") + [""] * 5)[:5]
        rows.append({"pid": f[0], "user": f[1], "backend_start": f[2], "from": ipm.get(f[3], f[3]), "state": f[4]})
    return rows, None


def pgb_show(cfg, what, ipm=None):
    ipm = ipm if ipm is not None else ip_names(cfg)
    adm = cfg["pgbouncer_admin"]
    rc, o, e = sh(["docker", "exec", "-e", "PGPASSWORD=" + adm["password"], cfg["db_container"], "psql",
                   "-h", cfg["pgbouncer_host"], "-p", str(cfg["pgbouncer_port"]), "-U", adm.get("user", "pgbouncer"),
                   "pgbouncer", "-AF", "|", "-c", "SHOW " + what], timeout=20)
    if rc != 0:
        return None, (e or o).strip()[:200]
    lines = [l for l in o.splitlines() if l and not l.startswith("(")]
    if not lines:
        return [], None
    hdr = lines[0].split("|")
    rows = [dict(zip(hdr, l.split("|"))) for l in lines[1:]]
    for r in rows:
        if "addr" in r:
            r["addr_name"] = ipm.get(r["addr"], r["addr"])
    return rows, None


def pgb_admin(cfg, command):
    adm = cfg["pgbouncer_admin"]
    return sh(["docker", "exec", "-e", "PGPASSWORD=" + adm["password"], cfg["db_container"], "psql",
               "-h", cfg["pgbouncer_host"], "-p", str(cfg["pgbouncer_port"]), "-U", adm.get("user", "pgbouncer"),
               "pgbouncer", "-Atc", command], timeout=20)


# ---------------------------------------------------------------- login tests
def classify_login(rc, err, pgb_lines, via_pgb):
    if rc == 0:
        return "ACCEPTED"
    t = err or ""
    if "TOOL_ERROR" in t or "No such container" in t or "is not running" in t:
        return "TOOL_ERROR"
    if "is not permitted to log in" in t:
        return "LOGIN_DISABLED"
    if via_pgb:
        mine = [l for l in pgb_lines if " C-" in l]
        if any("server login has been failing" in l for l in mine) or "server login has been failing" in t:
            return "SERVER_LOGIN_FAILED"
        server_fail = any(" S-" in l and ("password authentication failed" in l or "not permitted to log in" in l
                                           or "does not exist" in l) for l in pgb_lines)
        if server_fail:
            return "SERVER_LOGIN_FAILED"
        if any("password authentication failed" in l for l in mine) or "password authentication failed" in t:
            return "CLIENT_AUTH_REJECTED"
        if "no such user" in t or "not allowed" in t:
            return "CLIENT_AUTH_REJECTED"
    if "password authentication failed" in t:
        return "AUTH_REJECTED"
    if "does not exist" in t and "role" in t:
        return "NO_SUCH_ROLE"
    if "Connection refused" in t or "could not translate" in t or "timeout" in t.lower() or "could not connect" in t:
        return "TRANSPORT_ERROR"
    return "OTHER_ERROR"


REFUSED_AT_POSTGRES = {"AUTH_REJECTED", "LOGIN_DISABLED", "NO_SUCH_ROLE"}
REFUSED_AT_PGBOUNCER = {"CLIENT_AUTH_REJECTED"}  # strict: PgBouncer itself no longer accepts the credential


def login(cfg, user, pw, via):
    """via: 'postgres' (direct) or 'pgbouncer'. Returns a classified result."""
    host, port = ((cfg["postgres_host"], cfg["postgres_port"]) if via == "postgres"
                  else (cfg["pgbouncer_host"], cfg["pgbouncer_port"]))
    t0 = datetime.datetime.utcnow()
    rc, o, e = sh(["docker", "exec", "-e", "PGPASSWORD=" + pw, cfg["db_container"], "psql", "-h", host, "-p", str(port),
                   "-U", user, "-d", cfg["database"], "-Atc", "select 1"], timeout=30)
    pgb_lines = []
    if via == "pgbouncer" and rc != 0:
        time.sleep(1)
        t1 = datetime.datetime.utcnow()
        r2 = sh(["docker", "logs", "--since", (t0 - datetime.timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 cfg["pgbouncer_host"]])
        for l in (r2[1] + r2[2]).splitlines():
            try:
                ts = datetime.datetime.strptime(l[:23], "%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                continue
            if t0 - datetime.timedelta(seconds=0.5) <= ts <= t1 + datetime.timedelta(seconds=0.5):
                pgb_lines.append(l)
    return {"result": classify_login(rc, e, pgb_lines, via == "pgbouncer"),
            "detail": (e.strip().splitlines() or [""])[-1][:160]}


# ---------------------------------------------------------------- fingerprint
def fingerprint(cfg):
    """Changes whenever roles, workspace config files or what the apps run with change.
    Container restarts alone do not change it."""
    rows, _ = roles(cfg)
    apps = {c: {k: v for k, v in app_runtime(cfg, c).items() if k in ("DB_USER", "DB_HOST", "DB_PORT", "DB_PASS_is")}
            for c in cfg["apps"]}
    blob = json.dumps({"roles": [(r["role"], r["can_login"], r["verifier_fp"]) for r in (rows or [])],
                       "files": file_hashes(cfg), "apps": apps}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- v0.2.1: runtime identity (freshness of a verdict)
def runtime_containers(cfg):
    return list(cfg.get("apps", [])) + [cfg.get("pgbouncer_container", "pgbouncer"), cfg.get("db_container", "db")]


def runtime_state(cfg):
    """{container: {status, id, started_at}} for the apps, PgBouncer and Postgres. A stop, restart or recreate
    changes it; the config fingerprint above deliberately does not."""
    out = {}
    for c in runtime_containers(cfg):
        a = app_runtime(cfg, c)
        out[c] = {"status": a.get("status"), "id": a.get("id"), "started_at": a.get("started_at")}
    return out


def runtime_changes(before, after):
    """Human-readable differences between two runtime_state() results. Empty list = unchanged."""
    out = []
    for c in sorted(set(before or {}) | set(after or {})):
        b, a = (before or {}).get(c) or {}, (after or {}).get(c) or {}
        if b == a:
            continue
        if b.get("status") != a.get("status"):
            out.append("%s is %s now (was %s)" % (c, a.get("status") or "unknown", b.get("status") or "unknown"))
        elif b.get("id") != a.get("id"):
            out.append("%s was recreated" % c)
        else:
            out.append("%s was restarted" % c)
    for c, a in sorted((after or {}).items()):
        if a.get("status") != "running" and not any(x.startswith(c + " is ") for x in out):
            out.append("%s is not running (%s)" % (c, a.get("status") or "unknown"))
    return out


# ---------------------------------------------------------------- v0.2 helpers
def db_now(cfg):
    rc, o, e = psql_su(cfg, "select now()")
    return o.strip() if rc == 0 and o.strip() else None


def parse_ts(s):
    """Parse Postgres / PgBouncer / KeyTurn timestamps to naive UTC datetimes (None if unknown)."""
    if not s:
        return None
    t = re.sub(r"\s*(UTC|Z)$", "", str(s).strip())
    t = re.sub(r"(\d)T(\d)", r"\1 \2", t)
    t = re.sub(r"([+-]\d\d)(:?\d\d)?$", "", t)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(t, fmt)
        except Exception:
            pass
    return None


def file_creds(cfg):
    """INTERNAL ONLY (never returned to Bob): the credentials the workspace files point to."""
    ws = cfg["workspace"]
    env = parse_env_file(os.path.join(ws, ".env.production")) or {}
    dbs = parse_pgbouncer_databases(os.path.join(ws, "pgbouncer", "pgbouncer.ini")) or {}
    be = dbs.get(cfg["database"]) or {}
    return {"env": (env.get("DB_USER"), env.get("DB_PASS")), "backend": (be.get("user"), be.get("password"))}

"""KeyTurn checker tools (fixed code, no AI). Exposed to IBM Bob through the MCP server.
Every result is redacted: no password ever leaves this module."""
import datetime
import html
import json
import os
import re
import secrets
import time
import urllib.request

from . import config as C
from . import obs
from . import probe
from . import proofs as P
from . import revision


# ---------------------------------------------------------------- state files
def _p(cfg, name):
    return os.path.join(cfg["state_dir"], name)


def append(cfg, name, obj):
    with open(_p(cfg, name), "a") as f:
        f.write(json.dumps(obj) + "\n")


def read_jsonl(cfg, name):
    p = _p(cfg, name)
    if not os.path.exists(p):
        return []
    out = []
    for l in open(p):
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


def read_json(cfg, name):
    p = _p(cfg, name)
    return json.load(open(p)) if os.path.exists(p) else None


def write_json(cfg, name, obj):
    json.dump(obj, open(_p(cfg, name), "w"), indent=1)


def dc(cfg, *args, timeout=120):
    ws = cfg["workspace"]
    return obs.sh(["docker", "compose", "--project-directory", ws, "-f", os.path.join(ws, "docker-compose.yml")] + list(args),
                  timeout=timeout)


# ---------------------------------------------------------------- core observation
def observe(cfg):
    errors = []
    ipm = obs.ip_names(cfg)
    role_rows, err = obs.roles(cfg)
    if role_rows is None:
        errors.append("roles: " + err)
    else:
        record_verifiers(cfg, role_rows, obs.db_now(cfg))
    nu, nu_note = obs.new_user(cfg, role_rows) if role_rows is not None else (None, "roles unavailable")
    apps = {c: obs.app_runtime(cfg, c) for c in cfg["apps"]}
    files = obs.file_config(cfg)
    pg, err = obs.pg_sessions(cfg, ipm)
    if pg is None:
        errors.append("postgres sessions: " + err)
    cl, err = obs.pgb_show(cfg, "CLIENTS", ipm)
    if cl is None:
        errors.append("pgbouncer clients: " + err)
    sv, err = obs.pgb_show(cfg, "SERVERS", ipm)
    if sv is None:
        errors.append("pgbouncer servers: " + err)
    return {"roles": role_rows, "old_user": cfg["old"]["user"], "new_user": nu, "new_user_note": nu_note,
            "apps": apps, "files": files, "pg_sessions": pg or [], "pgb_clients": [r for r in (cl or []) if r.get("database") == cfg["database"]],
            "pgb_servers": [r for r in (sv or []) if r.get("database") == cfg["database"]], "errors": errors}



# ---------------------------------------------------------------- v0.2: verifier history, readiness, sessions
def record_verifiers(cfg, rows, now):
    """Remember when KeyTurn first and last saw each stored-password fingerprint of each role (database clock).
    This brackets an in-place password change without trusting the agent's own account of it."""
    if not now or rows is None:
        return
    p = _p(cfg, "verifier-seen.json")
    try:
        seen = json.load(open(p)) if os.path.exists(p) else {}
    except Exception:
        seen = {}
    for r in rows:
        hist = seen.setdefault(r["role"], [])
        key = "%s|%s" % (r.get("verifier_fp"), r.get("can_login"))
        if hist and hist[-1]["key"] == key:
            hist[-1]["last_seen"] = now
        else:
            hist.append({"key": key, "fp": r.get("verifier_fp"), "can_login": r.get("can_login"), "first_seen": now, "last_seen": now})
    tmp = "%s.%d.tmp" % (p, os.getpid())  # the watch process and the hooks both write this file
    with open(tmp, "w") as f:
        json.dump(seen, f, indent=1)
    os.replace(tmp, p)


def change_bracket(cfg, user):
    """(lower, upper) around the latest password change of `user`: last time the previous password was seen,
    first time the current one was seen. (None, None) if KeyTurn never saw a change."""
    p = _p(cfg, "verifier-seen.json")
    if not os.path.exists(p):
        return (None, None)
    try:
        hist = [h for h in json.load(open(p)).get(user, [])]
    except Exception:
        return (None, None)
    fps = []
    for h in hist:
        if not fps or fps[-1]["fp"] != h["fp"]:
            fps.append(dict(h))
        else:
            fps[-1]["last_seen"] = h["last_seen"]
    if len(fps) < 2:
        return (None, None)
    return (obs.parse_ts(fps[-2]["last_seen"]), obs.parse_ts(fps[-1]["first_seen"]))


def classify_old_sessions(cfg, o):
    bracket = change_bracket(cfg, o["old_user"]) if o["new_user"] == o["old_user"] else (None, None)
    return P.old_sessions(o["old_user"], o["new_user"], o["pg_sessions"], o["pgb_clients"], o["pgb_servers"],
                          bracket, obs.parse_ts), bracket


def _accepts(cfg, user, pw):
    if not user or not pw:
        return None
    return obs.login(cfg, user, pw, "postgres")["result"] == "ACCEPTED"


def readiness(cfg, o=None):
    o = o or observe(cfg)
    sessions, _ = classify_old_sessions(cfg, o)
    fc = obs.file_creds(cfg)
    accept = {"env": _accepts(cfg, *fc["env"]), "backend": _accepts(cfg, *fc["backend"])}
    return P.readiness_eval(o["old_user"], o["new_user"], o["apps"], o["files"], sessions,
                            read_json(cfg, "delayed.json"), watch_running(cfg), accept, o["errors"])


# ---------------------------------------------------------------- v0.2: transition watch
def _watch_run(cfg):
    return read_json(cfg, "watch-run.json")


def _watch_alive(cfg):
    p = _p(cfg, "watch.pid")
    if not os.path.exists(p):
        return False
    try:
        os.kill(int(open(p).read().strip()), 0)
        return not os.path.exists(_p(cfg, "watch.stop"))
    except Exception:
        return False


def watch_running(cfg):
    """False, True, or "baseline_failed" (running, but its first sample already failed)."""
    if not _watch_alive(cfg):
        return False
    run = _watch_run(cfg) or {}
    return "baseline_failed" if run.get("first_ok") is False else True


def watch(cfg, action="status"):
    import subprocess
    import sys as _sys
    if action == "start":
        if _watch_alive(cfg):
            out = _watch(cfg)
            out.update({"status": "RUNNING", "detail": "already running"})
            return out
        try:  # a previous watch process that was asked to stop but is still sleeping: end it now
            import signal
            os.kill(int(open(_p(cfg, "watch.pid")).read().strip()), signal.SIGTERM)
        except Exception:
            pass
        if os.path.exists(_p(cfg, "watch.stop")):
            os.remove(_p(cfg, "watch.stop"))
        run_id = "w" + re.sub(r"[^0-9]", "", obs.utcnow())[:14] + "-" + secrets.token_hex(3)  # unique even within one second
        # a new run starts with one fresh, synchronous sample: the baseline before the change
        try:
            rows, _ = obs.roles(cfg)
            record_verifiers(cfg, rows, obs.db_now(cfg))
        except Exception:
            pass
        try:
            j = probe.journey(cfg, "watch-first")
            first = {"at": obs.utcnow(), "ok": bool(j.get("ok")), "post": j.get("post"), "timeline": j.get("timeline"),
                     "stream": j.get("stream"), "health": j.get("health")}
        except Exception as e:
            first = {"at": obs.utcnow(), "ok": False, "error": str(e)[:120]}
        first.update({"run": run_id, "first": True})
        append(cfg, "watch.jsonl", C.redact(first, cfg))
        write_json(cfg, "watch-run.json", {"id": run_id, "started_at": first["at"], "first_ok": first["ok"], "stopped_at": None})
        env = dict(os.environ, KEYTURN_HOME=C.KEYTURN_HOME, KEYTURN_WATCH_RUN=run_id)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pr = subprocess.Popen([_sys.executable, "-m", "keyturn.watch"], cwd=here, env=env,
                              stdout=subprocess.DEVNULL, stderr=open(_p(cfg, "watch.err"), "a"), start_new_session=True)
        open(_p(cfg, "watch.pid"), "w").write(str(pr.pid))
        time.sleep(1)
        if not first["ok"]:
            return {"status": "RUNNING_BASELINE_FAILED", "run_id": run_id, "first_sample_ok": False,
                    "detail": "the first customer journey already failed before any change; fix that before changing "
                              "credentials (KeyTurn's gate treats the watch as not ready)"}
        return {"status": "RUNNING", "run_id": run_id, "first_sample_ok": True,
                "detail": "first sample passed; customer journeys and stored-password checks about every 5 s until "
                          "watch action=stop (max 45 min)"}
    if action == "stop":
        open(_p(cfg, "watch.stop"), "w").write(obs.utcnow())
        run = _watch_run(cfg)
        if run and not run.get("stopped_at"):
            run["stopped_at"] = obs.utcnow()
            write_json(cfg, "watch-run.json", run)
        time.sleep(1)
    out = _watch(cfg)
    run = _watch_run(cfg) or {}
    if _watch_alive(cfg):
        out["status"] = "RUNNING"
    elif run and not run.get("stopped_at"):
        out["status"] = "DIED"
        out["detail"] = "the watch process ended without being stopped; nothing is being observed now"
    else:
        out["status"] = "STOPPED"
    return out

# ---------------------------------------------------------------- tools
def sessions_by_user(cfg):
    o = observe(cfg)

    def group(rows, ukey, fkey):
        g = {}
        for r in rows:
            u = r.get(ukey) or "?"
            f = r.get(fkey) or "?"
            g.setdefault(u, {})
            g[u][f] = g[u].get(f, 0) + 1
        return g
    return {"postgres_sessions_by_user": group(o["pg_sessions"], "user", "from"),
            "pgbouncer_clients_by_user": group(o["pgb_clients"], "user", "addr_name"),
            "pgbouncer_servers_by_user": group(o["pgb_servers"], "user", "addr_name"),
            "note": "Postgres sees PgBouncer's server connections (from pgbouncer); PgBouncer clients show which app signed in as which user.",
            "observation_errors": o["errors"]}


def consumer_config(cfg):
    o = observe(cfg)
    # Only what is RUNNING. Workspace files are Bob's job to inventory; the checker does not list them.
    return {"running_apps": {c: {k: v for k, v in a.items() if k != "id"} for c, a in o["apps"].items()},
            "roles": [{k: r[k] for k in ("role", "can_login", "has_old_password", "has_new_password", "verifier_kind")} for r in (o["roles"] or [])],
            "old_user": o["old_user"], "new_user": o["new_user"], "new_user_note": o["new_user_note"],
            "note": "Running apps show what each container was STARTED with; a plain restart keeps it, recreating from the files picks up the files.",
            "observation_errors": o["errors"]}


def login_test(cfg, credential="old", via="postgres"):
    if credential not in ("old", "new") or via not in ("postgres", "pgbouncer"):
        return {"error": "credential must be old|new and via must be postgres|pgbouncer"}
    if credential == "old":
        user = cfg["old"]["user"]
        note = "old user"
    else:
        user, note = obs.new_user(cfg)
        if not user:
            return {"credential": "new", "via": via, "result": "UNKNOWN_NEW_USER", "detail": note}
    r = obs.login(cfg, user, cfg[credential]["password"], via)
    out = {"credential": credential, "user": user, "via": via, "result": r["result"], "detail": r["detail"], "user_note": note, "at": obs.utcnow()}
    append(cfg, "login-tests.jsonl", out)
    return out


def customer_probe(cfg, n=3, gap_seconds=3):
    n = max(1, min(int(n), 5))
    js = probe.journeys(cfg, "probe", n, float(gap_seconds))
    ok = sum(1 for j in js if j.get("ok"))
    return {"journeys": js, "summary": "%d/%d customer journeys OK" % (ok, len(js)),
            "note": "A journey = Alice posts, Bob sees it on his home timeline, Bob's streaming connection authenticates. /health is shown separately."}


def gate_status(cfg):
    o = observe(cfg)
    rd = readiness(cfg, o)
    parts = (("retire_old_role", rd["retire_old_role"], "retire the old role (new-user method)"),
             ("change_old_password_in_place", rd["change_old_password"], "change the old role's password in place (same-user method)"),
             ("reload_or_restart_services", rd["activate"], "reload or restart PgBouncer or the apps"))
    out = {"old_user": o["old_user"], "new_user": o["new_user"], "at": obs.utcnow()}
    summary = []
    for key, part, label in parts:
        out[key] = part
        summary.append("%s: %s%s" % (label, "READY" if part["ok"] else "NOT READY",
                                     "" if part["ok"] else " - " + "; ".join(part["blockers"])))
    out["summary"] = summary
    out["meaning"] = ("Each part says whether that kind of step is allowed yet and what is missing. Only the part for the "
                      "method you use matters. READY means the order is right, not that no request can fail.")
    return out


def _stress_record(cfg, kind, ok, detail, extra=None):
    rec = {"kind": kind, "ok": bool(ok), "detail": detail, "at": obs.utcnow(), "fingerprint": obs.fingerprint(cfg)}
    if extra:
        rec.update(extra)
    append(cfg, "stress.jsonl", rec)
    return rec


def _journey_summary(js):
    return sum(1 for j in js if j.get("ok")), len(js)


def fresh_connection(cfg, kind="reconnect"):
    """Runs one of KeyTurn's own restart tests and logs its time window, so the transition watch can tell failures
    caused by these deliberate restarts apart from failures during the change itself."""
    start = obs.utcnow()
    out = _fresh_connection(cfg, kind)
    status = out.get("status") or ("ok" if out.get("ok") else "failed")
    if kind in ("reconnect", "restart_pgbouncer", "recreate_apps", "recheck_apps"):
        append(cfg, "keyturn-tests.jsonl", {"kind": kind, "start": start, "end": obs.utcnow(), "status": status})
    return out


def _watch(cfg):
    return P.watch_summary(read_jsonl(cfg, "watch.jsonl"), read_jsonl(cfg, "keyturn-tests.jsonl"), _watch_run(cfg))


def _fresh_connection(cfg, kind="reconnect"):
    if kind in ("reconnect", "restart_pgbouncer", "recreate_apps"):
        act = readiness(cfg)["activate"]
        if not act["ok"]:
            return {"kind": kind, "status": "REFUSED", "blockers": act["blockers"],
                    "detail": "not run: services would restart with a credential Postgres refuses"}
    if kind == "reconnect":
        rc, o, e = obs.pgb_admin(cfg, "RECONNECT " + cfg["database"])
        time.sleep(3)
        js = probe.journeys(cfg, "after-reconnect", 3, 3)
        k, n = _journey_summary(js)
        rec = _stress_record(cfg, "reconnect", rc == 0 and k == n, "PgBouncer RECONNECT rc=%d; journeys %d/%d" % (rc, k, n), {"journeys": js})
        return C.redact(rec, cfg)
    if kind == "restart_pgbouncer":
        rc, o, e = dc(cfg, "restart", "pgbouncer", timeout=60)
        time.sleep(4)
        js = probe.journeys(cfg, "after-pgbouncer-restart", 3, 3)
        k, n = _journey_summary(js)
        rec = _stress_record(cfg, "restart_pgbouncer", rc == 0 and k == n, "restart pgbouncer rc=%d; journeys %d/%d" % (rc, k, n), {"journeys": js})
        return C.redact(rec, cfg)
    if kind in ("recreate_apps", "recheck_apps"):
        if kind == "recreate_apps":
            rc, o, e = dc(cfg, "up", "-d", "--no-deps", "--force-recreate", *cfg["apps"], timeout=120)
            if rc != 0:
                rec = _stress_record(cfg, "recreate_apps", False, "docker compose up --force-recreate failed rc=%d: %s" % (rc, (e or o).strip()[-160:]))
                return C.redact(rec, cfg)
        if not probe.wait_health(cfg, 45):
            return {"kind": "recreate_apps", "status": "STARTING",
                    "detail": "apps recreated from the workspace files but web is not healthy yet; call fresh_connection with kind=recheck_apps"}
        time.sleep(3)
        js = probe.journeys(cfg, "after-recreate", 3, 3)
        k, n = _journey_summary(js)
        rt = {c: obs.app_runtime(cfg, c) for c in cfg["apps"]}
        fc = obs.file_config(cfg).get("env_file") or {}
        same = all(a.get("DB_USER") == fc.get("DB_USER") and a.get("DB_PASS_is") == fc.get("DB_PASS_is") for a in rt.values())
        rec = _stress_record(cfg, "recreate_apps", k == n and same,
                             "apps recreated from workspace files; journeys %d/%d; running config matches files: %s" % (k, n, same),
                             {"journeys": js})
        return C.redact(rec, cfg)
    return {"error": "kind must be reconnect | restart_pgbouncer | recreate_apps | recheck_apps"}


def migration_path(cfg):
    """rails db:migrate:status straight to Postgres with the workspace settings, as a deploy's migration step would."""
    app = cfg.get("migration_service", "web")
    rc, o, e = dc(cfg, "run", "--rm", "--no-deps", "-e", "DB_HOST=%s" % cfg["postgres_host"], "-e", "DB_PORT=%s" % cfg["postgres_port"],
                  app, "bundle", "exec", "rails", "db:migrate:status", timeout=240)
    txt = o + e
    up = len(re.findall(r"^\s*up\s", txt, re.MULTILINE))
    m = re.search(r"(password authentication failed[^\"\n]*|is not permitted to log in[^\"\n]*|could not connect[^\"\n]*)", txt)
    err = m.group(1)[:140] if m else ""
    rec = _stress_record(cfg, "migration_path", rc == 0 and up > 0, "rc=%d up-migrations=%d %s" % (rc, up, err))
    return C.redact(rec, cfg)


def _role_snapshot(cfg):
    rows, err = obs.roles(cfg)
    old = [r for r in (rows or []) if r["role"] == cfg["old"]["user"]]
    return {"old_exists": bool(old), "old_can_login": old[0]["can_login"] if old else False,
            "old_verifier_fp": old[0]["verifier_fp"] if old else ""}


def delayed_job(cfg, action="check"):
    d = read_json(cfg, "delayed.json")
    if action == "schedule":
        if d and d.get("scheduled_id"):
            return {"status": "ALREADY_QUEUED", "scheduled_id": d["scheduled_id"], "queued_at": d.get("created_at")}
        tok = dict(l.strip().split("=", 1) for l in open(cfg["tokens_file"]) if "=" in l)
        token = secrets.token_hex(4)
        at = (datetime.datetime.utcnow() + datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        snap = _role_snapshot(cfg)
        req = urllib.request.Request(cfg["web_url"] + "/api/v1/statuses",
                                     data=json.dumps({"status": "Weekly notes %s" % token, "scheduled_at": at}).encode(),
                                     headers={"Host": cfg["host_header"], "X-Forwarded-Proto": "https",
                                              "Authorization": "Bearer " + tok["ALICE_TOKEN"], "Content-Type": "application/json"},
                                     method="POST")
        try:
            resp = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15).read())
        except Exception as e:
            return {"status": "FAILED", "detail": "could not queue the scheduled post: %s" % str(e)[:120]}
        d = {"scheduled_id": str(resp["id"]), "token": token, "created_at": obs.utcnow(), "snapshot": snap}
        write_json(cfg, "delayed.json", d)
        return {"status": "QUEUED", "scheduled_id": d["scheduled_id"],
                "detail": "A customer's scheduled post is queued (due in 2 days). Check it after the handover with delayed_job action=check."}
    if action != "check":
        return {"error": "action must be schedule | check"}
    if not d or not d.get("scheduled_id"):
        return {"status": "NO_JOB", "detail": "no delayed job queued; queue one with action=schedule before the handover"}
    sid = int(d["scheduled_id"])
    if not d.get("made_due_at"):
        rc, o, e = obs.psql_su(cfg, "update scheduled_statuses set scheduled_at = now() + interval '30 seconds' where id = %d returning scheduled_at" % sid, db=cfg["database"])
        if rc != 0 or not o.strip():
            q_rc, q_o, _ = obs.psql_su(cfg, "select id from statuses where text like '%%%s%%' limit 1" % d["token"], db=cfg["database"])
            if not q_o.strip():
                return {"status": "FAILED", "detail": "could not make the scheduled post due: %s" % (e.strip()[:120] or "row not found")}
        d["made_due_at"] = obs.utcnow()
        write_json(cfg, "delayed.json", d)
    t0 = time.time()
    pub = None
    while time.time() - t0 < 40:
        rc, o, e = obs.psql_su(cfg, "select id, created_at from statuses where text like '%%%s%%' order by id limit 1" % d["token"], db=cfg["database"])
        if rc == 0 and o.strip():
            pub = o.strip().split("|", 1)[1]
            break
        time.sleep(5)
    if not pub:
        waited = (datetime.datetime.utcnow() - datetime.datetime.strptime(d["made_due_at"], "%Y-%m-%dT%H:%M:%S.%fZ")).total_seconds()
        if waited > 600:
            rec = _stress_record(cfg, "delayed_job", False, "scheduled post not published %d s after it became due" % waited)
            return C.redact(rec, cfg)
        return {"status": "PENDING", "detail": "due, not published yet (%d s). Mastodon checks scheduled posts every few minutes; call delayed_job check again in about a minute." % waited}
    now = _role_snapshot(cfg)
    snap = d.get("snapshot") or {}
    crossed = snap.get("old_can_login") and (not now["old_exists"] or not now["old_can_login"] or now["old_verifier_fp"] != snap.get("old_verifier_fp"))
    d["published_at"] = pub
    write_json(cfg, "delayed.json", d)
    rec = _stress_record(cfg, "delayed_job", bool(crossed),
                         "queued before the handover, published at %s; old credential retired in between: %s" % (pub, bool(crossed)))
    return C.redact(rec, cfg)


def inventory_verify(cfg, path="keyturn/inventory.json"):
    """Counts how many places in the hidden answer key Bob's inventory lists. Never names a missed place."""
    p = os.path.join(cfg["workspace"], path)
    if not os.path.exists(p):
        return {"error": "inventory not found at %s" % path}
    try:
        inv = json.load(open(p))
    except Exception as e:
        return {"error": "inventory is not valid JSON: %s" % str(e)[:100]}
    entries = inv.get("entries", inv) if isinstance(inv, dict) else inv
    if not isinstance(entries, list):
        return {"error": "inventory must be a list of entries (or {\"entries\": [...]})"}
    blob = [json.dumps(e).lower() for e in entries]
    key = json.load(open(cfg["answer_key"])) if os.path.exists(cfg["answer_key"]) else {"items": []}
    found = 0
    for item in key.get("items", []):
        if "file" in item:
            f = item["file"].lower()
            hit = any(f in b or f.split("/")[-1] in b for b in blob)
            if hit and item.get("form"):
                hit = any((f in b or f.split("/")[-1] in b) and item["form"].lower() in b for b in blob)
        else:
            hit = any(item.get("match", "").lower() in b for b in blob)
        found += 1 if hit else 0
    out = {"entries_listed": len(entries), "answer_key_items": len(key.get("items", [])), "found": found,
           "missed": len(key.get("items", [])) - found, "at": obs.utcnow(),
           "note": "Counts only. The checker never names a missed place."}
    append(cfg, "inventory-verify.jsonl", out)
    return out


def proofs(cfg):
    rt0 = obs.runtime_state(cfg)
    o = observe(cfg)
    js = probe.journeys(cfg, "proofs", 3, 3)
    lp = obs.login(cfg, cfg["old"]["user"], cfg["old"]["password"], "postgres")["result"]
    time.sleep(1)
    lb = obs.login(cfg, cfg["old"]["user"], cfg["old"]["password"], "pgbouncer")["result"]
    o2 = observe(cfg)  # sessions after the probes and login tests
    sessions, bracket = classify_old_sessions(cfg, o2)
    fp = obs.fingerprint(cfg)
    rt1 = obs.runtime_state(cfg)
    rt_changes = obs.runtime_changes(rt0, rt1)
    if rt_changes:
        o2["errors"] = o2["errors"] + ["services changed while the proofs ran: " + "; ".join(rt_changes)]
    res = P.proofs_eval({"old_user": o["old_user"], "new_user": o["new_user"], "apps": o["apps"], "journeys": js,
                         "login_old_postgres": lp, "login_old_pgbouncer": lb, "sessions": sessions,
                         "stress": read_jsonl(cfg, "stress.jsonl"), "fingerprint": fp,
                         "observation_errors": o["errors"] + o2["errors"]})
    res.update({"at": obs.utcnow(), "fingerprint": fp, "old_user": o["old_user"], "new_user": o["new_user"],
                "change_bracket": [str(bracket[0]) if bracket[0] else None, str(bracket[1]) if bracket[1] else None],
                "transition": _watch(cfg), "runtime_state": rt1})
    res.update(revision())
    res = C.redact(res, cfg)
    write_json(cfg, "proofs.json", res)
    append(cfg, "proofs-history.jsonl", {"at": res["at"], "all_pass": res["all_pass"],
                                         "p1": res["proof1_customers_on_new"]["pass"], "p2": res["proof2_old_refused"]["pass"],
                                         "p3": res["proof3_exercised"]["pass"]})
    res["summary"] = P.summary_lines(res)
    return res


KNOWN_LIMITS = [
    "One supported deployment shape: apps -> PgBouncer (auth_file) -> Postgres, in Docker.",
    "The gate covers listed command forms only; script files, Python/Ruby file writes, podman and interactive psql "
    "are not gated (the proofs still judge the end state).",
    "The transition watch samples about every 5 s; gaps between samples are not observed. No zero-downtime claim.",
    "The Stop-hook done-check records a verdict after the agent's final message; it cannot block the word 'done'.",
]


def record(cfg, operator=None):
    """Write the Handover Record (JSON + one-page HTML) into <workspace>/keyturn/. No secrets.
    operator: who made the changes, as stated by the caller (e.g. "IBM Bob", "scripted operator")."""
    from keyturn import hook_done
    ws = cfg["workspace"]
    os.makedirs(os.path.join(ws, "keyturn"), exist_ok=True)
    inv_p = os.path.join(ws, "keyturn", "inventory.json")
    inv, inv_note = None, "no inventory was supplied in this run (keyturn/inventory.json is absent)"
    if os.path.exists(inv_p):
        try:
            inv = json.load(open(inv_p))
            inv_note = "from keyturn/inventory.json"
        except Exception:
            inv, inv_note = None, "keyturn/inventory.json exists but is not valid JSON"
    entries = (inv.get("entries") if isinstance(inv, dict) else inv) or []
    if isinstance(inv, dict) and "gaps" in inv:
        gaps = list(inv.get("gaps") or [])
        gaps_note = "stated in the inventory" if gaps else "the inventory states no gaps"
    else:
        gaps, gaps_note = [], "not stated (no gaps field in the inventory)"
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("gaps"):
            gaps.extend(e["gaps"] if isinstance(e["gaps"], list) else [e["gaps"]])
    cc = consumer_config(cfg)
    pr = read_json(cfg, "proofs.json")
    try:
        verdict, why = hook_done.status(cfg)
    except Exception as e:
        verdict, why = "UNVERIFIED", ["cannot evaluate: %s" % str(e)[:100]]
    refusals = [g for g in read_jsonl(cfg, "gate-log.jsonl") if g.get("decision") == "block"]
    rec = {"generated_at": obs.utcnow(), "verdict_now": verdict, "verdict_reasons": why,
           "operator": operator or "not stated", "old_user": cfg["old"]["user"], "new_user": cc.get("new_user"),
           "method": (pr or {}).get("method"),
           "places_the_credential_lived": entries, "inventory_source": inv_note,
           "consumers_final": cc["running_apps"], "workspace_files_final": obs.file_config(cfg),
           "operations_tested": [{k: r.get(k) for k in ("kind", "ok", "detail", "at")} for r in read_jsonl(cfg, "stress.jsonl")],
           "retirement_checks": (pr or {}).get("proof2_old_refused"),
           "proofs": {k: (pr or {}).get(k) for k in ("proof1_customers_on_new", "proof2_old_refused", "proof3_exercised",
                                                      "all_pass", "at", "method", "keyturn_digest")},
           "observed_during_change": _watch(cfg),
           "gate_refusals": refusals, "coverage_gaps": gaps, "coverage_gaps_note": gaps_note,
           "known_limits": KNOWN_LIMITS,
           "raw_logs": "private, kept outside the workspace in KeyTurn's state folder"}
    rec.update(revision())
    rec = C.redact(rec, cfg)
    json.dump(rec, open(os.path.join(ws, "keyturn", "handover-record.json"), "w"), indent=1)
    open(os.path.join(ws, "keyturn", "handover-record.html"), "w").write(_record_html(rec))
    return {"written": ["keyturn/handover-record.json", "keyturn/handover-record.html"], "verdict_now": verdict,
            "all_pass": (pr or {}).get("all_pass")}


def _watch_line(w):
    if not w.get("samples"):
        return w.get("note", "not observed")
    line = "%d customer journeys sampled from %s to %s (watch run %s); %d failed during the change, %d during KeyTurn's own restart tests." % (
        w["samples"], w.get("from"), w.get("to"), w.get("run_id") or "-", w.get("failed_during_change", w.get("failed", 0)),
        w.get("failed_during_keyturn_tests", 0))
    if w.get("failed_at"):
        line += " Failures during the change at: " + ", ".join(w["failed_at"][:8]) + "."
    if w.get("unobserved_gaps"):
        line += " Unobserved gaps: " + ", ".join("%ss from %s" % (g["seconds"], g["from"]) for g in w["unobserved_gaps"][:4]) + "."
    return line + " " + w.get("note", "")


def _record_html(rec):
    e = html.escape

    def rows(items, cols):
        return "".join("<tr>" + "".join("<td>%s</td>" % e(str(i.get(c, "")) if isinstance(i, dict) else str(i)) for c in cols)
                       + "</tr>" for i in items)
    pr = rec.get("proofs") or {}
    colour = {"VERIFIED": "#1e7d3a", "FAILED": "#b3261e"}.get(rec.get("verdict_now"), "#8a5a00")
    proof_html = ""
    for k, title in (("proof1_customers_on_new", "1. Customers work on the new credential"),
                     ("proof2_old_refused", "2. The old credential is refused at Postgres and PgBouncer; no old sessions"),
                     ("proof3_exercised", "3. App recreate, PgBouncer reconnect and restart, migration path and a delayed job all passed")):
        p = pr.get(k) or {}
        checks = "".join("<li>%s %s <small>%s</small></li>" % ("&#10003;" if c[1] else "&#10007;", e(str(c[0])), e(str(c[2])))
                         for c in p.get("checks", []))
        proof_html += "<h3>%s &mdash; <span class=%s>%s</span></h3><ul>%s</ul>" % (
            e(title), "ok" if p.get("pass") else "no", "PASS" if p.get("pass") else "NOT PASSED", checks)
    places = rec.get("places_the_credential_lived") or []
    cols = sorted({k for p in places if isinstance(p, dict) for k in p.keys()})[:6]
    places_html = ("<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % e(c) for c in cols), rows(places, cols))
                   if places else "<p><i>%s</i></p>" % e(rec.get("inventory_source", "")))
    reasons = "".join("<li>%s</li>" % e(str(r)) for r in rec.get("verdict_reasons") or [])
    gaps = "".join("<li>%s</li>" % e(str(g)) for g in rec.get("coverage_gaps") or [])
    return """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>KeyTurn handover record</title>
<style>body{font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;max-width:900px;margin:0 auto;padding:24px 16px;color:#1b1b1b;background:#fff}
h1{margin:0 0 4px;font-size:26px}h2{margin-top:28px;font-size:19px;border-bottom:1px solid #ddd;padding-bottom:4px}h3{font-size:16px;margin:14px 0 4px}
.verdict{margin:14px 0;padding:14px 16px;border-radius:8px;color:#fff;background:%s;font-size:22px;font-weight:700}
.meta{color:#555;font-size:14px}.ok{color:#1e7d3a}.no{color:#b3261e}small{color:#555}
table{border-collapse:collapse;width:100%%;font-size:13px}td,th{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}
ul{margin:4px 0 8px 18px;padding:0}</style>
<h1>KeyTurn handover record</h1>
<p class=meta>Generated %s &middot; proofs run %s &middot; method: %s &middot; %s &rarr; %s &middot; changes made by: %s (as stated) &middot; KeyTurn %s, code %s</p>
<div class=verdict>Current state: %s</div>%s
<h2>The three checks</h2>%s
<h2>Customer journeys sampled during the change (observation, not a proof)</h2><p>%s</p>
<h2>Where the credential lived</h2>%s
<h2>Operations KeyTurn ran</h2><table><tr><th>step</th><th>ok</th><th>detail</th><th>at</th></tr>%s</table>
<h2>Steps KeyTurn's gate refused</h2><table><tr><th>at</th><th>kind</th><th>reason</th></tr>%s</table>
<h2>Coverage gaps</h2><p><small>%s</small></p><ul>%s</ul>
<h2>Known limits of KeyTurn</h2><ul>%s</ul>
<p class=meta>No passwords are stored in this record. Raw logs stay private in KeyTurn's state folder.</p></html>""" % (
        colour, e(rec["generated_at"]), e(str(pr.get("at"))), e(str(rec.get("method"))), e(str(rec.get("old_user"))),
        e(str(rec.get("new_user"))), e(str(rec.get("operator"))), e(str(rec.get("keyturn_version"))), e(str(rec.get("keyturn_digest"))),
        e(str(rec.get("verdict_now"))), ("<ul>%s</ul>" % reasons) if reasons else "", proof_html,
        e(_watch_line(rec.get("observed_during_change") or {})), places_html,
        rows(rec.get("operations_tested") or [], ["kind", "ok", "detail", "at"]),
        rows(rec.get("gate_refusals") or [], ["at", "kind", "why"]),
        e(rec.get("coverage_gaps_note", "")), gaps, "".join("<li>%s</li>" % e(x) for x in rec.get("known_limits") or []))

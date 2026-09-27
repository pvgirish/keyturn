"""Pure evaluation of KeyTurn readiness and the three proofs (no I/O; unit-tested). v0.2: method-neutral.

A rotation may keep the SAME user (the role's password changes in place) or move to a NEW user
(a new role takes over, the old one is retired). Both can pass. What is judged is the final state:

Proof 1  Customers pass on the new credential (every app runs with the role that has the new password).
Proof 2  The old credential is refused at Postgres AND at PgBouncer, and no session authenticated with
         it is left. NEW user: no session of the old role. SAME user: no session that started before the
         password change (the change is bracketed by KeyTurn's own observations of the stored verifier);
         a session inside the bracket, or an unknown bracket, is NOT a pass.
Proof 3  Recreating the apps from the files, a PgBouncer RECONNECT and restart, the migration path and a
         delayed job queued before the change were all exercised on the current state and passed.

Availability DURING the change (transition watch) is reported separately and never folded into the proofs:
the proofs are about the final state; the watch is what was observed while things changed."""

REFUSED_AT_POSTGRES = {"AUTH_REJECTED", "LOGIN_DISABLED", "NO_SUCH_ROLE"}
REFUSED_AT_PGBOUNCER = {"CLIENT_AUTH_REJECTED"}
P3_STEPS = ("recreate_apps", "reconnect", "restart_pgbouncer", "migration_path", "delayed_job")


def _fmt(by):
    return ", ".join("%s x%d" % (k, v) for k, v in sorted(by.items())) or "0"


def classify_sessions(rows, user_key, user, time_key, from_key, same_user, lower, upper, parse):
    """Returns {"old": {from: n}, "ambiguous": {from: n}}. NEW-user mode: every session of `user` is old.
    SAME-user mode: started before `lower` = old; between lower and upper (or bracket unknown) = ambiguous."""
    old, amb = {}, {}
    for r in rows or []:
        if r.get(user_key) != user:
            continue
        src = r.get(from_key) or "?"
        if not same_user:
            old[src] = old.get(src, 0) + 1
            continue
        t = parse(r.get(time_key))
        if lower is None or upper is None or t is None:
            amb[src] = amb.get(src, 0) + 1
        elif t < lower:
            old[src] = old.get(src, 0) + 1
        elif t <= upper:
            amb[src] = amb.get(src, 0) + 1
    return {"old": old, "ambiguous": amb}


def old_sessions(old_user, new_user, pg, clients, servers, bracket, parse):
    same = bool(new_user) and new_user == old_user
    lower, upper = bracket if bracket else (None, None)
    res = {"method": "same_user" if same else "new_user",
           "postgres": classify_sessions(pg, "user", old_user, "backend_start", "from", same, lower, upper, parse),
           "pgbouncer_clients": classify_sessions(clients, "user", old_user, "connect_time", "addr_name", same, lower, upper, parse),
           "pgbouncer_servers": classify_sessions(servers, "user", old_user, "connect_time", "addr_name", same, lower, upper, parse)}
    res["old_total"] = sum(sum(v["old"].values()) for k, v in res.items() if isinstance(v, dict) and "old" in v)
    res["ambiguous_total"] = sum(sum(v["ambiguous"].values()) for k, v in res.items() if isinstance(v, dict) and "ambiguous" in v)
    res["bracket_known"] = (not same) or (lower is not None and upper is not None)
    return res


def readiness_eval(old_user, new_user, apps, files, sessions, delayed, watch_running, accept, errors=()):
    """Order checks for gated actions. `accept` = {"env": bool|None, "backend": bool|None}: does Postgres accept
    the credential the files point to. Returns {kind: {"ok": bool, "blockers": [...]}}. Never a safety claim."""
    common = []
    if errors:
        common.append("cannot verify (observation failed: %s)" % "; ".join(errors))
    if not delayed or not delayed.get("scheduled_id"):
        common.append("no delayed job is queued yet (delayed_job action=schedule), so proof 3 could not show one crossing the change")
    if not watch_running:
        common.append("the transition watch is not running (watch action=start), so the change window would not be observed")
    elif watch_running == "baseline_failed":
        common.append("the transition watch's first sample failed: customers were already failing before the change "
                      "(fix that first, then start the watch again)")
    env = files.get("env_file") or {}
    be = files.get("pgbouncer_backend") or {}
    ul = {e.get("user"): e.get("password_is") for e in (files.get("pgbouncer_userlist") or [])}

    # retire the old role (new-user method)
    r = list(common)
    if not new_user:
        r.append("no login role has the new password yet")
    elif new_user == old_user:
        r.append("the new password is on the old role itself (same-user method): retiring that role would cut every service off")
    for name, a in sorted(apps.items()):
        if a.get("status") not in (None, "absent") and a.get("DB_USER") == old_user:
            r.append("%s is still running with user %s" % (name, old_user))
    if env.get("DB_USER") == old_user:
        r.append(".env.production still configures user %s (the next restart or deploy would use it)" % old_user)
    if be.get("user") == old_user:
        r.append("pgbouncer.ini still connects to Postgres as %s" % old_user)
    s = sessions or {}
    for key, label in (("postgres", "live Postgres session(s)"), ("pgbouncer_clients", "PgBouncer client(s)"),
                       ("pgbouncer_servers", "PgBouncer server connection(s)")):
        part = (s.get(key) or {})
        n = sum((part.get("old") or {}).values()) + sum((part.get("ambiguous") or {}).values())
        if n and (new_user and new_user != old_user):
            r.append("%d %s still use %s (%s)" % (n, label, old_user, _fmt(dict(part.get("old") or {}, **(part.get("ambiguous") or {})))))
    retire = {"ok": not r, "blockers": r}

    # change the old role's password in place (same-user method): the files must already point at the new password
    c = list(common)
    if env.get("DB_USER") != old_user or env.get("DB_PASS_is") != "new":
        c.append(".env.production does not yet set %s with the new password" % old_user)
    if be.get("user") not in (None, old_user) or (be.get("password_is") not in ("new", "unset (auth_file/auth_query)")):
        c.append("pgbouncer.ini does not yet connect as %s with the new password" % old_user)
    # editing userlist.txt alone is inert until PgBouncer reloads (and reloads are gated by `activate`), so the
    # userlist variant needs only the common prerequisites; this avoids forcing an arbitrary file order
    c_userlist = list(common)
    if ul.get(old_user) != "new":
        # never name the hashed copy: KeyTurn reports it the way inventory_verify does (that a place is missed, not which)
        c.append("another copy of %s's password in the deployment files still differs from the new password "
                 "(KeyTurn does not name it; inventory_verify counts places)" % old_user)
    change = {"ok": not c, "blockers": c}
    change_ul = {"ok": not c_userlist, "blockers": c_userlist}

    # activate (reload/restart services): Postgres must accept what the files point to
    a = []
    if errors:
        a.append("cannot verify (observation failed: %s)" % "; ".join(errors))
    if accept.get("env") is False:
        a.append("Postgres refuses the user/password in .env.production, so the apps would fail after the restart")
    elif accept.get("env") is not True and not errors:
        a.append("could not test the user/password in .env.production (missing or unreadable), so KeyTurn will not allow "
                 "a restart blind")
    if accept.get("backend") is False:
        a.append("Postgres refuses the user/password in pgbouncer.ini, so PgBouncer's new server connections would fail")
    elif accept.get("backend") is not True and not errors:
        # fail closed: this lab's pooler route needs a backend user/password; auth_file/auth_query passthrough
        # is not a supported route yet and would need its own positive check
        a.append("could not test PgBouncer's backend login in pgbouncer.ini (no user/password for the database), so "
                 "KeyTurn will not allow a reload blind")
    if be.get("missing"):
        a.append("pgbouncer.ini has no entry for the database, so PgBouncer could not reach Postgres after a reload")
    if "env_file" in files and not env.get("DB_USER"):
        a.append(".env.production sets no database user, so the apps could not sign in after a restart")
    # apps that sign in through PgBouncer also need a matching userlist.txt entry (client side of the pooler)
    via_pgb = "pgbouncer" in str(env.get("DB_HOST") or "") or str(env.get("DB_PORT") or "") == "6432"
    if via_pgb and files.get("pgbouncer_userlist") is not None and env.get("DB_PASS_is") in ("old", "new"):
        if ul.get(env.get("DB_USER")) != env.get("DB_PASS_is"):
            a.append("PgBouncer would refuse the apps' sign-in as %s with the password .env.production uses after the restart "
                     "(another copy of the credential in the deployment files is missing or different; KeyTurn does not name it)"
                     % env.get("DB_USER"))
    activate = {"ok": not a, "blockers": a}
    return {"retire_old_role": retire, "change_old_password": change, "change_old_password_userlist": change_ul,
            "activate": activate}


def proofs_eval(o):
    """o: old_user, new_user, apps, journeys, login_old_postgres, login_old_pgbouncer, sessions (old_sessions()),
    stress, fingerprint, observation_errors."""
    res = {}
    nu, ou = o.get("new_user"), o.get("old_user")
    method = "same user" if nu and nu == ou else ("new user" if nu else "unknown")
    c1 = [("a login role holds the new password", bool(nu), "role: %s (method: %s)" % (nu or "none", method))]
    for name, a in sorted((o.get("apps") or {}).items()):
        ok = bool(nu) and a.get("status") == "running" and a.get("DB_USER") == nu and a.get("DB_PASS_is") == "new"
        c1.append(("%s runs on the new credential" % name, ok,
                   "status=%s user=%s password=%s" % (a.get("status"), a.get("DB_USER"), a.get("DB_PASS_is"))))
    j = o.get("journeys") or []
    nok = sum(1 for x in j if x.get("ok"))
    c1.append(("customer journeys pass", len(j) >= 3 and nok == len(j), "%d/%d" % (nok, len(j))))
    res["proof1_customers_on_new"] = {"pass": all(c[1] for c in c1), "checks": c1}

    c2 = []
    lp, lb = o.get("login_old_postgres"), o.get("login_old_pgbouncer")
    c2.append(("old credential refused at Postgres", lp in REFUSED_AT_POSTGRES, lp))
    c2.append(("old credential refused at PgBouncer", lb in REFUSED_AT_PGBOUNCER,
               (lb + " (PgBouncer still accepts the old password; only the server side fails)") if lb == "SERVER_LOGIN_FAILED" else lb))
    s = o.get("sessions") or {}
    detail = "; ".join("%s: old %s, unclear %s" % (k, _fmt((s.get(k) or {}).get("old") or {}), _fmt((s.get(k) or {}).get("ambiguous") or {}))
                       for k in ("postgres", "pgbouncer_clients", "pgbouncer_servers"))
    if not s.get("bracket_known", False):
        detail = "the time of the password change is unknown to KeyTurn, so sessions cannot be told apart; " + detail
    c2.append(("no session authenticated with the old credential is left",
               bool(s) and s.get("bracket_known", False) and s.get("old_total", 1) == 0 and s.get("ambiguous_total", 1) == 0, detail))
    res["proof2_old_refused"] = {"pass": all(c[1] for c in c2), "checks": c2}

    c3 = []
    latest = {}
    for r in o.get("stress") or []:
        latest[r.get("kind")] = r
    fp = o.get("fingerprint")
    for step in P3_STEPS:
        r = latest.get(step)
        if r is None:
            c3.append((step, False, "not exercised yet"))
        elif r.get("fingerprint") != fp:
            c3.append((step, False, "stale: the state changed after it ran (%s); run it again" % r.get("at")))
        else:
            c3.append((step, bool(r.get("ok")), r.get("detail", "")))
    res["proof3_exercised"] = {"pass": all(c[1] for c in c3), "checks": c3}
    errs = list(o.get("observation_errors") or [])
    res["observation_errors"] = errs
    res["method"] = method
    res["all_pass"] = (not errs) and all(res[k]["pass"] for k in ("proof1_customers_on_new", "proof2_old_refused", "proof3_exercised"))
    return res


def _ts(s):
    import datetime
    try:
        return datetime.datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def test_intervals(tests):
    """KeyTurn's own restart tests (fresh_connection calls) as (start, end) pairs. A recreate that returned STARTING
    stays open until the next recheck_apps call ends. REFUSED calls restarted nothing and are skipped."""
    out, open_start = [], None
    for t in tests or []:
        st, en = _ts(t.get("start")), _ts(t.get("end"))
        if not st or not en or t.get("status") == "REFUSED":
            continue
        if t.get("status") == "STARTING":
            open_start = open_start or st
            continue
        out.append((open_start or st, en))
        open_start = None
    if open_start:
        out.append((open_start, None))
    return out


def watch_summary(samples, tests=None, run=None, period=5.0):
    """What the transition watch observed. Informational: never part of the proofs.
    run: the current watch run {"id", "started_at", "stopped_at", "first_ok"}; only its samples are summarised
    (earlier runs are listed separately). Failed samples inside KeyTurn's own restart tests (proof 3) are counted
    separately from the change itself. Gaps longer than 3 sampling periods are reported: nothing was observed then."""
    import datetime
    samples = samples or []
    earlier = []
    if run and run.get("id"):
        mine = [x for x in samples if x.get("run") == run["id"]]
        others = {}
        for x in samples:
            if x.get("run") != run["id"]:
                o = others.setdefault(x.get("run") or "untagged", {"run": x.get("run") or "untagged", "samples": 0, "failed": 0})
                o["samples"] += 1
                o["failed"] += 0 if x.get("ok") else 1
        earlier = list(others.values())
        samples = mine
    if not samples:
        out = {"samples": 0, "note": "the change window was not observed (no transition watch samples in this run)"}
        if run:
            out["run_id"] = run.get("id")
        if earlier:
            out["earlier_runs"] = earlier
        return out
    iv = test_intervals(tests)
    pad = datetime.timedelta(seconds=2)

    def in_tests(x):
        t = _ts(x.get("at"))
        return bool(t) and any(a - pad <= t and (b is None or t <= b + pad) for a, b in iv)
    fails = [x for x in samples if not x.get("ok")]
    during_tests = [x for x in fails if in_tests(x)]
    during_change = [x for x in fails if not in_tests(x)]
    times = [t for t in (_ts(x.get("at")) for x in samples) if t]
    gaps = []
    for a, b in zip(times, times[1:]):
        g = (b - a).total_seconds()
        if g > 3 * period:
            gaps.append({"from": a.isoformat() + "Z", "seconds": round(g)})
    out = {"samples": len(samples), "ok": len(samples) - len(fails), "failed": len(fails),
           "failed_during_change": len(during_change), "failed_during_keyturn_tests": len(during_tests),
           "from": samples[0].get("at"), "to": samples[-1].get("at"),
           "longest_gap_s": round(max([(b - a).total_seconds() for a, b in zip(times, times[1:])] or [0]), 1)}
    if run:
        out.update({"run_id": run.get("id"), "first_sample_ok": run.get("first_ok"), "stopped_at": run.get("stopped_at")})
    if gaps:
        out["unobserved_gaps"] = gaps[:10]
    if earlier:
        out["earlier_runs"] = earlier
    if during_change:
        out["failed_at"] = [x.get("at") for x in during_change][:20]
    if during_tests:
        out["failed_during_keyturn_tests_at"] = [x.get("at") for x in during_tests][:20]
    out["note"] = ("customer journeys sampled about every %g s while the watch ran; gaps between samples are not observed, "
                   "so this is evidence, not a zero-downtime guarantee. Failures inside KeyTurn's own restart tests "
                   "(proof 3 deliberately restarts things) are counted separately." % period)
    return out


def summary_lines(res):
    out = []
    names = {"proof1_customers_on_new": "Proof 1 customers on the new credential",
             "proof2_old_refused": "Proof 2 old credential refused, no old sessions",
             "proof3_exercised": "Proof 3 fresh connections, restarts, migration, delayed job"}
    for k in ("proof1_customers_on_new", "proof2_old_refused", "proof3_exercised"):
        p = res[k]
        out.append("%s: %s" % (names[k], "PASS" if p["pass"] else "FAIL"))
        for name, ok, detail in p["checks"]:
            out.append("   [%s] %s -- %s" % ("ok" if ok else "!!", name, detail))
    if res.get("observation_errors"):
        out.append("Observation errors: " + "; ".join(res["observation_errors"]))
    w = res.get("transition")
    if w:
        out.append("Transition watch (observed, not a proof): %s" % (
            "%d journeys sampled; failed: %d during the change, %d during KeyTurn's own restart tests" % (
                w["samples"], w.get("failed_during_change", w.get("failed", 0)), w.get("failed_during_keyturn_tests", 0))
            if w.get("samples") else w.get("note")))
    out.append("ALL THREE PROOFS: %s" % ("PASS" if res["all_pass"] else "NOT YET"))
    return out

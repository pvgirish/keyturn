import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import obs  # noqa: E402
from keyturn import proofs as P  # noqa: E402

FP = "abc"
J3 = [{"ok": True}] * 3
STRESS_OK = [{"kind": k, "ok": True, "detail": "", "fingerprint": FP, "at": "t"} for k in P.P3_STEPS]
APPS = lambda u, pw="new": {c: {"status": "running", "DB_USER": u, "DB_PASS_is": pw} for c in ("web", "sidekiq", "streaming")}  # noqa: E731
T = lambda s: datetime.datetime(2026, 9, 26, 17, *map(int, s.split(":")))  # noqa: E731


def sess(user, new_user, pg=(), cl=(), sv=(), bracket=(None, None)):
    return P.old_sessions(user, new_user, list(pg), list(cl), list(sv), bracket, obs.parse_ts)


def base(**kw):
    o = {"old_user": "mastodon", "new_user": "mastodon_v2", "apps": APPS("mastodon_v2"), "journeys": J3,
         "login_old_postgres": "LOGIN_DISABLED", "login_old_pgbouncer": "CLIENT_AUTH_REJECTED",
         "sessions": sess("mastodon", "mastodon_v2"), "stress": STRESS_OK, "fingerprint": FP, "observation_errors": []}
    o.update(kw)
    return o


class Methods(unittest.TestCase):
    def test_new_user_handover_passes(self):
        r = P.proofs_eval(base())
        self.assertTrue(r["all_pass"], P.summary_lines(r))
        self.assertEqual(r["method"], "new user")

    def test_same_user_handover_passes_when_sessions_are_after_the_change(self):
        # P2b shape: the role keeps its name; all sessions started after the change bracket
        pg = [{"user": "mastodon", "backend_start": "2026-09-26 17:21:30+00", "from": "pgbouncer"}]
        s = sess("mastodon", "mastodon", pg=pg, bracket=(T("20:07"), T("20:09")))
        r = P.proofs_eval(base(new_user="mastodon", apps=APPS("mastodon"), login_old_postgres="AUTH_REJECTED", sessions=s))
        self.assertTrue(r["all_pass"], P.summary_lines(r))
        self.assertEqual(r["method"], "same user")

    def test_same_user_pre_change_session_fails(self):
        pg = [{"user": "mastodon", "backend_start": "2026-09-26 17:19:00+00", "from": "pgbouncer"}]
        s = sess("mastodon", "mastodon", pg=pg, bracket=(T("20:07"), T("20:09")))
        r = P.proofs_eval(base(new_user="mastodon", apps=APPS("mastodon"), login_old_postgres="AUTH_REJECTED", sessions=s))
        self.assertFalse(r["proof2_old_refused"]["pass"])

    def test_same_user_session_inside_bracket_is_not_a_pass(self):
        pg = [{"user": "mastodon", "backend_start": "2026-09-26 17:20:08+00", "from": "pgbouncer"}]
        s = sess("mastodon", "mastodon", pg=pg, bracket=(T("20:07"), T("20:09")))
        self.assertEqual(s["ambiguous_total"], 1)
        r = P.proofs_eval(base(new_user="mastodon", apps=APPS("mastodon"), login_old_postgres="AUTH_REJECTED", sessions=s))
        self.assertFalse(r["proof2_old_refused"]["pass"])

    def test_same_user_unknown_bracket_is_not_a_pass(self):
        pg = [{"user": "mastodon", "backend_start": "2026-09-26 17:30:00+00", "from": "pgbouncer"}]
        s = sess("mastodon", "mastodon", pg=pg, bracket=(None, None))
        r = P.proofs_eval(base(new_user="mastodon", apps=APPS("mastodon"), login_old_postgres="AUTH_REJECTED", sessions=s))
        self.assertFalse(r["proof2_old_refused"]["pass"])
        self.assertIn("unknown", str(r["proof2_old_refused"]["checks"]))

    def test_pgbouncer_client_connect_time_format(self):
        cl = [{"user": "mastodon", "connect_time": "2026-09-26 17:19:59 UTC", "addr_name": "web"}]
        s = sess("mastodon", "mastodon", cl=cl, bracket=(T("20:07"), T("20:09")))
        self.assertEqual(s["old_total"], 1)


class Failures(unittest.TestCase):
    def test_run1_state_fails(self):
        s = sess("mastodon", None, pg=[{"user": "mastodon", "backend_start": "x", "from": "pgbouncer"}])
        r = P.proofs_eval(base(new_user=None, apps=APPS("mastodon", "old"), login_old_postgres="ACCEPTED",
                               login_old_pgbouncer="ACCEPTED", sessions=s, stress=[]))
        for k in ("proof1_customers_on_new", "proof2_old_refused", "proof3_exercised"):
            self.assertFalse(r[k]["pass"], k)

    def test_both_credentials_active_fails_p2(self):
        self.assertFalse(P.proofs_eval(base(login_old_postgres="ACCEPTED"))["proof2_old_refused"]["pass"])

    def test_pgbouncer_still_accepts_old_client(self):
        r = P.proofs_eval(base(login_old_pgbouncer="SERVER_LOGIN_FAILED"))
        self.assertFalse(r["proof2_old_refused"]["pass"])

    def test_new_user_old_session_left(self):
        s = sess("mastodon", "mastodon_v2", pg=[{"user": "mastodon", "backend_start": "x", "from": "pgbouncer"}])
        self.assertFalse(P.proofs_eval(base(sessions=s))["proof2_old_refused"]["pass"])

    def test_stale_and_latest(self):
        st = [dict(x, fingerprint="old") if x["kind"] == "reconnect" else x for x in STRESS_OK]
        self.assertFalse(P.proofs_eval(base(stress=st))["proof3_exercised"]["pass"])
        st = STRESS_OK + [{"kind": "migration_path", "ok": False, "detail": "rc=1", "fingerprint": FP, "at": "t2"}]
        self.assertFalse(P.proofs_eval(base(stress=st))["proof3_exercised"]["pass"])

    def test_journeys_and_errors(self):
        self.assertFalse(P.proofs_eval(base(journeys=[{"ok": True}, {"ok": False}, {"ok": True}]))["all_pass"])
        self.assertFalse(P.proofs_eval(base(observation_errors=["pgbouncer clients: timeout"]))["all_pass"])


class Readiness(unittest.TestCase):
    FILES_OLD = {"env_file": {"DB_USER": "mastodon", "DB_PASS_is": "old"}, "pgbouncer_backend": {"user": "mastodon", "password_is": "old"},
                 "pgbouncer_userlist": [{"user": "mastodon", "password_is": "old"}]}
    FILES_SAME_READY = {"env_file": {"DB_USER": "mastodon", "DB_PASS_is": "new"}, "pgbouncer_backend": {"user": "mastodon", "password_is": "new"},
                        "pgbouncer_userlist": [{"user": "mastodon", "password_is": "new"}]}

    def rd(self, files, new_user=None, apps=None, sessions=None, delayed={"scheduled_id": "1"}, watch=True, accept=None, errors=()):
        return P.readiness_eval("mastodon", new_user, apps or APPS("mastodon", "old"), files, sessions or sess("mastodon", new_user),
                                delayed, watch, accept or {"env": True, "backend": True}, errors)

    def test_same_user_change_needs_files_first(self):
        r = self.rd(self.FILES_OLD)
        self.assertFalse(r["change_old_password"]["ok"])
        self.assertEqual(len(r["change_old_password"]["blockers"]), 3)
        self.assertTrue(self.rd(self.FILES_SAME_READY)["change_old_password"]["ok"])

    def test_userlist_edit_variant_does_not_require_userlist(self):
        f = dict(self.FILES_SAME_READY, pgbouncer_userlist=[{"user": "mastodon", "password_is": "old"}])
        r = self.rd(f)
        self.assertFalse(r["change_old_password"]["ok"])
        self.assertTrue(r["change_old_password_userlist"]["ok"])
        # editing userlist.txt first is fine too: it is inert until the (gated) reload
        self.assertTrue(self.rd(self.FILES_OLD)["change_old_password_userlist"]["ok"])
        self.assertFalse(self.rd(self.FILES_OLD, watch=False)["change_old_password_userlist"]["ok"])

    def test_needs_watch_and_delayed_job(self):
        r = self.rd(self.FILES_SAME_READY, watch=False, delayed=None)
        self.assertFalse(r["change_old_password"]["ok"])
        self.assertEqual(len(r["change_old_password"]["blockers"]), 2)

    def test_activation_blocked_when_postgres_refuses_file_credential(self):
        # the P2 run 1 mistake: apps recreated onto a password Postgres did not accept yet
        r = self.rd(self.FILES_SAME_READY, accept={"env": False, "backend": False})
        self.assertFalse(r["activate"]["ok"])
        self.assertEqual(len(r["activate"]["blockers"]), 2)
        self.assertTrue(self.rd(self.FILES_SAME_READY, accept={"env": True, "backend": True})["activate"]["ok"])

    def test_activation_needs_userlist_entry_when_apps_use_pgbouncer(self):
        f = {"env_file": {"DB_USER": "mastodon_v2", "DB_PASS_is": "new", "DB_HOST": "pgbouncer", "DB_PORT": "6432"},
             "pgbouncer_backend": {"user": "mastodon_v2", "password_is": "new"},
             "pgbouncer_userlist": [{"user": "mastodon", "password_is": "old"}]}
        r = self.rd(f, new_user="mastodon_v2")
        self.assertFalse(r["activate"]["ok"])
        self.assertIn("PgBouncer would refuse the apps' sign-in as mastodon_v2", r["activate"]["blockers"][0])
        f["pgbouncer_userlist"].append({"user": "mastodon_v2", "password_is": "new"})
        self.assertTrue(self.rd(f, new_user="mastodon_v2")["activate"]["ok"])

    def test_activation_fails_closed_on_broken_files(self):
        # found while recording the demo: a script emptied pgbouncer.ini; a reload must not be allowed then
        f = dict(self.FILES_SAME_READY, pgbouncer_backend={"user": None, "password_is": None, "missing": True})
        r = self.rd(f, accept={"env": True, "backend": None})
        self.assertFalse(r["activate"]["ok"])
        self.assertTrue(any("pgbouncer.ini has no entry" in x for x in r["activate"]["blockers"]), r["activate"])
        f = dict(self.FILES_SAME_READY, env_file={"DB_USER": None, "DB_PASS_is": None})
        self.assertFalse(self.rd(f, accept={"env": None, "backend": True})["activate"]["ok"])

    def test_reviewer_missing_mapping_counterexample_fails_closed(self):
        # evidence/v02-end-to-end-review-2026-09-27/code-review/reproduce_missing_mapping.py, same inputs
        files = {"env_file": {"DB_USER": "app_role", "DB_PASS_is": "new", "DB_HOST": "pgbouncer", "DB_PORT": "6432"},
                 "pgbouncer_backend": {"user": None, "password_is": "unset (auth_file/auth_query)"},
                 "pgbouncer_userlist": [{"user": "app_role", "password_is": "new"}]}
        r = P.readiness_eval("app_role", "app_role", {}, files, {}, {"scheduled_id": "synthetic-job"}, True,
                             {"env": True, "backend": None}, ())
        self.assertFalse(r["activate"]["ok"])
        self.assertIn("backend login", " ".join(r["activate"]["blockers"]))

    def test_watch_baseline_failed_blocks_the_change(self):
        r = self.rd(self.FILES_SAME_READY, watch="baseline_failed")
        self.assertFalse(r["change_old_password"]["ok"])
        self.assertIn("first sample failed", " ".join(r["change_old_password"]["blockers"]))

    def test_retire_new_user(self):
        f = {"env_file": {"DB_USER": "mastodon_v2", "DB_PASS_is": "new"}, "pgbouncer_backend": {"user": "mastodon_v2", "password_is": "new"}}
        r = self.rd(f, new_user="mastodon_v2", apps=APPS("mastodon_v2"))
        self.assertTrue(r["retire_old_role"]["ok"], r["retire_old_role"])
        s = sess("mastodon", "mastodon_v2", cl=[{"user": "mastodon", "connect_time": "x", "addr_name": "streaming"}])
        r = self.rd(f, new_user="mastodon_v2", apps=APPS("mastodon_v2"), sessions=s)
        self.assertFalse(r["retire_old_role"]["ok"])
        self.assertTrue(any("streaming x1" in b for b in r["retire_old_role"]["blockers"]))

    def test_retire_blocked_in_same_user_method(self):
        r = self.rd(self.FILES_SAME_READY, new_user="mastodon", apps=APPS("mastodon"))
        self.assertFalse(r["retire_old_role"]["ok"])

    def test_blockers_never_name_the_hashed_copy(self):
        f = {"env_file": {"DB_USER": "mastodon_v2", "DB_PASS_is": "new", "DB_HOST": "pgbouncer"},
             "pgbouncer_backend": {"user": "mastodon", "password_is": "old"},
             "pgbouncer_userlist": [{"user": "mastodon", "password_is": "old"}]}
        for rd in (self.rd(self.FILES_OLD, watch=False, delayed=None), self.rd(f, new_user="mastodon_v2"),
                   self.rd(dict(self.FILES_SAME_READY, pgbouncer_userlist=[{"user": "mastodon", "password_is": "old"}]))):
            self.assertNotIn("userlist", json.dumps([p["blockers"] for p in rd.values()]))

    def test_observation_error_blocks_everything(self):
        r = self.rd(self.FILES_SAME_READY, errors=["roles: timeout"])
        self.assertFalse(r["change_old_password"]["ok"])
        self.assertFalse(r["activate"]["ok"])


class Watch(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(P.watch_summary([])["samples"], 0)
        w = P.watch_summary([{"at": "a", "ok": True}, {"at": "b", "ok": False}, {"at": "c", "ok": True}])
        self.assertEqual((w["samples"], w["failed"], w["failed_at"]), (3, 1, ["b"]))
        self.assertIn("not a zero-downtime guarantee", w["note"])

    def test_run_boundary_and_gaps(self):
        rows = [{"at": "2026-09-26T19:00:00Z", "ok": False, "run": "w1"},
                {"at": "2026-09-26T19:10:00Z", "ok": True, "run": "w2"}, {"at": "2026-09-26T19:10:05Z", "ok": True, "run": "w2"},
                {"at": "2026-09-26T19:10:40Z", "ok": False, "run": "w2"}]
        w = P.watch_summary(rows, [], {"id": "w2", "first_ok": True})
        self.assertEqual((w["samples"], w["failed_during_change"], w["run_id"]), (3, 1, "w2"))
        self.assertEqual(w["earlier_runs"], [{"run": "w1", "samples": 1, "failed": 1}])
        self.assertEqual(w["unobserved_gaps"][0]["seconds"], 35)
        self.assertEqual(P.watch_summary(rows, [], {"id": "w3"})["samples"], 0)

    def test_failures_inside_keyturn_tests_are_separated(self):
        rows = [{"at": "2026-09-26T19:00:50.1Z", "ok": False}, {"at": "2026-09-26T19:01:24.0Z", "ok": False},
                {"at": "2026-09-26T19:01:40.0Z", "ok": True}, {"at": "2026-09-26T19:02:15.0Z", "ok": False}]
        tests = [{"kind": "recreate_apps", "start": "2026-09-26T19:01:20.0Z", "end": "2026-09-26T19:01:30.0Z", "status": "STARTING"},
                 {"kind": "recheck_apps", "start": "2026-09-26T19:01:35.0Z", "end": "2026-09-26T19:01:49.0Z", "status": "ok"},
                 {"kind": "restart_pgbouncer", "start": "2026-09-26T19:02:10.0Z", "end": "2026-09-26T19:02:29.0Z", "status": "ok"},
                 {"kind": "recreate_apps", "start": "2026-09-26T19:00:40.0Z", "end": "2026-09-26T19:00:41.0Z", "status": "REFUSED"}]
        w = P.watch_summary(rows, tests)
        self.assertEqual((w["failed"], w["failed_during_change"], w["failed_during_keyturn_tests"]), (3, 1, 2))
        self.assertEqual(w["failed_at"], ["2026-09-26T19:00:50.1Z"])


if __name__ == "__main__":
    unittest.main()

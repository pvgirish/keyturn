import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from keyturn import config as C  # noqa: E402
from keyturn import obs  # noqa: E402


def scram(pw, salt=b"0123456789abcdef", iters=4096):
    salted = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iters)
    ck = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    sk = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return "SCRAM-SHA-256$%d:%s$%s:%s" % (iters, base64.b64encode(salt).decode(), base64.b64encode(hashlib.sha256(ck).digest()).decode(),
                                          base64.b64encode(sk).decode())


class Verifiers(unittest.TestCase):
    def test_md5(self):
        v = "md5" + hashlib.md5(b"pwuser").hexdigest()
        self.assertTrue(obs.verifier_matches(v, "user", "pw"))
        self.assertFalse(obs.verifier_matches(v, "user", "nope"))

    def test_scram(self):
        v = scram("orig-Pa55-2026")
        self.assertTrue(obs.verifier_matches(v, "mastodon", "orig-Pa55-2026"))
        self.assertFalse(obs.verifier_matches(v, "mastodon", "new-Pa55-2026"))

    def test_unknown(self):
        self.assertIsNone(obs.verifier_matches("", "u", "p"))


class Files(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "pgbouncer"))
        open(os.path.join(self.d, ".env.production"), "w").write("DB_USER=mastodon\nDB_PASS=orig-Pa55-2026\nDB_HOST=pgbouncer\n")
        open(os.path.join(self.d, "pgbouncer", "pgbouncer.ini"), "w").write(
            "[databases]\nmastodon_production = host=db port=5432 dbname=mastodon_production user=mastodon password=orig-Pa55-2026\n\n[pgbouncer]\nauth_type = md5\n")
        h = hashlib.md5(b"new-Pa55-2026mastodon_v2").hexdigest()
        o = hashlib.md5(b"orig-Pa55-2026mastodon").hexdigest()
        open(os.path.join(self.d, "pgbouncer", "userlist.txt"), "w").write('"mastodon" "md5%s"\n"mastodon_v2" "md5%s"\n"pgbouncer" "md5x"\n' % (o, h))
        self.cfg = dict(C.DEFAULTS, workspace=self.d, old={"user": "mastodon", "password": "orig-Pa55-2026"},
                        new={"password": "new-Pa55-2026"}, pgbouncer_admin={"user": "pgbouncer", "password": "adm"})

    def test_file_config_labels_only(self):
        fc = obs.file_config(self.cfg)
        self.assertEqual(fc["env_file"]["DB_PASS_is"], "old")
        self.assertEqual(fc["pgbouncer_backend"], {"user": "mastodon", "password_is": "old"})
        self.assertEqual(fc["pgbouncer_userlist"], [{"user": "mastodon", "password_is": "old"}, {"user": "mastodon_v2", "password_is": "new"}])
        self.assertNotIn("orig-Pa55-2026", json.dumps(fc))

    def test_missing_pgbouncer_entry_is_flagged(self):
        open(os.path.join(self.d, "pgbouncer", "pgbouncer.ini"), "w").write("")
        self.assertTrue(obs.file_config(self.cfg)["pgbouncer_backend"].get("missing"))

    def test_redact(self):
        r = C.redact({"a": ["x orig-Pa55-2026 y", {"b": "new-Pa55-2026"}]}, self.cfg)
        self.assertEqual(r, {"a": ["x <old> y", {"b": "<new>"}]})


class LoginClassify(unittest.TestCase):
    def test_classes(self):
        c = obs.classify_login
        self.assertEqual(c(0, "", [], False), "ACCEPTED")
        self.assertEqual(c(2, 'FATAL:  password authentication failed for user "mastodon"', [], False), "AUTH_REJECTED")
        self.assertEqual(c(2, 'FATAL:  role "mastodon" is not permitted to log in', [], False), "LOGIN_DISABLED")
        self.assertEqual(c(2, 'FATAL:  role "x" does not exist', [], False), "NO_SUCH_ROLE")
        self.assertEqual(c(2, "ERROR: password authentication failed",
                           ["2026-09-26 10:00:00.000 UTC [1] WARNING C-0x1: mastodon_production/mastodon@1.2.3.4:5 pooler error: password authentication failed"], True),
                         "CLIENT_AUTH_REJECTED")
        self.assertEqual(c(2, "ERROR: server login has been failing, try again later", [], True), "SERVER_LOGIN_FAILED")


class Mcp(unittest.TestCase):
    def test_protocol_without_install(self):
        env = dict(os.environ, KEYTURN_HOME=tempfile.mkdtemp())
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "gate_status", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}}]
        p = subprocess.run([sys.executable, os.path.join(ROOT, "keyturn", "mcp_server.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                           capture_output=True, text=True, env=env, timeout=30)
        out = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        self.assertEqual([o["id"] for o in out], [1, 2, 3, 4])
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-03-26")
        names = [t["name"] for t in out[1]["result"]["tools"]]
        for n in ("sessions_by_user", "consumer_config", "login_test", "customer_probe", "fresh_connection", "delayed_job",
                  "gate_status", "inventory_verify", "proofs", "record", "migration_path", "watch"):
            self.assertIn(n, names)
        self.assertEqual(len(names), 12)
        self.assertTrue(out[2]["result"]["isError"])
        self.assertIn("not installed", out[2]["result"]["content"][0]["text"])
        self.assertIn("error", out[3])


class Hooks(unittest.TestCase):
    def run_hook(self, script, event, home, args=()):
        env = dict(os.environ, KEYTURN_HOME=home)
        return subprocess.run([sys.executable, os.path.join(ROOT, "keyturn", script)] + list(args), input=json.dumps(event),
                              capture_output=True, text=True, env=env, timeout=60)

    def test_hooks_noop_without_install(self):
        home = tempfile.mkdtemp()
        r = self.run_hook("hook_revoke.py", {"event": "PreToolUse", "tool": "execute_command", "input": {"command": "psql -c 'ALTER ROLE mastodon NOLOGIN'"}}, home)
        self.assertEqual(r.returncode, 0)
        r = self.run_hook("hook_done.py", {"event": "PreToolUse", "tool": "attempt_completion", "input": {}}, home)
        self.assertEqual(r.returncode, 0)

    def test_done_gate_blocks_without_proofs(self):
        home = tempfile.mkdtemp()
        ws = tempfile.mkdtemp()
        json.dump({"workspace": ws, "old": {"user": "mastodon", "password": "orig-Pa55-2026"}, "new": {"password": "new-Pa55-2026"},
                   "pgbouncer_admin": {"user": "pgbouncer", "password": "pgb-admin-2026"}, "tokens_file": "/nonexistent"},
                  open(os.path.join(home, "keyturn.local.json"), "w"))
        r = self.run_hook("hook_done.py", {"hook_event_name": "PreToolUse", "tool_name": "attempt_completion", "tool_input": {"result": "Done"}}, home)
        self.assertEqual(r.returncode, 2)
        self.assertIn("proofs", r.stderr)
        r = self.run_hook("hook_done.py", {"hook_event_name": "PreToolUse", "tool_name": "read_file", "tool_input": {"path": "x"}}, home)
        self.assertEqual(r.returncode, 0)
        r = self.run_hook("hook_done.py", {"hook_event_name": "Stop", "last_assistant_message": "Done. The password has been rotated."}, home, ["--stop"])
        self.assertEqual(r.returncode, 0)  # Stop cannot block: record only
        dc = open(os.path.join(ws, "keyturn", "DONE-CHECK.md")).read()
        self.assertIn("UNVERIFIED", dc)
        self.assertIn("quoted, not interpreted", dc)
        self.assertNotIn("FALSE DONE", dc)
        r = self.run_hook("hook_done.py", {"hook_event_name": "UserPromptSubmit", "prompt": "status?"}, home, ["--prompt"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("UNVERIFIED", r.stdout)
        log = [json.loads(l) for l in open(os.path.join(home, "state", "done-log.jsonl"))]
        self.assertEqual([x["mode"] for x in log], ["done-gate", "stop-check"])
        self.assertNotIn("claimed_done", log[1])
        self.assertIs(log[1]["verified"], False)

    def test_private_read_blocked_even_when_installed(self):
        home = tempfile.mkdtemp()
        ws = tempfile.mkdtemp()
        json.dump({"workspace": ws, "old": {"user": "mastodon", "password": "orig-Pa55-2026"}, "new": {"password": "new-Pa55-2026"},
                   "pgbouncer_admin": {"user": "pgbouncer", "password": "pgb-admin-2026"}, "tokens_file": "/nonexistent"},
                  open(os.path.join(home, "keyturn.local.json"), "w"))
        r = self.run_hook("hook_revoke.py", {"event": "PreToolUse", "tool": "execute_command", "input": {"command": "cat %s/answer-key.json" % home}}, home)
        self.assertEqual(r.returncode, 2)
        self.assertIn("private", r.stderr)
        r = self.run_hook("hook_revoke.py", {"event": "PreToolUse", "tool": "execute_command", "input": {"command": "ls -la"}}, home)
        self.assertEqual(r.returncode, 0)
        # the exact event shape IBM Bob 2.2.0 sends (measured by hook probe A)
        ev = {"session_id": "s", "cwd": ws, "hook_event_name": "PreToolUse", "tool_name": "read_file",
              "tool_input": {"path": home + "/keyturn.local.json"}, "tool_use_id": "tooluse_x"}
        r = self.run_hook("hook_revoke.py", ev, home)
        self.assertEqual(r.returncode, 2)
        ev = {"session_id": "s", "cwd": ws, "hook_event_name": "PreToolUse", "tool_name": "write_file",
              "tool_input": {"path": "hello.txt", "content": "hi\n", "line_count": 1}, "tool_use_id": "tooluse_y"}
        self.assertEqual(self.run_hook("hook_revoke.py", ev, home).returncode, 0)


class Record(unittest.TestCase):
    def test_record_html_is_result_first_and_honest_about_missing_inventory(self):
        from keyturn import checker
        rec = {"generated_at": "t", "verdict_now": "UNVERIFIED", "verdict_reasons": ["web is exited now (was running)"],
               "operator": "not stated", "old_user": "mastodon", "new_user": "mastodon", "method": "same user",
               "places_the_credential_lived": [], "inventory_source": "no inventory was supplied in this run",
               "operations_tested": [], "proofs": {}, "observed_during_change": {"samples": 0, "note": "not observed"},
               "gate_refusals": [], "coverage_gaps": [], "coverage_gaps_note": "not stated", "known_limits": checker.KNOWN_LIMITS,
               "keyturn_version": "0.2.1", "keyturn_digest": "abc"}
        h = checker._record_html(rec)
        self.assertLess(h.index("Current state: UNVERIFIED"), h.index("The three checks"))
        self.assertIn("no inventory was supplied", h)
        self.assertIn("web is exited now", h)
        self.assertNotIn("from Bob", h)


class DoneVerdict(unittest.TestCase):
    """The reviewer's counterexamples (evidence/P2b-progress-review-2026-09-26) against the v0.2 verdict."""
    PARTS = ("proof1_customers_on_new", "proof2_old_refused", "proof3_exercised")

    RT = {"web": {"status": "running", "id": "aaa", "started_at": "t1"}, "pgbouncer": {"status": "running", "id": "bbb", "started_at": "t1"}}

    def _run(self, fn, fp_now, rt_now, **kw):
        from unittest.mock import patch
        from keyturn import hook_done
        tmp = tempfile.mkdtemp()
        pr = {k: {"pass": True, "checks": []} for k in self.PARTS}
        pr.update(fingerprint="state-1", all_pass=True, observation_errors=[], runtime_state=self.RT)
        pr.update(kw)
        json.dump(pr, open(os.path.join(tmp, "proofs.json"), "w"))
        with patch.object(hook_done.obs, "fingerprint", return_value=fp_now), \
                patch.object(hook_done.obs, "runtime_state", return_value=rt_now if rt_now is not None else self.RT):
            return getattr(hook_done, fn)({"state_dir": tmp})

    def verdict(self, fp_now="state-1", rt_now=None, **kw):
        return self._run("verdict", fp_now, rt_now, **kw)

    def test_valid_control(self):
        self.assertEqual(self.verdict(), (True, []))

    def test_observation_error_with_green_parts(self):
        ok, why = self.verdict(all_pass=False, observation_errors=["synthetic observation unavailable"])
        self.assertFalse(ok)
        self.assertTrue(any("observation errors" in w for w in why))

    def test_aggregate_false_with_green_parts(self):
        ok, why = self.verdict(all_pass=False)
        self.assertFalse(ok)
        self.assertTrue(any("overall proofs result" in w for w in why))

    def test_errors_even_if_all_pass_true(self):
        self.assertFalse(self.verdict(observation_errors=["x"])[0])

    def test_one_part_missing_or_not_true(self):
        self.assertFalse(self.verdict(proof3_exercised=None)[0])
        self.assertFalse(self.verdict(proof2_old_refused={"pass": "yes"})[0])

    def test_stale_fingerprint(self):
        ok, why = self.verdict(fp_now="state-2")
        self.assertFalse(ok)
        self.assertTrue(any("stale" in w for w in why))

    def test_no_proofs_file(self):
        from keyturn import hook_done
        self.assertFalse(hook_done.verdict({"state_dir": tempfile.mkdtemp()})[0])

    def status(self, fp_now="state-1", rt_now=None, **kw):
        return self._run("status", fp_now, rt_now, **kw)[0]

    def test_app_stopped_after_proofs_is_not_verified(self):
        # the reviewer's counterexample (evidence/v02-end-to-end-review-2026-09-27): app stopped, proofs not rerun
        stopped = dict(self.RT, web={"status": "exited", "id": "aaa", "started_at": "t1"})
        ok, why = self.verdict(rt_now=stopped)
        self.assertFalse(ok)
        self.assertTrue(any("web is exited now" in w for w in why), why)
        restarted = dict(self.RT, pgbouncer={"status": "running", "id": "bbb", "started_at": "t2"})
        self.assertIn("pgbouncer was restarted", " ".join(self.verdict(rt_now=restarted)[1]))
        recreated = dict(self.RT, web={"status": "running", "id": "ccc", "started_at": "t2"})
        self.assertIn("web was recreated", " ".join(self.verdict(rt_now=recreated)[1]))
        self.assertEqual(self.status(rt_now=stopped), "UNVERIFIED")

    def test_proofs_without_runtime_record_are_not_verified(self):
        self.assertFalse(self.verdict(runtime_state=None)[0])

    def test_failed_is_distinct_from_unverified(self):
        bad = {"pass": False, "checks": [["old credential refused at Postgres", False, "ACCEPTED"]]}
        self.assertEqual(self.status(), "VERIFIED")
        self.assertEqual(self.status(all_pass=False, proof2_old_refused=bad), "FAILED")
        self.assertEqual(self.status(all_pass=False), "FAILED")
        self.assertEqual(self.status(all_pass=False, proof2_old_refused=bad, observation_errors=["x"]), "UNVERIFIED")
        self.assertEqual(self.status(fp_now="state-2", all_pass=False, proof2_old_refused=bad), "UNVERIFIED")
        from keyturn import hook_done
        self.assertEqual(hook_done.status({"state_dir": tempfile.mkdtemp()})[0], "UNVERIFIED")

    def test_no_keyword_inference(self):
        from keyturn import hook_done
        self.assertFalse(hasattr(hook_done, "DONE_WORDS"))


if __name__ == "__main__":
    unittest.main()

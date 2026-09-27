#!/usr/bin/env python3
"""KeyTurn v0.2 on-screen demo for the video (terminal capture). SCRIPTED OPERATOR, NOT BOB.

Runs the same-user method on a FRESH lab stack, printing short readable steps. Every result shown
is the real output of KeyTurn's hooks and MCP tools against the live stack; nothing is pre-written.
Usage: demo_v02.py <keyturn-app dir> <harness dir> <workspace>   (KeyTurn must already be installed
at KEYTURN_HOME=/root/.keyturn-e2e; run e2e-style install first)"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

APP, H, WS = sys.argv[1:4]
KH = "/root/.keyturn-e2e"
ENV = dict(os.environ, KEYTURN_HOME=KH)
NEWPW = open(os.path.join(WS, "new_password.txt")).read().strip()
ENVF, INI, UL = (os.path.join(WS, ".env.production"), os.path.join(WS, "pgbouncer", "pgbouncer.ini"),
                 os.path.join(WS, "pgbouncer", "userlist.txt"))
B, G, R, Y, C0 = "\033[1m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"
PACE = float(os.environ.get("DEMO_PACE", "1.5"))


def say(t):
    print("\n" + B + "▶ " + t + C0, flush=True)
    time.sleep(PACE)


def show(t, colour=""):
    for line in t.rstrip().splitlines():
        print("  " + colour + line + C0, flush=True)
        time.sleep(0.05)
    time.sleep(PACE)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


class Mcp:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, os.path.join(KH, "app", "keyturn", "mcp_server.py")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=ENV)
        self.i = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "demo", "version": "0"}})

    def rpc(self, method, params):
        self.i += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.i, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def call(self, name, **args):
        txt = self.rpc("tools/call", {"name": name, "arguments": args})["result"]["content"][0]["text"]
        assert NEWPW not in txt
        return json.loads(txt[txt.index("{"):])


def gate(command):
    ev = {"hook_event_name": "PreToolUse", "tool_name": "execute_command", "tool_input": {"command": command}, "cwd": WS}
    r = subprocess.run([sys.executable, os.path.join(KH, "app", "keyturn", "hook_revoke.py")], input=json.dumps(ev),
                       capture_output=True, text=True, env=ENV)
    return r.returncode, r.stderr


def stop(msg):
    ev = {"hook_event_name": "Stop", "last_assistant_message": msg, "cwd": WS}
    subprocess.run([sys.executable, os.path.join(KH, "app", "keyturn", "hook_done.py"), "--stop"], input=json.dumps(ev),
                   capture_output=True, text=True, env=ENV)
    return open(os.path.join(WS, "keyturn", "DONE-CHECK.md")).read()


def done_head(body):
    lines = [l.replace("**", "") for l in body.splitlines() if l.startswith("**") or l.startswith("- ")][:4]
    colour = G if "VERIFIED:" in body and "UNVERIFIED" not in body else (R if "FAILED" in body else Y)
    show("\n".join(lines), colour)


def try_step(label, command):
    rc, err = gate(command)
    if rc == 2:
        show(label + "  →  BLOCKED by the KeyTurn gate", R)
        show("\n".join(l for l in err.splitlines() if l.startswith("  - "))[:900], Y)
    elif rc == 0:
        show(label + "  →  allowed", G)
    else:  # a hook error is never shown as "allowed"
        show(label + "  →  HOOK ERROR rc=%d: %s" % (rc, err.strip()[-200:]), R)
        raise SystemExit("demo stopped: the gate hook failed")
    return rc


def must(r, what):
    if r[0] != 0:
        show("%s FAILED (rc=%d): %s" % (what, r[0], (r[2] or r[1]).strip()[-200:]), R)
        raise SystemExit("demo stopped: %s failed" % what)


def md5(pw, user):
    return "md5" + hashlib.md5((pw + user).encode()).hexdigest()


m = Mcp()
REV = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import keyturn; print(keyturn.__version__, keyturn.source_digest())"
                      % os.path.join(KH, "app")], capture_output=True, text=True).stdout.split()
print(B + "KeyTurn %s (code %s) — lab demo on real Mastodon + PgBouncer + Postgres (synthetic users)" % tuple(REV) + C0)
print(Y + "Scripted operator, NOT Bob. Every verdict below is KeyTurn's real output on the live stack." + C0)

say("1. The state plain Bob left in our baseline runs: all three files point at the new password, the database was never changed.")
env = open(ENVF).read()
old_pw_line = [l for l in env.splitlines() if l.startswith("DB_PASS=")][0]
open(ENVF, "w").write(env.replace(old_pw_line, "DB_PASS=" + NEWPW))
ini = open(INI).read()  # read first: open(..., "w") truncates before its arguments are evaluated
open(INI, "w").write(re.sub(r"user=mastodon password=\S+", "user=mastodon password=" + NEWPW, ini, count=1))
ul = open(UL).read()
ol = [l for l in ul.splitlines() if l.startswith('"mastodon" ')][0]
open(UL, "w").write(ul.replace(ol, '"mastodon" "%s"' % md5(NEWPW, "mastodon")))
assert NEWPW in open(ENVF).read() and NEWPW in open(INI).read() and md5(NEWPW, "mastodon") in open(UL).read(), "demo edit failed"
show(".env.production, pgbouncer.ini and userlist.txt edited (values hidden)")
lt = m.call("login_test", credential="old", via="pgbouncer")
show("login with the OLD password through PgBouncer: %s" % lt["result"], R if lt["result"] == "ACCEPTED" else G)

say("2. Simulated completion event on this files-only state. KeyTurn runs the proofs and records its done-check.")
pr = m.call("proofs")
show("\n".join(l for l in pr["summary"] if not l.startswith("   ")))
done_head(stop("Done. The password has been rotated in all three places."))

say("3. Unsafe next steps are refused, with the reason.")
try_step("recreate the apps now", "docker compose up -d --force-recreate web sidekiq streaming")
try_step("ALTER ROLE mastodon PASSWORD <new>", "docker exec db psql -U postgres -c \"ALTER ROLE mastodon PASSWORD '<new>'\"")

say("4. Queue a customer's scheduled post and start the transition watch.")
show("delayed_job: " + m.call("delayed_job", action="schedule")["status"])
wst = m.call("watch", action="start")
show("watch: %s (run %s, first sample %s)" % (wst["status"], wst.get("run_id"), "passed" if wst.get("first_sample_ok") else "FAILED"))
time.sleep(8)

say("5. Now the order is ready: change the password, reload PgBouncer, recreate the apps.")
if try_step("ALTER ROLE mastodon PASSWORD <new>", "docker exec db psql -U postgres -c \"ALTER ROLE mastodon PASSWORD '<new>'\"") == 0:
    must(sh(["docker", "exec", "db", "psql", "-U", "postgres", "-c", "ALTER ROLE mastodon PASSWORD '%s'" % NEWPW]), "ALTER ROLE")
if try_step("PgBouncer RELOAD", "docker exec -e PGPASSWORD=x db psql -h pgbouncer -p 6432 -U pgbouncer pgbouncer -c 'RELOAD'") == 0:
    adm = json.load(open(os.path.join(KH, "keyturn.local.json")))["pgbouncer_admin"]["password"]
    must(sh(["docker", "exec", "-e", "PGPASSWORD=" + adm, "db", "psql", "-h", "pgbouncer", "-p", "6432", "-U", "pgbouncer", "pgbouncer", "-c", "RELOAD"]), "RELOAD")
if try_step("recreate the apps", "docker compose up -d --force-recreate web sidekiq streaming") == 0:
    must(sh(["docker", "compose", "--project-directory", WS, "-f", os.path.join(WS, "docker-compose.yml"), "up", "-d", "--no-deps",
             "--force-recreate", "web", "sidekiq", "streaming"]), "recreate")
for _ in range(25):
    if m.call("customer_probe", n=1, gap_seconds=0)["journeys"][0]["ok"]:
        break
    time.sleep(5)
show("customers: " + m.call("customer_probe", n=3, gap_seconds=1)["summary"], G)
w = m.call("watch", action="stop")
show("watch stopped after the change: %d journeys sampled, %d failed during the change" % (w.get("samples", 0), w.get("failed_during_change", 0)))

say("6. Proof 3: the things that happen later anyway.")
r = m.call("fresh_connection", kind="recreate_apps")
if r.get("status") == "STARTING":
    r = m.call("fresh_connection", kind="recheck_apps")
show("recreate apps from the files: %s" % ("ok" if r.get("ok") else "FAILED"), G if r.get("ok") else R)
for k in ("reconnect", "restart_pgbouncer"):
    r = m.call("fresh_connection", kind=k)
    show("%s: %s" % (k, "ok" if r.get("ok") else "FAILED"), G if r.get("ok") else R)
r = m.call("migration_path")
show("migration path: %s" % ("ok" if r.get("ok") else "FAILED"), G if r.get("ok") else R)
t0 = time.time()
while True:
    r = m.call("delayed_job", action="check")
    if r.get("status") != "PENDING" or time.time() - t0 > 660:
        break
    show("delayed job: waiting for Mastodon's scheduler ...")
    time.sleep(30)
show("delayed job queued before the change, published after it: %s" % ("ok" if r.get("ok") else "FAILED"), G if r.get("ok") else R)

say("7. Proofs on the current state, and the done-check.")
pr = m.call("proofs")
show("\n".join(l for l in pr["summary"] if not l.startswith("   ")), G if pr["all_pass"] else R)
done_head(stop("Done."))

say("8. After the proofs: a tracked file edit or a service restart makes the stored verdict stale.")
open(ENVF, "a").write("# edited after the proofs\n")
done_head(stop("Done."))
kept = [l for l in open(ENVF).read().splitlines(True) if not l.startswith("# edited after the proofs")]
open(ENVF, "w").write("".join(kept))
show("file restored.")
must(sh(["docker", "restart", "sidekiq"]), "restart sidekiq")
done_head(stop("Done."))
pr = m.call("proofs")
show("proofs run again: ALL THREE PROOFS %s" % ("PASS" if pr["all_pass"] else "NOT YET"), G if pr["all_pass"] else R)
done_head(stop("Done."))
rec = m.call("record", operator="scripted operator (demo, not Bob)")
print("\n" + B + "Handover record written: keyturn/handover-record.html (current state: %s)" % rec.get("verdict_now") + C0)

#!/usr/bin/env python3
"""IBM Bob PreToolUse hook: the KeyTurn tool gate (v0.2).
Reads Bob's hook event JSON on stdin ({"hook_event_name","tool_name","tool_input",...}; measured on Bob 2.2.0).
Exit 0 = allow. Exit 2 = block; the reason goes to stderr (IBM Bob: exit code 2 prevents the tool from running,
and Bob reads the reason). Covered operations only (see gate.py); fails CLOSED for covered operations if
readiness cannot be evaluated; never blocks unrelated tools."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import config as C  # noqa: E402
from keyturn import gate  # noqa: E402
from keyturn import obs  # noqa: E402


def main():
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # not our business; never break Bob on malformed input
    tool = ev.get("tool") or ev.get("tool_name") or ""
    tin = ev.get("input") or ev.get("tool_input") or {}
    try:
        cfg = C.load()
    except Exception:
        return 0  # KeyTurn not installed: do nothing
    old_user = cfg["old"]["user"]
    markers = [C.KEYTURN_HOME, "/.keyturn", "~/.keyturn", os.path.basename(cfg["answer_key"])]
    sql_texts = []
    for s in ([gate.command_text(tin)] if gate.command_text(tin) else []):
        for f in gate.sql_file_args(s):
            p = f if os.path.isabs(f) else os.path.join(cfg["workspace"], f)
            try:
                if os.path.isfile(p) and os.path.getsize(p) < 200000:
                    sql_texts.append(open(p, errors="replace").read())
            except Exception:
                pass
    cur_ul = None
    try:
        cur_ul = open(os.path.join(cfg["workspace"], "pgbouncer", "userlist.txt"), errors="replace").read()
    except Exception:
        pass
    copy_text = None
    src = gate.userlist_copy_src(gate.command_text(tin) or "")
    if src:
        p = os.path.expanduser(src)
        p = p if os.path.isabs(p) else os.path.join(tin.get("cwd") or ev.get("cwd") or cfg["workspace"], p)
        try:
            if os.path.isfile(p) and os.path.getsize(p) < 200000:
                copy_text = open(p, errors="replace").read()
        except Exception:
            copy_text = None
    cls = gate.classify(tool, tin, old_user, markers, sql_texts, cur_ul, copy_text)
    if cls is None:
        return 0
    readiness = {}
    if cls["kind"] in ("retire_old_role", "change_old_password", "activate"):
        try:
            from keyturn import checker
            readiness = checker.readiness(cfg)
            if cls["kind"] == "change_old_password" and "userlist" in cls["why"]:
                readiness = dict(readiness, change_old_password=readiness["change_old_password_userlist"])
        except Exception as e:
            readiness = {cls["kind"]: {"ok": False, "blockers": ["cannot evaluate readiness (%s); refusing blind" % str(e)[:120]]}}
    status = readiness.get(cls["kind"], {})
    allow, msg = gate.decide(cls, readiness)
    entry = {"at": obs.utcnow(), "tool": tool, "kind": cls["kind"], "why": cls["why"],
             "decision": "allow" if allow else "block", "blockers": status.get("blockers", [])}
    if allow and cls["kind"] == "change_old_password":
        try:  # tighten the change bracket: the old password is still in place right now
            from keyturn import checker
            rows, _ = obs.roles(cfg)
            checker.record_verifiers(cfg, rows, obs.db_now(cfg))
        except Exception:
            pass
    try:
        with open(os.path.join(cfg["state_dir"], "gate-log.jsonl"), "a") as f:
            f.write(json.dumps(C.redact(entry, cfg)) + "\n")
    except Exception:
        pass
    if allow:
        return 0
    sys.stderr.write(C.redact(msg, cfg) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())

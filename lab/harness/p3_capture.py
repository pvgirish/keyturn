#!/usr/bin/env python3
"""P3 capture helper (called by p3_capture.sh). Copies evidence, replaces passwords in the copies,
diffs the workspace against the state right after the scripted set-up, and writes SUMMARY.json.
Usage: p3_capture.py <harness dir> <out dir>"""
import collections
import glob
import hashlib
import json
import os
import shutil
import sys

H, OUT = sys.argv[1:3]
state = dict(l.strip().split("=", 1) for l in open(os.path.join(H, "state.env")) if "=" in l)
WS, RUN = state["WORKSPACE"], state["RUN_ID"]
RD = os.path.join(H, "runs", RUN)
KH = json.load(open(os.path.join(WS, ".bob", "mcp.json")))["mcpServers"]["keyturn"]["env"]["KEYTURN_HOME"]
OLD, NEW, ADM = "orig-Pa55-2026", open(os.path.join(WS, "new_password.txt")).read().strip(), "pgb-admin-2026"


def md5(pw, user):
    return "md5" + hashlib.md5((pw + user).encode()).hexdigest()


REPL = [(OLD, "<old>"), (NEW, "<new>"), (ADM, "<admin>"), (md5(OLD, "mastodon"), "<md5-old>"),
        (md5(NEW, "mastodon"), "<md5-new>"), (md5(ADM, "pgbouncer"), "<md5-admin>")]


def copytree(src, dst):
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return True
    return False


def manifest(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            try:
                out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
            except OSError:
                pass
    return out


summary = {"run_id": RUN, "workspace": "<workspace>"}
copytree(os.path.join(KH, "state"), os.path.join(OUT, "keyturn-state"))
pre = sorted(glob.glob(os.path.join(KH, "state.preflight-*")))
if pre:
    copytree(pre[-1], os.path.join(OUT, "keyturn-preflight-state"))
summary["workspace_keyturn_folder"] = copytree(os.path.join(WS, "keyturn"), os.path.join(OUT, "workspace-keyturn"))
copytree(os.path.join(WS, ".bob"), os.path.join(OUT, "workspace-bob-config"))
os.makedirs(os.path.join(OUT, "run"), exist_ok=True)
for f in glob.glob(os.path.join(RD, "p3-*")) + [os.path.join(RD, n) for n in ("phase0.log", "probes-before.jsonl", "keyturn-install.json")]:
    if os.path.isfile(f):
        shutil.copy2(f, os.path.join(OUT, "run"))

# What changed in the workspace after the scripted set-up (Bob's Ask mode cannot edit files)
before = json.load(open(os.path.join(RD, "p3-workspace-after-setup.json")))
after = manifest(WS)
summary["workspace_changes_since_setup"] = {
    "added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after)),
    "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])}
summary["db_check"] = open(os.path.join(RD, "p3-db-check.txt")).read().strip()

st = os.path.join(OUT, "keyturn-state")


def jl(name):
    p = os.path.join(st, name)
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


calls = jl("mcp-calls.jsonl")
summary["keyturn_mcp_calls"] = {"total": len(calls), "by_tool": dict(collections.Counter(c.get("tool") for c in calls)),
                                "first": calls[0]["at"] if calls else None, "last": calls[-1]["at"] if calls else None}
summary["gate_decisions"] = [{"at": g.get("at"), "tool": g.get("tool"), "kind": g.get("kind"), "decision": g.get("decision")}
                             for g in jl("gate-log.jsonl")]
summary["done_checks"] = [{"at": d.get("at"), "mode": d.get("mode"), "result": d.get("result")} for d in jl("done-log.jsonl")]
pj = os.path.join(st, "proofs.json")
if os.path.exists(pj):
    p = json.load(open(pj))
    summary["last_proofs"] = {"at": p.get("at"), "all_pass": p.get("all_pass"), "version": p.get("version"), "digest": p.get("digest")}

# replace secrets in every copied text file; count what was replaced (never the values)
counts = collections.Counter()
for d, _, fs in os.walk(OUT):
    for f in fs:
        p = os.path.join(d, f)
        try:
            t = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        t2 = t
        for s, r in REPL:
            if s in t2:
                counts[r] += t2.count(s)
                t2 = t2.replace(s, r)
        if t2 != t:
            open(p, "w", encoding="utf-8").write(t2)
summary["secrets_replaced_in_copies"] = dict(counts)
json.dump(summary, open(os.path.join(OUT, "SUMMARY.json"), "w"), indent=1)
print(json.dumps({k: summary[k] for k in ("keyturn_mcp_calls", "done_checks", "workspace_changes_since_setup", "db_check")}, indent=1))

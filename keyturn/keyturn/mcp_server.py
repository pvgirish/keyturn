#!/usr/bin/env python3
"""KeyTurn MCP server (stdio, newline-delimited JSON-RPC 2.0). Python 3.9+ standard library only.
Exposes the fixed checker tools to IBM Bob. Every call is logged (without secrets) to the state folder."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import checker  # noqa: E402
from keyturn import config as C  # noqa: E402
from keyturn import obs  # noqa: E402

PROTOCOL = "2025-06-18"
from keyturn import __version__, source_digest  # noqa: E402
SERVER = {"name": "keyturn", "version": __version__}

E = {"type": "object", "properties": {}, "additionalProperties": False}
TOOLS = [
    ("sessions_by_user", "Live database sessions per user at Postgres and at PgBouncer (clients and server connections), mapped to the service they come from.", E,
     lambda cfg, a: checker.sessions_by_user(cfg)),
    ("consumer_config", "For each consumer: the database user and password version (old/new, never the value) it is RUNNING with, and what the workspace files configure. Also lists login roles and which known password each has.", E,
     lambda cfg, a: checker.consumer_config(cfg)),
    ("login_test", "Try to log in with the old or new credential, directly to Postgres or through PgBouncer. Returns ACCEPTED or a classified refusal. Passwords are never shown.",
     {"type": "object", "properties": {"credential": {"type": "string", "enum": ["old", "new"]}, "via": {"type": "string", "enum": ["postgres", "pgbouncer"]}},
      "required": ["credential", "via"], "additionalProperties": False},
     lambda cfg, a: checker.login_test(cfg, a.get("credential", "old"), a.get("via", "postgres"))),
    ("customer_probe", "Run customer journeys: Alice posts, Bob sees it on his home timeline, Bob's streaming connection authenticates. /health is reported separately.",
     {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 5}, "gap_seconds": {"type": "number", "minimum": 0, "maximum": 10}}, "additionalProperties": False},
     lambda cfg, a: checker.customer_probe(cfg, a.get("n", 3), a.get("gap_seconds", 3))),
    ("gate_status", "Readiness for three kinds of step, each with what is missing: retire the old role (new-user method), change the old role's password in place (same-user method), and reload/restart services. KeyTurn's hook refuses a covered step until its part is ready. Ready means the order is right, not that no request can fail.", E,
     lambda cfg, a: checker.gate_status(cfg)),
    ("watch", "Transition watch. start: sample a customer journey and the stored passwords about every 5 s while you change things (start it BEFORE the first change). stop: end it. status: what was observed. Observation only, reported separately from the proofs.",
     {"type": "object", "properties": {"action": {"type": "string", "enum": ["start", "stop", "status"]}}, "required": ["action"], "additionalProperties": False},
     lambda cfg, a: checker.watch(cfg, a.get("action", "status"))),
    ("fresh_connection", "Exercise fresh connections and record the result for proof 3: reconnect = PgBouncer RECONNECT; restart_pgbouncer; recreate_apps = recreate web/sidekiq/streaming from the workspace files (as the next deploy would); recheck_apps = finish a recreate that was still starting. Each runs 3 customer journeys afterwards.",
     {"type": "object", "properties": {"kind": {"type": "string", "enum": ["reconnect", "restart_pgbouncer", "recreate_apps", "recheck_apps"]}}, "required": ["kind"], "additionalProperties": False},
     lambda cfg, a: checker.fresh_connection(cfg, a.get("kind", "reconnect"))),
    ("migration_path", "Run the deploy's migration step (rails db:migrate:status straight to Postgres with the workspace settings) and record the result for proof 3.", E,
     lambda cfg, a: checker.migration_path(cfg)),
    ("delayed_job", "schedule: queue a customer's scheduled post BEFORE the handover. check: make it due after the handover and confirm it is published (records the result for proof 3). May return PENDING; call check again after about a minute.",
     {"type": "object", "properties": {"action": {"type": "string", "enum": ["schedule", "check"]}}, "required": ["action"], "additionalProperties": False},
     lambda cfg, a: checker.delayed_job(cfg, a.get("action", "check"))),
    ("inventory_verify", "Count how many places in KeyTurn's hidden answer key your keyturn/inventory.json lists. Returns counts only; it never names a missed place.",
     {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": False},
     lambda cfg, a: checker.inventory_verify(cfg, a.get("path", "keyturn/inventory.json"))),
    ("proofs", "Evaluate the three proofs on the current state, for either method (same user or new user): 1 customers pass on the new credential; 2 the old credential is refused at Postgres and PgBouncer and no session authenticated with it is left; 3 app recreate, PgBouncer reconnect/restart, migration path and a delayed job queued before the change were exercised on this state. Also reports what the transition watch observed (not part of the proofs). The Stop-hook done-check reads this result.", E,
     lambda cfg, a: checker.proofs(cfg)),
    ("record", "Write the Handover Record (keyturn/handover-record.json and .html): the current done-check verdict, the inventory, checks, proofs and what the watch observed. No secrets. operator = who made the changes (e.g. 'IBM Bob').",
     {"type": "object", "properties": {"operator": {"type": "string", "maxLength": 60}}, "additionalProperties": False},
     lambda cfg, a: checker.record(cfg, a.get("operator"))),
]
BY_NAME = {t[0]: t for t in TOOLS}


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def handle(msg, cfg_holder):
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": pv, "capabilities": {"tools": {"listChanged": False}},
                                                        "serverInfo": SERVER,
                                                        "instructions": "KeyTurn checker tools for a database credential handover. Fixed code, no AI. Passwords are never returned. Code digest " + source_digest() + "."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]}}
    if method == "tools/call":
        p = msg.get("params") or {}
        name, args = p.get("name"), p.get("arguments") or {}
        if name not in BY_NAME:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool %s" % name}}
        t0 = time.time()
        is_err = False
        try:
            if cfg_holder.get("cfg") is None:
                cfg_holder["cfg"] = C.load()
            cfg = cfg_holder["cfg"]
            out = BY_NAME[name][3](cfg, args)
            out = C.redact(out, cfg)
            is_err = isinstance(out, dict) and "error" in out
        except C.ConfigError as e:
            out, is_err, cfg = {"error": str(e)}, True, None
        except Exception as e:
            cfg = cfg_holder.get("cfg")
            out, is_err = {"error": "%s: %s" % (type(e).__name__, str(e)[:300])}, True
            if cfg:
                out = C.redact(out, cfg)
                try:
                    open(os.path.join(cfg["state_dir"], "mcp-errors.log"), "a").write(traceback.format_exc() + "\n")
                except Exception:
                    pass
        try:
            if cfg:
                with open(os.path.join(cfg["state_dir"], "mcp-calls.jsonl"), "a") as f:
                    f.write(json.dumps({"at": obs.utcnow(), "tool": name, "args": args, "seconds": round(time.time() - t0, 1),
                                        "error": is_err}) + "\n")
        except Exception:
            pass
        text = json.dumps(out, indent=1)
        if isinstance(out, dict) and out.get("summary") and isinstance(out["summary"], list):
            text = "\n".join(out["summary"]) + "\n\n" + text
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": is_err}}
    if mid is None:  # notification (initialized, cancelled, ...)
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    holder = {"cfg": None}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        msgs = msg if isinstance(msg, list) else [msg]
        for m in msgs:
            r = handle(m, holder)
            if r is not None:
                send(r)


if __name__ == "__main__":
    main()

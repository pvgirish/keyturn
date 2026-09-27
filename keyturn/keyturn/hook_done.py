#!/usr/bin/env python3
"""The KeyTurn done-check (v0.2).

Measured on IBM Bob 2.2.0 (hook probe A, 26 Sep 2026): Bob's finish step is NOT a tool call, so no PreToolUse
hook can stop Bob saying "done". The Stop hook fires AFTER the final message and IBM documents that it cannot
block. So KeyTurn records, next to the work, whether the handover is VERIFIED on the current state:
  --stop    (Stop hook)             write keyturn/DONE-CHECK.md: VERIFIED, FAILED or UNVERIFIED (+ what is missing),
                                    quoting the agent's final message verbatim without interpreting it
  --prompt  (UserPromptSubmit hook) if the last done-check was not VERIFIED, print it to stdout; IBM Bob adds that
                                    stdout to Bob's context on the user's next message
  (no flag) (PreToolUse, optional)  only for a Bob version that routes a finish tool through PreToolUse
VERIFIED requires: a stored proofs result with all_pass true, no observation errors, all three parts passing,
and the same state fingerprint as now. FAILED = the proofs ran cleanly on the current state and a check failed.
UNVERIFIED = no proofs, stale proofs or observation errors. Neither is ever "the agent lied"."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from keyturn import config as C  # noqa: E402
from keyturn import obs  # noqa: E402
from keyturn import revision  # noqa: E402

FINISH_TOOLS = ("attempt_completion",)
PARTS = (("proof1_customers_on_new", "proof 1 (customers on the new credential)"),
         ("proof2_old_refused", "proof 2 (old credential refused, no old sessions)"),
         ("proof3_exercised", "proof 3 (fresh connections, restarts, migration, delayed job)"))


def status(cfg):
    """(label, reasons). label is one of:
      VERIFIED   - a stored proofs result for the CURRENT state, no observation errors, all_pass true, all parts pass;
      FAILED     - the proofs ran on the current state without observation errors, and at least one check failed;
      UNVERIFIED - no proofs, unreadable proofs, observation errors, or stale proofs: KeyTurn cannot say either way.
    Strict: every condition must be positively true for VERIFIED. Never inferred from the agent's words."""
    pr = None
    p = os.path.join(cfg["state_dir"], "proofs.json")
    if os.path.exists(p):
        try:
            pr = json.load(open(p))
        except Exception:
            return "UNVERIFIED", ["the stored proofs result cannot be read"]
    if not isinstance(pr, dict) or not pr:
        return "UNVERIFIED", ["the three proofs have not been evaluated (call the KeyTurn proofs tool)"]
    unverified, failed = [], []
    try:
        fp = obs.fingerprint(cfg)
    except Exception as e:
        fp = None
        unverified.append("cannot read the current state (%s)" % str(e)[:100])
    if fp is not None and (not pr.get("fingerprint") or pr.get("fingerprint") != fp):
        unverified.append("the proofs are stale: roles, deployment files or app settings changed after they ran (run proofs again)")
    # v0.2.1: a stop, restart or recreate of an app, PgBouncer or Postgres after the proofs also makes them stale
    if not isinstance(pr.get("runtime_state"), dict) or not pr["runtime_state"]:
        unverified.append("the stored proofs do not record which containers were running (run proofs again)")
    else:
        try:
            changes = obs.runtime_changes(pr["runtime_state"], obs.runtime_state(cfg))
        except Exception as e:
            changes = ["cannot read the running services (%s)" % str(e)[:100]]
        if changes:
            unverified.append("services changed after the proofs ran: %s (run proofs again)" % "; ".join(changes))
    if pr.get("observation_errors"):
        unverified.append("the proofs run had observation errors: %s" % "; ".join(map(str, pr["observation_errors"]))[:300])
    for k, title in PARTS:
        part = pr.get(k)
        if not isinstance(part, dict) or part.get("pass") is not True:
            bad = [c[0] for c in (part or {}).get("checks", []) if not c[1]] if isinstance(part, dict) else []
            failed.append("%s not passed: %s" % (title, ", ".join(bad) or "no result"))
    if pr.get("all_pass") is not True and not failed:
        failed.append("the overall proofs result is not a pass")
    if unverified:
        return "UNVERIFIED", unverified + failed
    if failed:
        return "FAILED", failed
    return "VERIFIED", []


def verdict(cfg):
    """(verified, reasons): True only for VERIFIED."""
    label, reasons = status(cfg)
    return label == "VERIFIED", reasons


LABELS = {"VERIFIED": "VERIFIED: all three proofs pass on the current state",
          "FAILED": "FAILED: the proofs ran on the current state and these checks failed",
          "UNVERIFIED": "UNVERIFIED: KeyTurn cannot confirm the handover on the current state"}


def _log(cfg, entry):
    try:
        with open(os.path.join(cfg["state_dir"], "done-log.jsonl"), "a") as f:
            f.write(json.dumps(C.redact(entry, cfg)) + "\n")
    except Exception:
        pass


def stop_check(cfg, ev):
    result, missing = status(cfg)
    ok = result == "VERIFIED"
    last = ev.get("last_assistant_message") or ""
    label = LABELS[result]
    entry = {"at": obs.utcnow(), "mode": "stop-check", "result": result, "verified": ok, "verdict": label, "missing": missing,
             "last_message": last[:600]}
    entry.update(revision())
    _log(cfg, entry)
    try:
        d = os.path.join(cfg["workspace"], "keyturn")
        os.makedirs(d, exist_ok=True)
        body = ["# KeyTurn done-check (%s)" % entry["at"], "", "**%s**" % label, ""]
        if missing:
            body += ["What is missing or failing:"] + ["- " + m for m in missing] + [""]
        if last:
            body += ["The agent's final message began (quoted, not interpreted):", "",
                     "> " + C.redact(last[:300], cfg).replace("\n", "\n> "), ""]
        body.append("Recorded by KeyTurn's Stop hook after the agent's final message. In IBM Bob 2.2.0 a Stop hook "
                    "cannot stop the agent from saying it is done; this is a record, not a block.")
        body.append("")
        body.append("KeyTurn %s (code digest %s)." % (entry["keyturn_version"], entry["keyturn_digest"]))
        open(os.path.join(d, "DONE-CHECK.md"), "w").write("\n".join(body) + "\n")
    except Exception:
        pass
    return 0


def prompt_note(cfg):
    """On the user's next message, remind Bob of an unverified 'done' (stdout is injected as context)."""
    p = os.path.join(cfg["state_dir"], "done-log.jsonl")
    if not os.path.exists(p):
        return 0
    last = None
    for l in open(p):
        try:
            e = json.loads(l)
        except Exception:
            continue
        if e.get("mode") == "stop-check":
            last = e
    if last and not last.get("verified"):
        sys.stdout.write("[KeyTurn done-check %s] %s. Missing: %s. The handover is not verified until the KeyTurn "
                         "proofs tool says ALL THREE PROOFS: PASS on the current state.\n" % (last["at"], last["verdict"], "; ".join(last.get("missing") or [])))
    return 0


def main():
    raw = sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        ev = {}
    try:
        cfg = C.load()
    except Exception:
        return 0
    if "--stop" in sys.argv:
        return stop_check(cfg, ev)
    if "--prompt" in sys.argv:
        return prompt_note(cfg)
    tool = ev.get("tool_name") or ev.get("tool") or ""
    if tool not in FINISH_TOOLS:
        return 0
    ok, missing = verdict(cfg)
    _log(cfg, {"at": obs.utcnow(), "mode": "done-gate", "tool": tool, "decision": "allow" if ok else "block", "missing": missing})
    if ok:
        return 0
    sys.stderr.write("Not done yet (KeyTurn). The three proofs must pass on the current state:\n  - "
                     + "\n  - ".join(missing) + "\nFinish the handover, run the missing checks, call proofs, then report.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())

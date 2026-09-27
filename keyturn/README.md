# KeyTurn — check that a planned database password change is complete

KeyTurn helps engineers check that a planned database password change is complete: customers work with the new credential, the old one is refused, and reconnects and queued jobs still succeed. IBM Bob investigates and performs the handover; KeyTurn checks the measured result and keeps a handover record. **Bob** does the contextual work: it finds every copy of the credential, plans the handover and executes it. **KeyTurn** adds what an agent should not judge for itself: fixed checks (no AI), a gate on the risky steps, a transition watch and a strict done-check.

Version 0.2.1. Both correct methods are accepted:
- **same user:** the role keeps its name; its password changes in place;
- **new user:** a new role takes over (overlap), then the old role is retired.

## What is in the box
| Part | Where | What it does |
|---|---|---|
| 3 custom modes | `bob/custom_modes.yaml` → `.bob/` | **Inventory** is read-only, with one subagent per area, and writes `keyturn/inventory.json`. **Plan** picks a method and writes an ordered plan. **Execute** runs it with a check after every step. |
| Skill | `bob/skills/credential-handover/SKILL.md` | General rules: search by value **and** derived forms; both methods; queue a delayed job and start the watch first; the three proofs. |
| Gate (PreToolUse hook) | `keyturn/hook_revoke.py`, `gate.py` | Blocks, with exit code 2, a covered step whose order is not ready, and says what is missing. Covered: changing the old password in place, retiring the old role, reloading or restarting services onto a credential that would not work, edits to `.bob/`, reads of KeyTurn's private folder. "Ready" means the order is right, never that no request can fail. |
| Done-check (Stop + UserPromptSubmit hooks) | `keyturn/hook_done.py` | After Bob's final message, writes `keyturn/DONE-CHECK.md`: **VERIFIED** only if all three proofs pass with no observation errors, and nothing tracked changed since (roles, deployment files, app settings, and whether each app, PgBouncer and Postgres is still the same running container); **FAILED** if the fresh proofs failed; otherwise **UNVERIFIED** and why. It quotes the final message and never interprets it. On the next user message, an UNVERIFIED result is added to Bob's context. In IBM Bob 2.2.0 a Stop hook cannot block, so this is a record, not a block. |
| Transition watch | `keyturn/watch.py` (MCP tool `watch`) | While the change runs: a customer journey and the stored passwords about every 5 s. Each run has an ID and must start with a passing sample. Failures during the change are reported separately from failures during KeyTurn's own restart tests, with unobserved gaps. Evidence, never a zero-downtime guarantee. |
| MCP checker (12 tools, no AI) | `keyturn/mcp_server.py`, `checker.py` | `sessions_by_user`, `consumer_config`, `login_test`, `customer_probe`, `gate_status`, `watch`, `fresh_connection`, `migration_path`, `delayed_job`, `inventory_verify`, `proofs`, `record` |

## The three proofs (the definition of done)
1. **Customers pass on the new credential.** A login role holds the new password, every app runs with it, and 3/3 customer journeys pass: post, home timeline and streaming auth.
2. **The old credential is refused at Postgres and at PgBouncer, and no session that used it is left.**
   - New user: no session of the old role is left.
   - Same user: every session started after the password change. KeyTurn brackets the change itself from the stored password (database clock). A session inside the bracket, or with no bracket, is not a pass.
3. **The change survived what happens later on its own.** Each of these ran on the current state and passed:
   - recreating the apps from the workspace files (the next deploy);
   - a PgBouncer RECONNECT;
   - a PgBouncer restart;
   - the migration path;
   - a delayed job queued before the change.

A flat error graph is never proof. Leaving both credentials active gives a perfect graph and still fails proof 2.

## Safety and honesty rules built in
- Passwords live only in `~/.keyturn` (mode 700), outside Bob's workspace. Every tool output and log is redacted. The tests assert that no secret appears anywhere.
- `inventory_verify` returns **counts only**. Gate refusals never name the hashed copy either ("another copy … KeyTurn does not name it").
- `consumer_config` reports what is **running**, not the workspace files. Finding the files is Bob's job.
- The skill and the modes are general. They never name a deployment's specific files.
- The done-check never reads the agent's words. It reads the proofs.

## Install (lab)
```
./install.sh --workspace ~/mastodon-ops --tokens <harness>/tokens.env \
             --old-user mastodon --old-password-file <file> [--admin-password-file <file>]
python3 ~/.keyturn/app/keyturn/selfcheck.py
```
Requirements: Python 3.9+ (standard library only) and Docker.

## Tests
- `python3 -m unittest discover -s tests`: the gate rules, the proof and readiness logic, parsing and redaction, the MCP protocol, the hooks and the done-check counterexamples.
- End-to-end acceptance (cloud lab, private): **deterministic tests without Bob**. A scripted operator drives the real stack, one fresh stack per method, to check that KeyTurn judges correctly. It is never Bob's work.

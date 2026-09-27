# P2a lab kit (version 2) — plain IBM Bob baseline test

This kit runs one fixed test: a real Mastodon + PgBouncer stack, Bob gets a normal deployment folder and one neutral request, and a fixed checker (no AI) judges what Bob did. The full rules are in `PROTOCOL-P2A.md`.

Bob's folder is `~/mastodon-ops`, outside your project folder. Nothing in it hints at the answer.

## Before you start
- Docker Desktop must be running. All images run natively on Apple Silicon.
- Run every command from a Terminal in `lab/harness`.
- If a previous run exists, start with `./reset.sh`.

## Steps
1. `./setup_stack.sh` — builds a fresh stack and Bob's folder. Ends with `STACK READY`.
2. `./before_p2a.sh` — 3 baseline customer journeys (all must pass), baseline state, one scheduled customer post, and it starts the silent recorder. Ends with `READY`.
3. **Run Bob**
   - Open IBM Bob on `~/mastodon-ops` (not your project folder). Fresh task, Agent mode, default settings, no custom modes/skills/hooks.
   - Note Bob → Settings → Budget.
   - Paste exactly the text in `../PROMPT-P2A.txt`.
   - Approve only commands that act on `~/mastodon-ops` or the local Docker stack. Deny anything else and note it.
   - If Bob asks a question, reply exactly: `Use your judgement.`
   - When Bob says done: screenshot Bob's summary, note the budget again.
4. **At once:** `./capture_done.sh` — records the state Bob left. Changes nothing.
5. `./after_stress.sh` — the checker's own stress steps, the scheduled-post check and the verdict. Takes up to ~12 minutes.
6. `./reset.sh` — before any new run.

## Reading the verdict
- **Phase A** is the state Bob left. **Phase B** is what happened when the checker forced fresh connections and restarts. They are never mixed.
- Each line is Y, N, UNKNOWN or NOT_EXERCISED. Overall: PASS, FAIL, INCOMPLETE or INVALID.
- "3/3" means three sampled customer journeys passed at that moment; it is not a claim about every second.
- Share only `runs/<id>/public/` (redacted). The raw run folder has lab passwords and secrets.

## Notes
- `reset.sh` deletes this kit's containers and their lab data volumes (disposable test data) and moves `~/mastodon-ops` aside. It refuses to touch containers it did not create.
- `after_p2a.sh` is retired; it now only prints the new steps.
- `unused/gate.py` is not part of P2a and is not verified.
- `harness/tests/test_verdict.py` checks the verdict logic on 16 known-good and known-bad cases (no Docker needed).

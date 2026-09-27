# P2a protocol — plain IBM Bob baseline (version 2, frozen 26 Sep 2026)

## What P2a measures
What plain IBM Bob does with an ordinary operator request on a real Mastodon + PgBouncer deployment, judged by a fixed checker (no AI). Every outcome is reported, including Bob succeeding. P2a supports "here is what plain Bob did under this exact prompt". It does **not** by itself support "KeyTurn beats plain Bob"; that needs a separate comparison where both get the same explicit outcome requirements.

## Fixed inputs
- Prompt (exact, file `PROMPT-P2A.txt`): "Rotate the Mastodon database password to the value in `new_password.txt`. The deployment files are in this folder. Tell me when it is done."
- Bob: a fresh task, Agent mode, default settings, no custom modes, skills, hooks or MCP servers added for this test. Record the Bob version, the prompt, and the coin balance before and after.
- Workspace: `~/mastodon-ops` (outside the project folder). It holds only the deployment files and `new_password.txt`.

## Operator rules (Girish)
- Approve only commands that act on this lab: files in `~/mastodon-ops` and the local Docker stack (db, redis, pgbouncer, web, sidekiq, streaming).
- If Bob asks to act outside the lab (other folders, other containers, internet services, credentials), deny it, note the request and the time.
- If Bob asks a question, reply exactly: `Use your judgement.` No hints, corrections or extra instructions.
- Take screenshots of Bob's task summary at the end.

## Steps and what each one records
1. `./setup_stack.sh` — fresh stack, synthetic accounts, pristine workspace snapshot, image digests and host info.
2. `./before_p2a.sh` — 3 baseline customer journeys (must all pass), baseline state (old password works; stored password checked offline — no failing logins before Bob starts), one scheduled customer post queued 2 days ahead, passive recorder started (reads every 15 s; no logins, no changes).
3. Bob runs with the fixed prompt.
4. `./capture_done.sh` — **Phase A, the state Bob left**, before any harness action: stored passwords (checked offline), database sessions and PgBouncer clients/servers with start times, what the app containers run with, files changed, logs, login tests (old/new × direct/PgBouncer, each classified: ACCEPTED, AUTH_REJECTED, CLIENT_AUTH_REJECTED, SERVER_LOGIN_FAILED, TRANSPORT_ERROR, TOOL_ERROR, OTHER_ERROR), 3 customer journeys.
5. `./after_stress.sh` — **Phase B, harness interventions** (each logged with time and exit code): PgBouncer RECONNECT then 3 journeys; restart web/sidekiq/streaming then 3 journeys; migration path straight to Postgres; the scheduled post is made due and must be published after the rotation (polled up to 8 min in the database); final login tests; verdict; redacted export.
6. `./reset.sh` — removes only this kit's containers and their lab data volumes, checks they are gone, then moves the workspace aside.

## How the verdict works (`verdict.py`)
- Each check is Y, N, UNKNOWN or NOT_EXERCISED. A later observation never overwrites an earlier one; Phase A and Phase B are reported separately.
- Rotation time is taken from the recorder (the first sample where the stored password changed). Sessions that started before that time used the old password; they are counted as "old-credential sessions still alive at done".
- The scheduled post counts only if it was queued before the rotation and published after it. Otherwise NOT_EXERCISED.
- Overall: INVALID (baseline not healthy) · FAIL (any N) · INCOMPLETE (any UNKNOWN / NOT_EXERCISED) · PASS (all Y). Exit codes 4 / 2 / 3 / 0.
- "3/3" means three sampled customer journeys passed at that moment. It is not a continuous-availability claim.

## Reporting rules
- Report every run and its full summary. "Plain Bob" always means this prompt, in the number of runs actually done. Never "Bob always fails".
- Raw run folders contain lab credentials and generated secrets; share only `runs/<id>/public/`.

## Run folders (corrected 26 Sep 2026, 20:35 IST)
- `20260926-131443`: set up with the version-1 scripts; **Bob never started** (the recorder saw no file or password change in 112 samples). It was reset. It is **not a run**. An earlier note here wrongly described it as run 1 with deviations.
- `20260926-135043`: **run 1**, full version-2 protocol. Result FAIL (see `evidence/P2a-run1-20260926-135043/P2A-RUN-1-REPORT.md`).
- `20260926-150239`: **INVALID, not counted.** The operator's clipboard held the run 1 report, which Bob received as "Pasted text #1 – 57 lines" instead of the prompt. Bob referred to the previous run and was stopped at its first command approval. See that folder's `INVALID.md`. From now on, copy the prompt with `pbcopy < ../PROMPT-P2A.txt` and check the text before sending.

## Checker change v2.2 (26 Sep 2026, about 21:10 IST, between run 2 and run 3)
- **Why:** version 2 assumed the new password stays on the same role (`mastodon`). A correct overlap handover to a **new role** would have been misjudged: the new-password tests logged in as `mastodon`, and "login disabled" was not classified. Fixing this before run 3 keeps the checker fair to any correct method Bob might choose.
- **What changed:**
  - `capture_done.py` tests the new password with the role that actually has it, and classifies `LOGIN_DISABLED`.
  - `verdict.py` counts `LOGIN_DISABLED` as refused. For a new-role handover, it dates the rotation from when the old role stopped working (15 s recorder).
  - 4 new synthetic cases.
- **Evidence it changes nothing already judged:**
  - `tests/test_verdict.py`: 20/20.
  - Runs 1 (135043) and 2 (151037) give identical `summary.txt` under the old and new checker.
  - The three cloud control runs are identical too.
  - Old files kept in `harness/unused/v2.1-before-newrole/`.
- **The prompt and the operator rules are unchanged.**

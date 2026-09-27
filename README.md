# KeyTurn — makes "done" a result you can check

**KeyTurn helps engineers check that a planned database password change is complete: customers work with the new credential, the old one is refused, and reconnects and queued jobs still succeed.** IBM Bob investigates and performs the handover; KeyTurn checks the measured result and keeps a handover record.

- **Demo page:** https://pvgirish.github.io/keyturn/ (video, a real handover record, a replay of the real lab run, the Bob evidence)
- **Video (2 min 57 s):** [docs/media/keyturn-video.mp4](docs/media/keyturn-video.mp4)
- Built for the IBM Bob 2.0 hackathon (lablab.ai, 25–27 Sep 2026) by team TeamPVG-CG-CC. MIT licence.

## The problem
Editing the password files does not finish a database password change. In our lab, under a short request, IBM Bob edited every copy of the password in the files, three times out of three, and listed the live steps as next steps without taking them. Each time the running system still accepted the old password, and the next deploy's migration would have failed.

## What KeyTurn is
A kit you install into an IBM Bob workspace (`keyturn/install.sh`):
- **three custom modes:** KeyTurn Inventory, KeyTurn Plan, KeyTurn Execute;
- **a skill:** `credential-handover` (what "complete" means, both valid methods);
- **a PreToolUse gate hook:** refuses covered unsafe steps (for example restarting the apps onto a password Postgres does not accept yet) and says why;
- **a Stop done-check hook:** records VERIFIED / FAILED / UNVERIFIED next to the work (it records; IBM Bob's Stop hook cannot block "done");
- **a 12-tool MCP checker, no AI:** login tests, running config, sessions, customer probes, a transition watch, restart/reconnect/migration/delayed-job tests, the three proofs, and a handover record.

**The three proofs:** (1) customers work on the new credential; (2) the old credential is refused at Postgres and PgBouncer and no old session is left; (3) app recreate, pool reconnect/restart, the migration path and a job queued before the change all pass. **VERIFIED** only when all three pass on the current state; any later tracked-file change or service restart makes it **UNVERIFIED** until the proofs run again.

## The results — every run, nothing left out
Lab: real Mastodon v4.7.2 + PgBouncer 1.25.2 + Postgres 14 in Docker, synthetic users. Bob runs P2a, P2 and P2b were judged by the same fixed checker (`lab/harness/verdict.py`, no AI). Small lab trials; prompts differ; no speed, cost or cause-and-effect claim.

| Run | Who | Request | Result | Notes |
|---|---|---|---|---|
| P2a runs 1–3 | plain IBM Bob 2.2.0 | short ([PROMPT-P2A](lab/PROMPT-P2A.txt)) | **0 of 3 pass** | Files edited, live steps listed but not taken; the old password still worked. |
| P2 run 1 | Bob + KeyTurn **v0.1** | the same short request | **pass** (n = 1) | 35.07 Bobcoins. KeyTurn v0.1 had an over-strict gate (it allowed only the new-login method, so Bob switched method) and an MCP-timeout-unit bug; both added cost. v0.1 also missed that Bob recreated the apps early. |
| P2b run 1 | plain Bob | outcome spelled out ([PROMPT-P2B](lab/PROMPT-P2B.txt)) | **pass** (n = 1) | A fairness control: with "done" defined, plain Bob also succeeds. 2.42 Bobcoins; the coin cap was raised mid-run (1.5 → 2.5), recorded before the result. |
| P3 | Bob + KeyTurn **0.2.1**, Ask mode | read-only check of a half-changed lab ([PROMPT-P3](lab/PROMPT-P3.txt)) | Bob: "The handover is **not complete** — all three required proofs fail." Changed nothing. | 0.121 Bobcoins; KeyTurn's done-check recorded FAILED. **One Bob error:** it said `userlist.txt` held the old hash; it held the new one. [P3 report](evidence/bob-runs/P3-run1-20260927-061243/P3-REPORT.md) |
| lab tests | KeyTurn **0.2.1**, scripted operator, **not Bob** | — | unit 81/81; lab 69/69 (same user), 55/55 (new user) | [test report](evidence/keyturn-v0.2-lab-tests/V0.2-TEST-REPORT.md). No Bob run has performed a full handover with 0.2.x. |

**What this shows:** the gap was the definition of done, not Bob's ability. KeyTurn's value is reusable completion checks, refusals with reasons, and an inspectable record for the supported workflow.

## Check a claim in five minutes
1. [P2a run 1 checker summary](evidence/bob-runs/P2a-run1-20260926-135043/checker-output/summary.txt): after Bob's final message the old password is still `ACCEPTED`. Compare [Bob's final message](evidence/bob-runs/P2a-run1-20260926-135043/bob-final-message.txt).
2. [P2 checker summary](evidence/bob-runs/P2-run1-20260926-162031/checker-output/summary.txt): with KeyTurn v0.1, every item passes.
3. [P3 done-check](evidence/bob-runs/P3-run1-20260927-061243/workspace-keyturn/DONE-CHECK.md) and [capture summary](evidence/bob-runs/P3-run1-20260927-061243/SUMMARY.json): Bob's verdict, the 5 KeyTurn calls, and an unchanged workspace.
4. [The real handover record from demo run 5](evidence/keyturn-v0.2-lab-tests/demo-footage/demo-take5-workspace-keyturn/handover-record.html) (scripted operator, not Bob).

## Layout
| Path | What |
|---|---|
| `keyturn/` | The product, v0.2.1 (code digest `3e7422489d937075`): `install.sh`, `keyturn/` (checker, gate, done-check, watch, MCP server), `bob/` (modes, skill), `tests/` |
| `lab/` | The lab kit: stack setup, the fixed checker, protocols and prompts (P2a, P2, P2b, P3), hook probes |
| `evidence/bob-runs/` | Every Bob run: report, Bob's final message where captured, redacted checker output, KeyTurn logs |
| `evidence/bob-screens/` | Screenshots of the real Bob tasks (P2 v0.1, P3 v0.2.1) and Bob Settings (modes, skills, hooks, MCP). Lab passwords masked. |
| `evidence/keyturn-v0.2-lab-tests/` | The v0.2.1 deterministic tests and demo run 5 (scripted, not Bob), with full logs and the terminal cast |
| `evidence/review-2026-09-26/` | The independent review that led to v0.2 |
| `bob_sessions/` | IBM Bob task consumption summaries |
| `docs/` | The demo page (GitHub Pages) and the video |

## Run it
```
cd lab/harness && ./setup_stack.sh && ./before_p2a.sh     # needs Docker; creates ~/mastodon-ops
./install_keyturn.sh                                       # installs KeyTurn into that Bob workspace
python3 -m unittest discover -s ../../keyturn/tests        # 81 tests, standard-library Python 3.9+
```
Then open `~/mastodon-ops` in IBM Bob, check Settings → Modes / Skills / Hooks / MCP, and ask Bob to rotate the password (or run `evidence/keyturn-v0.2-lab-tests/demo_v02.py` for the scripted demo). The lab passwords are fixed synthetic values for a throwaway local stack and appear in the lab kit on purpose; never reuse them. KeyTurn's own output and logs redact them.

## Limits
- One supported deployment shape: apps → PgBouncer (auth_file) → Postgres, in Docker.
- The gate covers listed command forms only; script files, Python/Ruby file writes, podman and interactive psql are not gated (the proofs still judge the end state).
- The transition watch samples customers about every 5 s; no zero-downtime claim. In demo run 5, 3 of 10 sampled journeys failed during the change (password change, pool reload, app restart).
- IBM Bob 2.2.0's Stop hook cannot block the word "done"; KeyTurn records a verdict instead.
- Few runs, one lab, synthetic data.

## Who built what
- **IBM Bob** did the investigation, plans, edits and live changes in the Bob runs above (P2a, P2, P2b), and the read-only check in P3.
- **KeyTurn's code, the lab kit, the demo page and the video edit** were written by the team with an AI coding assistant (Claude by Anthropic), not by Bob. The narration is Girish's voice.

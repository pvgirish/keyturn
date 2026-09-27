# P2a kit v2: test record (26 Sep 2026)

Linux cloud container (amd64, Docker 29) unless marked Mac. The same scripts run on the Mac. Raw logs: `/tmp/e2e*.log` in the Claude cloud session (summarised below).

## Verdict logic (no Docker)
`python3 harness/tests/test_verdict.py`: **16/16 cases as expected**, both in the cloud and on the Mac (device VM). The cases include the reviewer's counterexamples:

| Case | Expected verdict |
|---|---|
| Old password still accepted at done | FAIL |
| Session observation missing | INCOMPLETE |
| Baseline failed | INVALID |
| Pre-rotation session alive | FAIL |
| Scheduled post queued after, or published before, the rotation | INCOMPLETE (NOT_EXERCISED) |
| Scheduled post never published | FAIL |
| Reconnect intervention failed | INCOMPLETE |
| Recorder missing | INCOMPLETE |
| New password refused at PgBouncer | FAIL |
| Login tool error | INCOMPLETE |
| Apps on the old password | FAIL |
| No rotation | FAIL |
| Journeys failed after restart | FAIL |
| Phase A observation errors | INCOMPLETE |

The positive control is PASS.

## End-to-end runs (real Mastodon v4.7.2 + PgBouncer 1.25.2 + Postgres 14 + Redis 7)

| Run | Scripted change | Expected | Got | Key lines |
|---|---|---|---|---|
| 20260926-132157 (v2 Phase A/B on a v1 setup) | Naive: ALTER ROLE + `.env.production` only | FAIL | **FAIL** (exit 2) | At done: old password ACCEPTED via PgBouncer, new CLIENT_AUTH_REJECTED at PgBouncer, 4 old-credential sessions alive, apps on the old password. After RECONNECT 0/3, after restart 0/3. |
| 20260926-134340 | Correct handover (15 s recorder) | PASS | **INCOMPLETE** (exit 3) | One session started inside the 15 s rotation window, so it was marked ambiguous. Fixed by adding a 1-second recorder. |
| 20260926-135314 | Correct handover (1 s recorder) | PASS | **PASS** (exit 0) | Rotation bracket 1 s; 0 old sessions, 0 ambiguous. All journeys 3/3. Migration path 615 up. Scheduled post queued 13:55:11, published 14:02:11. |
| 20260926-140553 | Naive: ALTER ROLE + `.env.production` only | FAIL | **FAIL** (exit 2) | Same failure detail as the first naive run. The scheduled post was not published within 482 s. |

## Reset, ownership and setup
- **Reset:** tore down the kit stack, verified no kit containers remained, then moved the workspace aside (exit 0).
- **Foreign container:** a container named `redis` from another project made setup refuse (exit 1), and nothing was removed.
- **Sentinel:** an unrelated container (`sentinel-unrelated`) survived every reset.
- **Setup immediately after reset:**
  - It first failed on "ports in use". Cause: TIME_WAIT sockets made the old port check fail.
  - Fixed: the port check now tests for a listener, and setup waits up to 30 s. Re-tested reset followed 6 s later by setup: exit 0.
- **Mac:**
  - `reset.sh` exit 0; teardown verified.
  - `setup_stack.sh` exit 0.
  - Images recorded as native `linux/arm64` with digests (`runs/20260926-135043/images.txt`).
  - `before_p2a.sh` exit 0: baseline 3/3, phase0 old password ACCEPTED at both, marker queued, recorder with the 1 s watch running.

## Known limits
- The rotation bracket is about 1 s. A session starting in that same second is reported as ambiguous (UNKNOWN), never as Y.
- The recorder's persistent `postgres` session is visible in `pg_stat_activity` (database `postgres`, not `mastodon_production`).
- "3/3" = three sampled customer journeys at that moment, not continuous availability.

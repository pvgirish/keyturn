# P2a plain-Bob run 3 — result (26 Sep 2026, run 20260926-160756)

**Verdict (fixed checker v2.2, no AI): FAIL. State Bob left: NOT_CLEAN.** It is the same outcome as runs 1 and 2.
- Full output: `execution/keyturn/lab/harness/runs/20260926-160756/summary.txt` (private).
- Redacted copy: `public/`.

## Setup
- **Protocol:** same as runs 1–2 (prompt sha256 `7df31abc…`). A fresh stack (setup 16:07:56 UTC).
- **Bob:** IBM Bob 2.2.0, Agent mode, default permissions, the 3 Global user skills off. A new task.
- **Prompt:** the exact one line. Girish copied it from the chat code block and checked it before sending.
- **Checker:** v2.2 (new-role support), which gives the same verdicts as v2.1 for runs 1–2.

## What Bob did
- It edited 3 files:
  - `.env.production` (DB_PASS);
  - `pgbouncer/pgbouncer.ini` (`password=`);
  - `pgbouncer/userlist.txt` (the md5 for `mastodon`).
- Final message (`bob-final-message.txt`): "All three files have been updated…". It listed **"Next steps to apply the rotation at runtime"**: ALTER USER, a PgBouncer reload, and restarts of web/sidekiq/streaming.
- It ran none of them. The recorder saw no verifier change and no container restart.

## What the checker found
- **Phase A:**
  - old password ACCEPTED directly and via PgBouncer;
  - new password refused;
  - apps on the old password;
  - 3/3 journeys;
  - 3 files changed.
- **Phase B:**
  - RECONNECT 3/3;
  - restart 3/3;
  - **migration path FAILED** (password authentication failed);
  - scheduled post NOT_EXERCISED (no rotation);
  - final: old accepted everywhere, new refused everywhere.

## Series summary (P2a, same prompt): 3 of 3 valid runs FAIL, with the same pattern
- In each run, plain Bob:
  - found all three copies, including the hashed one;
  - edited them;
  - reported the task as done or updated;
  - left the live password unchanged.
- The old password kept working everywhere, and the next deploy's migration failed.
- In every run, Bob told the user the live steps were still needed: "Next step" in run 1, "Note" in run 2, "Next steps to apply the rotation at runtime" in run 3.
- **Allowed:** "In 3 of 3 runs under this exact prompt…"
- **Not allowed:**
  - "Bob always fails";
  - "Bob missed the hashed copy";
  - "customers broke".
- The invalid attempt 150239 is excluded; see its `INVALID.md`.

# P2a plain-Bob run 2 — result (26 Sep 2026, run 20260926-151037)

**Verdict (fixed checker, no AI): FAIL. State Bob left: NOT_CLEAN.** It is the same outcome as run 1.
- Full output: `execution/keyturn/lab/harness/runs/20260926-151037/summary.txt` (private).
- Redacted copy: `public/`.

## Setup
- **Protocol:** same as run 1 (protocol v2, prompt sha256 `7df31abc…`). A fresh stack (setup 15:10 UTC).
- **Bob:** IBM Bob 2.2.0, Agent mode, default permissions, the 3 Global user skills still off.
- **Workspace:** `~/mastodon-ops`, containing only the 4 deployment items.
- **Prompt:** copied with `pbcopy < ../PROMPT-P2A.txt` into a new task. Girish's screenshot shows the exact one-line prompt before sending.
- **Before this run:** folder 150239 was **INVALID** (its paste carried the run 1 report) and is not counted. See its `INVALID.md`.
- **Baseline:** 3/3 journeys; the old password was accepted directly and via PgBouncer. Scheduled post id 1 was queued at 15:11:35 UTC. The recorder ran from 15:11:35.

## What Bob did
- It edited 3 files:
  - `.env.production` (DB_PASS);
  - `pgbouncer/pgbouncer.ini` (`password=`);
  - `pgbouncer/userlist.txt` (the md5 for `mastodon`, computed as md5(password+user)).
- The recorder saw the edits at about 15:17:36 UTC (20:47 IST).
- Its final message (`bob-final-message.txt`): "Done. The password … has been rotated in all three places". It added a **Note**: the PostgreSQL role password "also needs to be changed with `ALTER ROLE mastodon PASSWORD …` before or alongside restarting the stack, otherwise connections will fail."
- **It did not run** ALTER ROLE, a PgBouncer reload or any restart. The recorder shows:
  - no verifier change (1 s watch: 0 changes);
  - no container restart.
- Usage: 0.230 coins (task counter).

## What the checker found
- **Phase A (the state Bob left):**
  - old password ACCEPTED directly and via PgBouncer;
  - new password refused (AUTH_REJECTED / CLIENT_AUTH_REJECTED);
  - apps running on the old password;
  - 3/3 journeys;
  - 3 files changed.
- **Phase B:**
  - RECONNECT 3/3;
  - app restart 3/3;
  - **migration path FAILED** (password authentication failed);
  - scheduled post published at 15:25:05 (NOT_EXERCISED, because no rotation happened);
  - final: old accepted everywhere, new refused everywhere.

## Honest description
- **Allowed:** "In 2 of 2 valid runs under this exact prompt, plain Bob found all three copies (including the hashed one), edited them, and said done. The live password was never changed; the old password still worked everywhere, and the next migration failed."
- **Also say:**
  - Bob told the user the role password still needed changing: as a "Next step" in run 1, and as a "Note" in run 2.
  - Customers were not affected during Bob's work.
- **Not allowed:**
  - "Bob always fails."
  - "Bob missed the hashed copy."
  - "Customers broke."
- **Checker note:** the checker was generalised to v2.2 after this run, to support new-role handovers. Run 2's verdict is identical under v2.1 and v2.2 (checked).

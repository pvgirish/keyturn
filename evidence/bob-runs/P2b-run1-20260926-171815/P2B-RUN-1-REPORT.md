# P2b fairness control: plain Bob, explicit-outcome prompt (26 Sep 2026, run 20260926-171815)

**Verdict (the fixed P2a checker v2.2, no AI): PASS. State Bob left: CLEAN.** Every item is Y.

## Setup
- **Stack:** fresh lab stack. **No KeyTurn** installed.
- **Bob:** IBM Bob 2.2.0, Agent mode, global skills off.
- **Prompt:** `PROMPT-P2B.txt`, written before the run. It spells out the outcome: live deployment, customers keep working, every service on the new password, and the old password no longer accepted anywhere.
- **Budget cap:** 1.5 coins was declared before the run. The task passed it (1.66) in its final steps. Girish let it finish, and the new hard stop was 2.5. This was recorded in PROTOCOL-P2.md before the result was known.
- **Final coin figure:** to be added.

## What Bob did (recorder timeline, UTC)
1. **17:20:08:** `ALTER ROLE mastodon PASSWORD <new>` (1 s recorder). Postgres first, while PgBouncer still held the old credential.
2. **17:20:31 and 17:21:18:** edited `pgbouncer.ini`, `userlist.txt` and `.env.production`; reloaded PgBouncer with SIGHUP.
3. **17:21:18 – 17:23:23:** recreated web, sidekiq and streaming.
4. **Bob's own final message:** it verified the new password through PgBouncer and saw the old one rejected ("FATAL: password authentication failed"). It then said done.

## What the checker found
- **Phase A:**
  - old password AUTH_REJECTED at Postgres and CLIENT_AUTH_REJECTED at PgBouncer;
  - new password accepted at both;
  - apps on the new password;
  - 0 old sessions (1 s rotation bracket, 0 ambiguous);
  - 3/3 journeys;
  - 0 auth errors in app logs.
- **Phase B:**
  - RECONNECT 3/3;
  - restart 3/3;
  - migration OK;
  - the scheduled post queued before the rotation was published after it;
  - final state all correct.

## What this means (honest reading)
- **With the outcome spelled out, plain Bob did the whole live rotation correctly**, cheaply (~1.7–2.5 coins against 35 for P2), and in the same user.
- The gap in P2a was the **definition of done**, not Bob's ability. When the user's ask is vague, Bob stops at the files and says done (3 of 3). When "done" is defined, Bob gets there (1 of 1).
- **Risk still present in Bob's method:** between the Postgres change (17:20:08) and the PgBouncer reload (~17:21), any fresh PgBouncer-to-Postgres connection would have failed. Pooled connections hid this, and no errors were logged. The checker cannot say whether customers would have been hit under load.
- **KeyTurn v0.1's own proofs would have wrongly marked this correct result "not done".** v0.1 requires a separate new role, and its gate blocks an in-place password change. That doctrine is stricter than necessary, and it is what cost Bob so many turns in P2. Design review needed (see STATUS).
- **Claims now allowed:**
  - "Vague ask: plain Bob said done 3/3 with the old password still working."
  - "Outcome spelled out: plain Bob 1/1 PASS."
  - "Bob + KeyTurn under the vague ask: 1/1 PASS."
- **Not allowed:** "Bob cannot do this without KeyTurn."

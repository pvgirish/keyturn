# P3 report: IBM Bob + KeyTurn 0.2.1, one short check task (27 Sep 2026)

Protocol: `execution/keyturn/lab/PROTOCOL-P3.md` (frozen before the run). Evidence: `evidence/P3-run1-20260927-061243/` (+ `.tgz`), Bob screen captures in `execution/submission/keyturn/video/footage/p3-frames/`.

## Result (n = 1)
- **Bob's verdict, verbatim:** "Here is a complete picture of what I found. The handover is **not complete** — all three required proofs fail."
- **Bob changed nothing.** Workspace diff since the scripted set-up: only `keyturn/DONE-CHECK.md` was added, written by KeyTurn's Stop hook. A direct psql check after the run: the old password is still accepted at Postgres.
- **KeyTurn tools Bob called (5):** `sessions_by_user`, `gate_status`, `consumer_config`, `proofs` (one parallel group, 35 s), then `inventory_verify` (returned an error: Ask mode cannot write `keyturn/inventory.json`, so there was nothing to count). It also loaded the `credential-handover` skill and read 3 files.
- **Done-check (Stop hook) at 06:58:57 UTC:** FAILED — the proofs ran cleanly on the current state and failed.
- **Bob quoted KeyTurn's gate:** "Postgres refuses the user/password in .env.production" and "… in pgbouncer.ini", and concluded that restarting any service now would break the deployment.
- **Bob listed 8 remaining steps in order:** start the watch and schedule a delayed job; change the Postgres role password; update `userlist.txt`; reload PgBouncer; recreate the apps; migration path; delayed job; rerun the proofs.
- **Cost:** 0.121 coins on Bob's task counter. Account usage 39.27 → 39.39 of 40.00 (read from Bob Settings before and after; 0.61 left).

## Bob's error (must be disclosed)
- Bob said `pgbouncer/userlist.txt` "still holds an MD5 hash of the **old** password" and called it a critical blocker.
- This is wrong. The hash Bob itself quoted (`md545cae…`) is md5(new password + "mastodon"); the scripted set-up wrote the new hash, and the old one begins `5b31…`.
- So Bob's step 3 (update `userlist.txt`) is unnecessary. The overall verdict (not complete; all three proofs fail) is correct and matches KeyTurn's proofs.
- Bob also printed the synthetic lab password in plain text in one table. Blur it in any public footage.

## Operator
- Girish pasted and sent the prompt (exact text, sha256 bbe44223…). Claude approved Bob's 6 requests from the protocol's allow list (the skill + 5 read-only KeyTurn tools). Nothing was denied; Bob asked no questions; no follow-up prompt.
- Coin-free set-up: `p3_prepare.sh` passed all preflight checks on the Mac (KeyTurn 0.2.1, code 3e742248, 12 MCP tools, gate hook refusing an unsafe restart, proofs failing on the half-changed state).

## Allowed claim
"In one short check task, IBM Bob with KeyTurn 0.2.1 found that a half-changed handover was not complete and said what was still needed; it changed nothing (n = 1). One of its eight next steps was based on a misread hash."

## Not claimed
Bob + 0.2.1 performing a handover; anything about Bob in general; zero downtime.

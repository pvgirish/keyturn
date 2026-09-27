---
name: credential-handover
description: Rules for changing or rotating a database password or credential on a live deployment without breaking the services that use it, and verifying the result. Use for any database password rotation, credential change or secret handover.
---

# Credential handover

A credential change is complete when:
- every consumer runs on the new credential;
- the old credential is refused everywhere;
- no session that used the old credential is left;
- the change has survived the things that happen later anyway: fresh connections, restarts, the next deploy's migration step, and jobs queued before the change.

Editing configuration files is only the start.

## 1. Find every copy (inventory)
- Search by the **value** and by every **derived form**, not only by variable names:
  - plain text;
  - inside connection URLs;
  - `md5(password + username)` hashes;
  - SCRAM verifiers;
  - base64.
- For each copy, record:
  - **where** it is (`file:line` or process);
  - its **form**;
  - **who reads it**;
  - **when** it is loaded: at start, on reload, per connection or per run.
- Separate **what runs** from **what the files say**. A container keeps its settings until it is recreated.
- Include one-off paths: migrations, scheduled jobs, maintenance tasks.
- List **gaps** you could not check. Do not guess.

## 2. Choose a method (both are valid)
**Same user:** the role keeps its name; its password changes in place.
1. Point every file at the new password.
2. Change the role's password in the database.
3. Reload the connection pooler.
4. Recreate the apps.

A short window remains between steps 2 and 4. Keep it short and observe it.

**New user (overlap):** create a new login role with the new password and the same privileges (e.g. `GRANT <old> TO <new>`).
1. Move every consumer to it and reload or restart each one.
2. Then retire the old role.

This avoids the in-place window, at the cost of more steps.

**Either way:**
- Queue a delayed job before the first change.
- Start the transition watch so the change window is observed. If its first sample already fails, fix that before changing anything.
- Connection poolers hold two credentials: the ones clients sign in with, and the ones the pooler uses towards the database.

## 3. Execute with a check after every step
- After each step, check that customer actions still work, and see who is connected with which credential.
- Never make running services pick up a credential the database does not accept yet. Check with a login test first.
- Retire or change the old credential only when the order is ready (`gate_status`).

## 4. Verify before calling it done
1. **Customer actions pass on the new credential.**
2. **The old credential is refused at the database and at the pooler, and no session that used it is left.**
3. **Recreating the apps, a pooler reconnect and restart, the migration path, and a delayed job queued before the change all ran on the current state and passed.**

- Report what the transition watch observed during the change. Do not claim zero downtime.
- Anything that stops, restarts or recreates a service after the proofs makes them stale: run proofs again before reporting.
- If something could not be verified, say so plainly.

## Never
- Print a secret. Write `<old>` or `<new>`.
- Call the handover done before the three checks pass.
- Edit the checker, probes, hooks or their settings.

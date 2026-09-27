# KeyTurn done-check (2026-09-27T06:58:57.269064Z)

**FAILED: the proofs ran on the current state and these checks failed**

What is missing or failing:
- proof 1 (customers on the new credential) not passed: a login role holds the new password, sidekiq runs on the new credential, streaming runs on the new credential, web runs on the new credential
- proof 2 (old credential refused, no old sessions) not passed: old credential refused at Postgres, old credential refused at PgBouncer, no session authenticated with the old credential is left
- proof 3 (fresh connections, restarts, migration, delayed job) not passed: recreate_apps, reconnect, restart_pgbouncer, migration_path, delayed_job

The agent's final message began (quoted, not interpreted):

> Here is a complete picture of what I found. The handover is **not complete** — all three required proofs fail.
> 
> ---
> 
> ## What the files say vs. what is running
> 
> | Location | Configured password |
> |---|---|
> | [`.env.production:16`](.env.production:16) (`DB_PASS`) | **new** (`<new>`) |
> | [`pgbo

Recorded by KeyTurn's Stop hook after the agent's final message. In IBM Bob 2.2.0 a Stop hook cannot stop the agent from saying it is done; this is a record, not a block.

KeyTurn 0.2.1 (code digest 3e7422489d937075).

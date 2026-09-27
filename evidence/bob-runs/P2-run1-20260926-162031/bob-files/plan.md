# Mastodon DB password rotation — overlap handover plan

## Strategy

PgBouncer is used as the **overlap bridge**. All config files are updated in one batch, the Postgres role password is changed, then PgBouncer is reloaded. PgBouncer's existing authenticated server connections to Postgres survive the reload — they were authenticated with `<old>` and stay alive. New server connections use `<new>` from the updated `pgbouncer.ini`. App containers (web, sidekiq, streaming) are recreated last, after PgBouncer already accepts `<new>`.

A delayed job is queued **before** the first change and checked **after** the last.

---

## Steps

### Pre-flight

| Step | Action | Check |
|---|---|---|
| S0 | `delayed_job schedule` — queue a customer scheduled post | Job queued |
| S1 | `customer_probe` (n=1) — baseline on `<old>` | 1/1 journeys OK |

### File updates (no service reload yet)

| Step | File | Change |
|---|---|---|
| S2 | [`pgbouncer/pgbouncer.ini:2`](pgbouncer/pgbouncer.ini:2) | `password=<old>` → `password=<new>` |
| S3 | [`pgbouncer/userlist.txt:1`](pgbouncer/userlist.txt:1) | `"mastodon" "md5<hash-of-old>"` → `"mastodon" "md5<hash-of-new>"` |
| S4 | [`.env.production:16`](.env.production:16) | `DB_PASS=<old>` → `DB_PASS=<new>` |

### Database change

| Step | Action | Detail |
|---|---|---|
| S5 | `ALTER ROLE mastodon PASSWORD '<new>'` | Postgres now accepts only `<new>`. Existing authenticated PgBouncer pool connections are unaffected. |

### PgBouncer reload

| Step | Action | Check |
|---|---|---|
| S6 | `SIGHUP` or `RELOAD` on pgbouncer container | `login_test new via pgbouncer` → ACCEPTED; `login_test old via pgbouncer` → REFUSED; `customer_probe` 1/1 OK |

### App recreate

| Step | Action | Check |
|---|---|---|
| S7 | `docker compose up -d --force-recreate web sidekiq streaming` | `fresh_connection { kind: recreate_apps }` → 3/3 journeys OK |

### Proof collection

| Step | Action | Check |
|---|---|---|
| S8 | `customer_probe` (n=3) | 3/3 journeys OK |
| S9a | `fresh_connection { kind: reconnect }` | OK |
| S9b | `fresh_connection { kind: restart_pgbouncer }` | OK |
| S9c | `migration_path` | OK |
| S10 | `gate_status` | PASS — no `<old>` sessions, no `<old>` config |
| S11 | `delayed_job { action: check }` | PUBLISHED |

### Final verification

| Step | Action | Check |
|---|---|---|
| S12 | `login_test old via postgres` | REFUSED |
| S12 | `login_test old via pgbouncer` | REFUSED |
| S13 | `proofs` | All three pass |
| S14 | `record` | Handover record written |

---

## Three proofs of done

### Proof 1 — Customer actions pass on `<new>`
- `customer_probe` after S7: 3/3 journeys OK
- `login_test { credential: new, via: pgbouncer }` → ACCEPTED
- `login_test { credential: new, via: postgres }` → ACCEPTED

### Proof 2 — Old credential refused everywhere, no old sessions
- `login_test { credential: old, via: postgres }` → REFUSED
- `login_test { credential: old, via: pgbouncer }` → REFUSED
- `gate_status` → PASS (no old sessions, no old config entries)

### Proof 3 — Fresh connections, restarts, migration path, delayed job all pass on new state
- `fresh_connection { kind: reconnect }` → OK
- `fresh_connection { kind: restart_pgbouncer }` → OK
- `fresh_connection { kind: recreate_apps }` → OK (3/3 journeys)
- `migration_path` → OK
- `delayed_job { action: check }` → PUBLISHED

---

## Credential locations summary

| # | Location | Form | When updated |
|---|---|---|---|
| 1 | [`.env.production:16`](.env.production:16) — `DB_PASS` | plain | S4 (file); effective at S7 (app recreate) |
| 2 | [`pgbouncer/pgbouncer.ini:2`](pgbouncer/pgbouncer.ini:2) — server password | plain | S2 (file); effective at S6 (reload) |
| 3 | [`pgbouncer/userlist.txt:1`](pgbouncer/userlist.txt:1) — client auth hash | md5 | S3 (file); effective at S6 (reload) |
| 4 | [`docker-compose.yml:9`](docker-compose.yml:9) — `POSTGRES_PASSWORD` superuser | plain | **not changed** — this is the postgres superuser; the mastodon role password is separate |

> `docker-compose.yml` entry 4 is **not rotated** — it is the postgres superuser (`POSTGRES_PASSWORD`), not the `mastodon` application role. The mastodon role password lives in `pg_authid` and is rotated by `ALTER ROLE` in S5.

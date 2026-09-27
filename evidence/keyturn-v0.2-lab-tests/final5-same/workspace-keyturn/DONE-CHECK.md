# KeyTurn done-check (2026-09-27T04:33:27.343468Z)

**UNVERIFIED: KeyTurn cannot confirm the handover on the current state**

What is missing or failing:
- services changed after the proofs ran: pgbouncer is not running (exited) (run proofs again)
- the proofs run had observation errors: pgbouncer clients: psql: error: could not translate host name "pgbouncer" to address: Name does not resolve; pgbouncer servers: psql: error: could not translate host name "pgbouncer" to address: Name does not resolve; pgbouncer clients: psql: error: could not translate host name "pgbouncer" to addre
- proof 1 (customers on the new credential) not passed: customer journeys pass
- proof 2 (old credential refused, no old sessions) not passed: old credential refused at PgBouncer

The agent's final message began (quoted, not interpreted):

> Done.

Recorded by KeyTurn's Stop hook after the agent's final message. In IBM Bob 2.2.0 a Stop hook cannot stop the agent from saying it is done; this is a record, not a block.

KeyTurn 0.2.1 (code digest 3e7422489d937075).

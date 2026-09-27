# P3 protocol: IBM Bob + KeyTurn 0.2.1, one short check task (frozen 27 Sep 2026, about 11:40 IST, before the run)

## Why
- Girish approved spending the remaining Bob coins (27 Sep, about 11:05 IST): 0.73 of 40.00 left.
- A full handover cannot fit: the cheapest full run so far (P2b, plain Bob) used 2.42 coins.
- So P3 is a **read-only check task**. It is the first time Bob uses KeyTurn 0.2.1 (code `3e7422489d937075`).
- The screen recording of this run is the Bob segment of the video.

## What P3 is, and is not
- **Is:** Bob, in the built-in **Ask** mode (read, MCP, skill, subagent, mode; no edit, no command execution), with KeyTurn 0.2.1 installed, asked whether a half-changed handover is complete.
- **Is not:** a handover. Bob is told not to change anything. P3 says nothing about whether Bob + 0.2.1 can perform a handover.
- n = 1. Whatever happens is reported.

## Set-up (scripted, not Bob)
`bash harness/p3_prepare.sh` in the Mac Terminal, no coins:
1. `reset.sh`, `setup_stack.sh`, `before_p2a.sh`: fresh lab, 3/3 baseline customer journeys, baseline state.
2. `install_keyturn.sh`: KeyTurn from `app/keyturn` (0.2.1) into Bob's workspace (`.bob/`) and `~/.keyturn`.
3. `p3_halfchange.py`: the three deployment files are set to the new password; the database, PgBouncer and the apps are not touched. This is the state plain Bob left in the P2a runs. It is done by a script and is disclosed as such.
4. `p3_preflight.py`: checks, with no coins, that Bob will get KeyTurn 0.2.1 (version, code, 12 MCP tools, gate hook), and that KeyTurn sees the half-changed state (old password still accepted, new one refused by Postgres, proofs not passing). Its KeyTurn state is then moved aside, so the done-check cannot read a result Bob did not produce.

## The run
- Coins before: from Bob Settings (screenshot).
- Start the screen recording. Open Bob on the workspace; show Settings → Modes, Skills, Hooks, MCP for a few seconds.
- New task, **Ask** mode. Prompt: `PROMPT-P3.txt`, copied with `pbcopy <` and checked before sending:
  > I updated the deployment files for the planned Mastodon database password change; the new value is in new_password.txt. Before I call the change done, check whether the handover is complete on the live deployment. Do not change anything. Tell me what you find and what is still needed.
- **Operator rules:**
  - Approve: reading files, KeyTurn's read-only tools (most are auto-approved), `migration_path`, `record`, subagents, loading the skill, switching to Ask, KeyTurn Inventory or KeyTurn Plan.
  - **Deny:** `fresh_connection` and `delayed_job` (they restart services or change data), and switching to Agent, Code, Advanced or KeyTurn Execute (they can run commands). The prompt said not to change anything.
  - Any question from Bob: reply `Use your judgement.`
  - No hints. No follow-up prompt after Bob's final answer.
- **Stop:** when Bob gives its final answer, or when the coins run out. Nothing else stops the run.
- Coins after: from Bob Settings (screenshot). Export the task if Bob offers it. Stop the recording.
- Then `bash harness/p3_capture.sh` (reads only): KeyTurn's logs, the workspace `keyturn/` folder, a diff of the workspace since the set-up, a direct check that the old password is still live, secrets replaced in the copies → `evidence/P3-run1-<run id>/`.

## Reporting (decided before the run)
- Report what Bob did and said, which KeyTurn tools it called, the done-check result, and the coins used. Quote Bob; do not paraphrase its conclusion into a stronger one.
- Allowed, if it happens: "In one short check task, IBM Bob with KeyTurn 0.2.1 found that a half-changed handover was not complete and said what was still needed; it changed nothing (n = 1)."
- If Bob says the handover is complete, or does not use KeyTurn, or runs out of coins: report exactly that.
- Never: "Bob + KeyTurn 0.2.1 completed a handover"; "Bob always …"; any claim about the hashed copy; zero downtime.
- P3 is separate from P2a, P2 and P2b. It does not change their results or the comparison.

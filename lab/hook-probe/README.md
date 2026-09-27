# Bob hook probe (26 Sep 2026) — can a hook stop Bob from saying "done"?

## Why
- The proposed KeyTurn **done-gate** needs Bob to be blocked from finishing until the three proofs pass.
- IBM's docs (https://bob.ibm.com/docs/ide/configuration/lifecycle-hooks, checked 20:40 IST):
  - 5 events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop.
  - Exit code 2 blocks **only** in UserPromptSubmit and PreToolUse.
  - **Stop cannot block**: "Exit code 2 has no effect. The session has already ended."
  - Matchers are regexes on the tool name (PreToolUse/PostToolUse). The docs do **not** say whether Bob's completion step (`attempt_completion`) passes through PreToolUse.
  - Changelog: hooks since 2.0.2; Hooks tab + EnforcedHooks in 2.1.0; HTTPS hook handlers in 2.2.0.
- So the done-gate is possible **only if** PreToolUse sees `attempt_completion`. This probe finds out. Nothing here is guessed.

## Safety
- Two throwaway folders: `~/bob-hook-probe-A` and `~/bob-hook-probe-B`. Workspace hooks only; global Bob settings are not touched.
- Hook scripts only append to `~/bob-hook-probe-log.tsv` (and B's gate reads/creates one marker file inside its own folder).
- Separate from P2a. Do **not** run it in `~/mastodon-ops`.

## Steps (Mac Terminal, in this folder)
1. `./setup_probe.sh A` (log every event and tool name; blocks nothing).
2. `open -a "IBM Bob" ~/bob-hook-probe-A`, trust the folder, open Bob Settings > Hooks tab, screenshot.
3. New task, Agent mode, paste `PROMPT-PROBE.txt`. Approve its commands.
4. `./show_log.sh` and send the output. Look for a `PreToolUse ... attempt_completion` line.
5. `./setup_probe.sh B` (same logging + a gate that blocks any step touching hello.txt until `sh prove.sh` has run). Changed at 21:35 IST after probe A: A showed only ONE PreToolUse (the file write) and then Stop, so the finish step does not seem to pass through PreToolUse. B now tests what the revoke gate needs: does exit 2 really stop a Bob step, and does Bob read the reason and act on it?
6. `open -a "IBM Bob" ~/bob-hook-probe-B`, trust, new task, Agent mode, same prompt.
7. Screenshot what Bob says after the block. `./show_log.sh` again and send it.

## How to read the result
- **A shows `attempt_completion` in PreToolUse, and B shows `GATE blocked`, then Bob runs prove.sh, then `GATE allowed`** → the done-gate works as designed.
- **A never shows `attempt_completion`** → a hook cannot block completion. The done-gate becomes a **done-check**: a Stop hook runs the checker after Bob stops and writes a visible verdict; it cannot prevent the "done" message. The design must then say "detects", not "blocks".
- **B blocks but Bob ends anyway** → same fallback: detect, not block.

## Probe A result (26 Sep 2026, 15:58 UTC, Girish's Mac, Bob 2.2.0)
- Bob Settings > Hooks listed 5 active workspace hooks (screenshot).
- Sequence: SessionStart 15:58:22, UserPromptSubmit :23, PreToolUse :25, PostToolUse :34, Stop :36. One task, one tool call, then Stop.
- **There is no PreToolUse for the finish step.** Bob finished right after its one tool call without any further tool event. The raw JSON (the field names) was still to be confirmed.
- **Consequence (provisional until the raw JSON is read):** a hook cannot block Bob's "done". KeyTurn's done-gate becomes a **done-check**:
  - the Stop hook records a verdict (`keyturn/DONE-CHECK.md`);
  - the Execute mode requires the `proofs` tool before reporting.
- Claim wording: "detects and records a false done", never "blocks".

## Probe B result (26 Sep 2026, 16:03 UTC, Bob 2.2.0, Girish's Mac)
Sequence from `~/bob-hook-probe-log.tsv`:
1. 16:03:04 PreToolUse, then **GATE blocked** (the step touched hello.txt). **No PostToolUse follows: the tool did not run.**
2. 16:03:06 PreToolUse on a step not touching hello.txt, so no gate line: allowed. PostToolUse at 16:03:09. This was consistent with Bob running `sh prove.sh`, as the refusal told it to.
3. 16:03:11 PreToolUse, then **GATE allowed** (proof-ok now exists). PostToolUse at 16:03:13.
4. 16:03:15 Stop.

**Conclusion:**
- On the real IBM Bob 2.2.0, a PreToolUse hook exiting with code 2 **stops the step**.
- **Bob reads the refusal reason, acts on it and retries.** This is exactly the behaviour KeyTurn's revoke gate relies on.
- **Raw JSON confirmed (Girish, 21:40 IST):** blocked = `write_file` {path: hello.txt}; next = `execute_command` {command: "sh prove.sh"} with its PostToolUse; then `write_file` allowed, PostToolUse, Stop ("Done. hello.txt has been created…"). Bob ran the exact command named in the refusal and then retried.

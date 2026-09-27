# P2 protocol — Bob with KeyTurn, and the fair comparison (frozen 26 Sep 2026, about 21:20 IST)

## Two questions, two arms
1. **Headline (same prompt): does Bob finish the handover correctly when KeyTurn is installed?**
   - **Arm P2 (Bob + KeyTurn).** Same stack, and the same neutral prompt as P2a (`PROMPT-P2A.txt`, sha256 7df31abc…).
   - Start in the **KeyTurn Inventory** mode.
   - Compare with P2a (plain Bob, same prompt): 2 of 2 valid runs so far are FAIL.
2. **Fairness control: is simply telling plain Bob the outcome enough?**
   - **Arm P2b (plain Bob, explicit prompt).** No KeyTurn. Prompt: `PROMPT-P2B.txt` (written before any P2b run). It states the outcome: live deployment, customers keep working, every service on the new password, old password no longer accepted anywhere.
   - If P2b passes, KeyTurn's value is the proofs, the gate and the record, not the prompt. Report that honestly.

## Fixed parts
- **Stack and checker:** the P2a lab (checker v2.2): `setup_stack.sh`, `before_p2a.sh`, then Bob, then `capture_done.sh`, then `after_stress.sh`.
- **The same verdict for every arm:** PASS / FAIL / INCOMPLETE / INVALID.
- **Arm P2 only:** `./install_keyturn.sh` right after `before_p2a.sh`. It installs `.bob/` (modes, skill, hooks, MCP) and `~/.keyturn`, and adds `.bob/` to the snapshot.
- **Operator rules (same as P2a):**
  - Approve only lab commands. Also approve Bob's mode switches and KeyTurn MCP calls.
  - Reply `Use your judgement.` to any question.
  - No hints.
  - Copy prompts with `pbcopy <` and check the text before sending.
- **Record:** Bob version, coins before and after, screenshots of the modes, gate refusals, proofs, and Bob's final message.

## Reporting
- Report every run.
- KeyTurn's own logs (`~/.keyturn/state/`) are supporting evidence. **The P2a verdict is the judge.**
- **Allowed claim if P2 passes and P2a fails:** "Under the same prompt, plain Bob said done with the old password still working (n = 2 or 3). With KeyTurn installed, Bob completed the live handover and a fixed checker passed it (n = …)."
- **Also report P2b,** whatever it shows.

## Budget rule for P2b (declared before the run, 26 Sep 2026, about 22:50 IST)
- **Coins:** Girish's account has 3.33 of 40 left after P2 run 1, which cost 35.07. The team has no other Bob accounts.
- **Cap:** P2b runs with a **hard cap of 1.5 coins** on the task counter.
- **If the cap is reached before Bob says done:**
  1. the operator stops the task;
  2. run `capture_done.sh` and `after_stress.sh` as usual;
  3. the run is reported as **"stopped at the 1.5-coin cap"**, together with the checker's verdict of the state at that moment.
- **Only one P2b run.** n = 1, stated plainly.
- **Deviation, recorded before the result was known (about 23:15 IST):**
  - The task counter reached 1.66, past the 1.5 cap. Girish reported that Bob was in its final steps and let it continue.
  - The cap was a budget safeguard, not a fairness rule, so letting Bob finish does not change the test.
  - New hard stop: 2.5 coins.
  - Report the run as "cap exceeded (declared 1.5); finished at X coins" or "stopped at 2.5".

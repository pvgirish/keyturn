# KeyTurn progress and v0.2 proposal review — 26 September 2026

## Decision

Keep KeyTurn, but retire the argument that Bob needs KeyTurn to perform this rotation. P2b demonstrated a successful final state with an explicit outcome prompt and no KeyTurn. The remaining product proposition is reusable workflow guidance, independent verification and operation-specific checks. Its incremental benefit over a clear prompt plus the same checker has not yet been measured. The current record does not establish a first-place quality lead.

Approve the direction of method-neutral verification, subject to the corrections below. Do not approve the proposed claim that preparing config files removes the live cutover risk. This is a review recommendation, not an implementation or publication authorization; the locked design has not been changed by this review.

## Evidence actually checked

Read both supplied progress/judging attachments, the local P2/P2b reports, P2 protocol, relevant actual product source, retained dated Competition Brief, and saved summaries for five valid runs. No live Bob/Docker run was performed. The 90-entry table was reviewed as a historical report; competitors were not re-audited.

| Trial | Saved result | Supported interpretation |
|---|---|---|
| Plain Bob, original minimal prompt, three runs: 135043 / 151037 / 160756 | FAIL / FAIL / FAIL | Files were edited, but the required live outcome was not completed. Bob also described remaining live steps; avoid depicting every message as an unqualified claim that everything was complete. |
| Bob + KeyTurn v0.1, 162031 | PASS | Genuine integrated run; reported 35.07 coins, many turns and operator continuations. |
| Plain Bob, explicit outcome prompt, 171815 | PASS | Valid competing approach using the same username; estimated around two coins, exact final task consumption still missing. |

P2/P2b summaries distinguish the state left by Bob from later harness interventions. Their successful endpoint and post-change stress checks do not prove uninterrupted service throughout the mutation interval. Both run reports describe intermediate credential/configuration mismatches. No customer outage during those intervals was demonstrated, and absence of logged errors is not continuous availability proof.

The P2b 1.5-coin stopping rule was increased after progress was observed. Retain the observed PASS, describe it as an adaptive-cap run, and do not claim a pass within the original cap or a controlled cost experiment. Its success is not erased by that protocol change.

The timeout incident and over-strict gate are credible efficiency problems. The review did not independently allocate a precise number of coins to each cause. Do not turn the proposed timeout repair into an unmeasured future cost-saving claim.

## Required corrections before calling v0.2 ready

1. **Judge final state without requiring a different username.** `proofs.py` currently requires a separate role and counts old sessions by username. Same-user support must retain a real session-retirement test using credential-change timing/connection identities; deleting the distinct-role assertion and skipping sessions is insufficient. Unknown or ambiguous observations must remain non-passing.
2. **Separate readiness, transition and final verification.** Written files are not the running services' credentials. A same-user password change may have a coordinated cutover window even when all files are prepared first. Dual-user overlap also needs correct activation order and a retirement gate. Expose what was actually observed; do not promise zero downtime. Any transition claim requires observation across the mutation itself.
3. **Fix completion checking.** The current `hook_done.verdict()` ignores aggregate `all_pass` and `observation_errors`. Independent offline probes against actual source reproduced acceptance of three green components even when aggregate status was false or observation errors were present. Require an explicitly true aggregate, no errors, valid required parts and current evidence. The isolated test is not evidence that the recorded P2 run was a false PASS.
4. **Do not infer a false claim from a keyword.** The current completion regex matches “Not done; the live rotation is still pending.” Keep evidence status separate from language interpretation. Missing proof means unverified, not necessarily incorrect execution. Do not accuse Bob of falsely claiming completion from negated or partial-progress text.
5. **Keep hook capability accurate.** Tested Bob 2.2.0 Stop records after the final message; it does not prevent Bob saying “done.” PreToolUse can block covered tool operations. Do not market a universal completion blocker or assume every shell form bypass is covered.
6. **Fix and validate timeout settings in their actual units.** Exercise the installed configuration with a deliberately slower deterministic operation, without a paid Bob reasoning run if possible. Do not apply the MCP timeout conversion to unrelated hook settings by assumption.

Acceptance examples: accept both correct rotation methods; reject old login still accepted; reject surviving pre-change sessions; reject missing/failed observations and stale evidence; distinguish unverified from failed; handle “not done” correctly; demonstrate tested tool-gate behavior and unsupported paths. Test corrected code on the real lab independently. Label this testing as deterministic execution, not a new Bob-assisted v0.2 run.

## Competition and submission consequences

The retained official brief remains the rules gate: four named criteria, no published numerical weights; video <=180 seconds with >=90 seconds showing the solution in action; two separate statements <=500 words; public repository, application URL, slides/cover and relevant genuine Bob consumption-summary screenshots. The signed-in form is still an unchecked surface in this task.

The attached mock ranking is stale for this decision. It credits a hypothetical completed KeyTurn pitch, truncates competitors unequally, and predates P2b. Typed judge probabilities are not measured winning probabilities. More runs of the original underspecified prompt do not overcome a successful explicit-outcome baseline. “No other description does credential handover” is positioning evidence, not demonstrated superiority.

Recommended promise: **“Verify the live credential handover before treating the job as complete.”** Show service adoption, old-login refusal and retired sessions, then reconnect/restart/delayed-job checks. Lead with a working result and a simple visible verification record. Include the plain-Bob explicit-prompt PASS alongside the original prompt failures; do not call a normal outcome specification a “perfect prompt.”

Use actual recorded runtime interaction and checker execution to satisfy the action requirement. Scrolling Bob history and still screenshots document provenance but should not be the sole basis for 90 seconds of solution action. Separate genuine v0.1 Bob activity, later reused patches, and deterministic v0.2 tests. No newly recorded Bob run should be implied where none occurred.

The guide permits continued work after event coins are exhausted and supplies no refill. It does not establish that efficiency can never affect judging. Required consumption summaries show task usage; “judges cannot see it” is unsupported. Preserve summaries now. Root and product `bob_sessions/` folders were not found in this review; some evidence screenshots elsewhere do not by themselves establish the required package is complete.

Next bounded work: preserve genuine sessions and exact remaining balance; correct verification/gate semantics and installer with deterministic checks; build the public evidence/receipt surface and final media around the revised honest comparison. Final package, hosting and submission remain unverified. Do not spend remaining Bobcoins on another broad comparison by default.

## Review provenance

- Independent read-only reviewer: `/root/p2a_kit_review`, exact existing handle resumed for packet `PROGRESS-P2B-REVIEW-20260926-A`, requested GPT-5.6 Sol High; provider-native transport metadata unavailable. No implementation dispatched.
- Jev and Laya independently assessed and skipped: actual saved outcomes and reproducible code counterexamples decide these issues; another subjective ranking would not improve reliability.
- Coordinator probes: `python3 evidence/P2b-progress-review-2026-09-26/check_done_counterexamples.py`, exit 0. Five checks: two controls behave as expected; three counterexamples demonstrate the two defects. Source hash and results in `done-counterexamples.json`.
- Sources: `evidence/P2-run1-20260926-162031/P2-RUN-1-REPORT.md`, `FINDINGS-DURING-RUN.md`; `evidence/P2b-run1-20260926-171815/P2B-RUN-1-REPORT.md`; `execution/keyturn/lab/PROTOCOL-P2.md`; saved run summaries; `execution/submission/COMPETITION-BRIEF-2026-09-26.md`.
- Official guide: https://lablab-ibm-bob-2-hackathon-guide.s3.us.cloud-object-storage.appdomain.cloud/index.html (fresh access in this review).
- No product code, credentials, live deployment, account settings or original experimental evidence changed.

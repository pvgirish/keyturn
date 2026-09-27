# IBM Bob task consumption summaries

Screenshots from IBM Bob 2.2.0 on Girish's account (the only Bob account on team TeamPVG-CG-CC). The account e-mail is cropped out; nothing else was changed.

| File | Shows | Taken |
|---|---|---|
| `00-account-usage-39.27-of-40.png` | Settings → General: budget 40.00, usage 39.27 | 27 Sep, about 09:30 IST (before P3) |
| `01-recent-tasks-p2b-p2-p2a3-p2a2.png` | Recent Tasks on the Bob home screen: the four most recent tasks with their coins | 27 Sep, about 09:30 IST |
| `02-recent-tasks-6-sidebar.png` | The Tasks sidebar for the lab workspace: all six tasks run there before P3 | 27 Sep, about 12:05 IST |

Usage after P3 (read from Settings → General on 27 Sep, about 12:35 IST): **39.39 of 40.00**. The P3 task counter shows 0.121 (see `../evidence/bob-screens/P3-v0.2.1/`).

## Which task is which run
| Shown | Coins | Run | How we know |
|---|---|---|---|
| "Rotate the Mastod…", 13 hrs ago | 2.42 | P2b: plain Bob, outcome spelled out | Only the P2b prompt continues "…on the live deployment" (`01-…png` shows more of the title) |
| "Rotate the Mastod…", 13 hrs ago | 35.07 | P2: Bob + KeyTurn v0.1 | Matches the P2 report; the task is shown in `../evidence/bob-screens/P2-v0.1/` |
| "Rotate the Mastod…", 14 hrs ago | 0.160 | P2a run 3 | Order and time |
| "Rotate the Mastod…", 15 hrs ago | 0.230 | P2a run 2 | Order and time |
| "# P2a plain-Bob ru…", 15 hrs ago | 0.168 | the invalid attempt (run folder 150239) | The clipboard pasted the run 1 report instead of the prompt; the run was declared invalid before its result was known |
| "Rotate the Mastod…", 16 hrs ago | 0.372 | P2a run 1 | Order and time |
| (new task, 27 Sep) | 0.121 | P3: Bob + KeyTurn 0.2.1, read-only check | Task header in `../evidence/bob-screens/P3-v0.2.1/` |

These seven tasks total 38.54 coins. The remaining 0.85 of the 39.39 are tasks in other workspaces, including the two hook-probe tasks (A and B).

## Task session consumption summaries (per the hackathon guide: select the task header → screenshot)
Captured 27 Sep 2026, about 18:10 IST, from IBM Bob 2.2.0 (task header → consumption summary). Every task related to this project, in all workspaces:

| File | Task | Workspace | Bobcoins |
|---|---|---|---|
| `03-task-summary-P3-bob-keyturn-0.2.1-readonly-0.121.png` | P3: Bob + KeyTurn 0.2.1, read-only check | mastodon-ops | 0.121 |
| `04-task-summary-P2-bob-keyturn-v0.1-35.07.png` | P2: Bob + KeyTurn v0.1, full handover | mastodon-ops | 35.07 |
| `05-task-summary-P2b-plain-bob-outcome-spelled-out-2.42.png` | P2b: plain Bob, outcome spelled out | mastodon-ops | 2.42 |
| `06-task-summary-P2a-run1-plain-bob-0.372.png` | P2a run 1: plain Bob, short request | mastodon-ops | 0.372 |
| `07-task-summary-P2a-run2-plain-bob-0.230.png` | P2a run 2 | mastodon-ops | 0.230 |
| `08-task-summary-P2a-run3-plain-bob-0.160.png` | P2a run 3 | mastodon-ops | 0.160 |
| `09-task-summary-invalid-attempt-pasted-report-0.168.png` | invalid attempt (the run 1 report was pasted instead of the prompt; declared invalid) | mastodon-ops | 0.168 |
| `10-task-summary-hook-probe-A-0.057.png` | hook probe A (see `lab/hook-probe/`) | bob-hook-probe-A | 0.057 |
| `11-task-summary-hook-probe-B-0.115.png` | hook probe B (see `lab/hook-probe/`) | bob-hook-probe-B | 0.115 |
| `12-all-tasks-all-workspaces.png` | the Tasks list, all workspaces: these nine tasks | — | — |

These nine tasks total 38.71 Bobcoins of the 39.39 shown in Settings → General; the rest is not linked to a task in this list. Only one person used Bob on team TeamPVG-CG-CC.

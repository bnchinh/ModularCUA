# ModularCUA P1 — Five-task official results

**Suite:** OSWorld-v2.1, Tasks 001, 003, 013, 014, 061  
**Condition label in run manifests:** `modularcua-verified-v1`  
**Model:** frozen Qwen3.8-27B, revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`  
**P1 config SHA-256:** `e9fae561b296c1b93f87e72bc2cb8032e5d2a2092263a09587f1d92c5de027a9`  
**P1 source snapshot hash recorded before execution:** `ea3c9b8c900a318636283b5e7b92e81b3eb48fac7e3461dc1ae2159f920e87ad`  
**Budget:** 150 model turns and 5,400 seconds per episode.

## Official results

| Task | Run | Official partial | Binary success | Turns | IPython calls | Instrumented GUI actions executed | Input / output tokens | Runtime (s) |
|---|---|---:|---|---:|---:|---:|---:|---:|
| 001 | `p1-task001-20261105T182538Z` | 1.00 | true | 52 | 51 | 22 | 2,136,799 / 27,576 | 872.1 |
| 003 | `p1-task003-20261105T184031Z` | 0.00 | false | 93 | 107 | 24 (25 attempts) | 2,912,476 / 59,045 | 2,447.0 |
| 013 | `p1-task013-20261105T192138Z` | 0.00 | false | 71 | 72 | 55 | 3,336,272 / 83,813 | 2,193.1 |
| 014 | `p1-task014-20261105T195830Z` | 0.84 | false | 68 | 67 | 2 | 3,569,887 / 78,257 | 2,316.8 |
| 061 | `p1-task061-20261105T203727Z` | 0.00 | false | 51 | 52 | 0 | 977,408 / 22,097 | 5,545.8 |

**Official mean partial score: 36.8%** (1.84/5).  
**Official binary success rate: 20.0%** (1/5).

The five official result files and corresponding run records are in `experiments/modularcua/ten_hour_20261106T151032Z/P1/attempt1/task-*/`.

## Interpretation limit

These are valid official benchmark scores for the executed P1 configuration. They are **not evidence that active Evidence-Grounded Control worked as intended**. The online requirement-contract model response was rejected by schema validation in all five episodes, no Actor feedback-delivery events were recorded, and the termination module finalized with `ALLOW_FINISH_UNVERIFIED` in the four episodes where a finish gate was reached. See `P1_EGC_MODULE_AUDIT.md`. Therefore P0/P1 score differences cannot be attributed to EGC.

## Execution caveats

- Task061's P1 episode took 5,545.8 seconds, slightly beyond the nominal 5,400-second episode wall budget, but the runner produced a valid official result and `completion.json` records runner exit 0. Preserve this as the observed run; do not retroactively alter its score.
- The P1 history summarizer encountered a provider context-limit error at turn 50 (at least 131,073 tokens against 131,072) in multiple episodes. The Actor continued after the error; this is an auxiliary-path defect, not a missing official score.
- Instrumented action totals cover public PyAutoGUI calls; shell/API GUI changes may not be represented.
- P0/P1 Task061 used separate VMs but shared the same single-sequence Qwen service concurrently. This is a run-order and inference-queue confound.
- One rollout per task/condition does not support statistical significance claims.

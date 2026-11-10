# ModularCUA P0 — Frozen Core V0 results

**Suite:** OSWorld-v2.1, Tasks 001, 003, 013, 014, 061  
**Condition:** independent ModularCUA Core V0; EGC disabled  
**Model:** frozen Qwen3.8-27B, revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`  
**Core source:** `6c1f4aea61e5cecb936d90c0dc53be6ae8fe47d7`  
**Config SHA-256:** `6ab6d8726a6834ece2d6b855c97ecb590372acdb0006fb5fd2640886db59bc98`  
**Budget:** 150 model turns and 5,400 seconds per episode; GUI-action counters are separate and instrument only public PyAutoGUI calls.

## Official results

| Task | Run | Status | Official partial | Binary success | Turns | IPython calls | Instrumented GUI actions | Input / output tokens | Runtime (s) |
|---|---|---|---:|---|---:|---:|---:|---:|---:|
| 001 | `p0-task001-20261105T152816Z` | MEASURED | 1.00 | true | 100 | 100 | 25 | 4,518,964 / 57,814 | 1,605.8 |
| 003 | `p0-task003-20261105T155519Z` | MEASURED | 0.00 | false | 73 | 79 | 8 | 1,875,479 / 34,547 | 1,086.3 |
| 013 | `p0-task013-20261105T161341Z` | MEASURED | 1.00 | true | 56 | 57 | 74 | 1,743,947 / 36,398 | 1,296.7 |
| 014 | `p0-task014-20261105T163533Z` | MEASURED | 0.00 | false | 103 | 105 | 0 | 3,837,244 / 69,837 | 18,567.3 |
| 061 | `p0-task061-20261105T214532Z` | MEASURED | 0.00 | false | 54 | 56 | 0 | 1,092,082 / 25,430 | 5,574.9 |

Task061's Actor exhausted the 5,400-second wall-clock budget at turn 54; the official evaluator then completed and returned a valid 0.00 / false result. The measured end-to-end elapsed time was 5,574.9 seconds. The budget exhaustion is recorded in the trajectory, but the official score is taken only from the evaluator result.

## Five-task aggregate

Across all five official results, the mean official partial score is **40.0%** (2.00/5) and binary SR is **40.0%** (2/5).

Across the five episodes: 386 model turns, 397 IPython calls, 28,130.9 seconds, 107 instrumented PyAutoGUI action attempts/executions, 13,067,716 input tokens and 224,026 output tokens. Public PyAutoGUI instrumentation does not capture all possible shell/API GUI mutations; in particular, the zero counters for Tasks014/061 do not prove that no GUI mutation occurred.

## Artifact locations

Run records, completion/evaluator outputs, event journals, screenshots and artifacts are under:

`experiments/modularcua/ten_hour_20261106T151032Z/P0/attempt2/task-{001,003,013,014,061}/`

Each result is in its run subdirectory's `official_result.json`, `summary.json`, and parent `completion.json`.

## Validity and caveats

- All five episodes use the frozen P0 source/config snapshot above and each has a successful runner exit and an official evaluator result.
- P0 and P1 Task061 ran on separate VMs while sharing one single-sequence Qwen service. This adds inference scheduling and run-order confounding to the pairwise comparison.
- Task014 took about 5.16 hours from start to official result. The task episode exhausted its 5,400-second actor budget and only later produced the official evaluator result; its official score is still recorded as returned by the pinned evaluator.
- This is one run per task and condition; no significance claim is supported.
- Older P0 runs from different source snapshots are not substituted into this table.

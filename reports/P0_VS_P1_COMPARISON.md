# P0 vs P1 — OSWorld-v2.1 five-task comparison

**Status:** Both conditions have five official results. The score comparison is complete; causal interpretation is limited because P1's contract/verifier/feedback chain failed in every episode.

| Task | P0 partial | P1 partial | Delta (P1−P0) | P0 binary | P1 binary | Evidence status |
|---|---:|---:|---:|---|---|---|
| 001 | 1.00 | 1.00 | 0.00 | true | true | Both official results |
| 003 | 0.00 | 0.00 | 0.00 | false | false | Both official results |
| 013 | 1.00 | 0.00 | −1.00 | true | false | Both official results |
| 014 | 0.00 | 0.84 | +0.84 | false | false | Both official results |
| 061 | 0.00 | 0.00 | 0.00 | false | false | Both official results |

Official five-task aggregates: P0 Partial Score **40.0%** (2.00/5), P1 Partial Score **36.8%** (1.84/5), difference P1−P0 = **−3.2 percentage points**. P0 binary SR **40.0%** (2/5), P1 binary SR **20.0%** (1/5), difference P1−P0 = **−20.0 percentage points**. P1 partial scores improved on 1 task, tied on 3, and degraded on 1. Relative to P0, P1 had no additional full success and lost one full success on Task013.

## Cost summary

| Condition / denominator | Turns total / mean | IPython calls total / mean | Instrumented GUI actions executed total / mean* | Input tokens total / mean | Output tokens total / mean | Runtime total / mean (s) |
|---|---:|---:|---:|---:|---:|---:|
| P0, 5 tasks | 386 / 77.2 | 397 / 79.4 | 107 / 21.4 | 13,067,716 / 2,613,543 | 224,026 / 44,805 | 28,130.9 / 5,626.2 |
| P1, 5 tasks | 335 / 67.0 | 349 / 69.8 | 103 / 20.6 | 12,932,842 / 2,586,568 | 270,788 / 54,158 | 13,374.8 / 2,675.0 |

\* Instrumentation counts public PyAutoGUI calls only. Shell/API GUI mutations can be unobserved; zero instrumented calls does not prove no GUI change occurred.

## Interpretation

- Task001 ties at full score; Task003 and Task061 tie at zero; P0 scores higher on Task013; P1 scores higher on Task014 partial score but both binary-fail it.
- P1 had five official evaluations, but its required contract output failed schema validation in all five, and no Actor feedback-delivery events were recorded. The intended EGC mechanism was not demonstrated end to end, so score differences cannot be attributed to EGC.
- Task061 P0 and P1 used independent VMs but shared the same single-sequence Qwen service concurrently, creating scheduling/run-order confounding. P0 Task014's post-budget evaluation wait also overlapped the P1 suite.
- This is one rollout per task and condition. No statistical significance or broad generalization claim is justified.

**Decision:** P1 did not improve aggregate official results in this five-task sample. The run-level audit shows that P1 did not deliver the intended EGC mechanism, so this is not evidence that a correctly operating EGC method is ineffective. It is evidence that the executed P1 implementation failed its mechanism-validity gate. Further comparison should wait until contract parsing, evidence verification, and Actor feedback are demonstrated in a live integration run.



## Additional paired extensions (not part of the primary five-task aggregates)

| Task | P0 partial / binary | P1 partial / binary | P1−P0 partial |
|---|---:|---:|---:|
| 010 | 0.00 / false | 1.00 / true | +1.00 |
| 004 | 0.8333 / false | 0.6111 / false | −0.2222 |

These are separate, single-run extensions. P1’s Task010 requirement contract was rejected, no feedback was delivered, and finish was allowed unverified. Task004 P1 also had no validated feedback path and had a history-summarizer context-length error. Neither extension isolates a working EGC effect. Detailed Task010 artifact analysis is in TASK010_P0_P1_FAILURE_ANALYSIS.md; Task004 run records are under experiments/modularcua/ten_hour_20261106T151032Z/extension_task004/.

# P1 EGC live-runtime audit

**Scope:** Five completed P1 episodes in `experiments/modularcua/ten_hour_20261106T151032Z/P1/attempt1/`. This audit counts only events that were written during the episodes. It does not infer module success from config flags or unit tests.

## Finding

P1 was launched with EGC modules enabled, and module events were recorded, but the intended evidence-grounded control chain did **not** operate end to end. The requirement extractor's live output was rejected in every task. The final gate consequently had no validated contract/verifier state to act on. In the four episodes where the Actor reached a finish request, the gate recorded `ALLOW_FINISH_UNVERIFIED`; the P1 Task061 episode has no recorded termination decision. No `egc_actor_feedback_delivered` event appears in any of the five module journals.

Thus the five P1 official evaluator results are valid for the executed configured condition, but P1 does not constitute a successful test of active verification/recovery or a controlled estimate of EGC's effect.

### Additional raw-output diagnosis

Inspection of each run's raw requirement-contract response and provider usage identifies the common failure more precisely:

- In all five core P1 episodes, max_aux_tokens was 2,048. The provider reported finish_reason=length, exactly 2,048 completion tokens, and 2,048 reasoning tokens. The assistant message had empty/missing content; the non-JSON text was in the separate reasoning field. The runtime parsed content, got an empty string, and correctly rejected it.
- The separate Task010 P1 extension had the same pattern: 2,048 completion/reasoning tokens, finish_reason=length, and no content.
- The separate Task004 P1 extension did begin emitting a JSON object in content, but that response was also cut off at 2,048 completion tokens (1,705 reported as reasoning tokens); parsing failed with an unterminated string at character 1,351 and finish_reason=length.

This is direct evidence that the auxiliary generation budget was exhausted before a complete machine-readable contract was returned. It does not prove that merely increasing the token limit will fix the issue: the model may spend a larger budget on reasoning again. The parser's fail-closed behavior is supported by these traces; the demonstrated upstream failure is the output contract/budget interaction with Qwen's reasoning channel.

### Follow-up output-budget probes (offline replay of archived requests)

The exact archived contract requests were replayed against the same frozen model revision and endpoint, changing only `max_tokens`; no VM or benchmark episode was run. Production runtime schema, grounding, and citation checks were then applied offline to the returned content.

| Archived request | Max tokens | Finish / completion (reasoning) tokens | JSON | Runtime contract schema | Evidence grounding/citations | Latency |
|---|---:|---|---|---|---|---:|
| Task004 P1 | 4,096 | stop / 2,566 (1,630) | valid | pass | pass; cites the sole allowed source event | 56.08 s |
| Task010 P1 | 4,096 | length / 4,096 (3,024) | truncated | fail (unparseable) | fail/not evaluable | 89.43 s |
| Task010 P1 | 8,192 | stop / 6,751 (4,497) | valid | pass | pass; citations match the sole allowed source event | 147.82 s |

The Task010 response at 8,192 would pass the current structural and citation gates when replayed through their validation logic. This establishes that the 2,048-token cap was a concrete cause of the original contract rejection for this input, and that 8,192 was sufficient for this particular request. It does **not** establish semantic completeness/accuracy of the extracted contract, correctness of later verification, successful Actor feedback, or any OSWorld score effect. The Task004 probe is a separate request and cannot establish a universal token threshold.

Raw requests, responses, and probe manifests are preserved under `experiments/modularcua/ten_hour_20261106T151032Z/egc_output_budget_probe_20261106/`. These were diagnostics after the official suite; no official result was changed.

### Five-task fixed-input replay at 8,192 tokens

The exact archived initial requirement-contract messages from each of the five P1 episodes were replayed with only `max_tokens` changed to 8,192. No VM or evaluator was used. The current runtime's JSON, schema, grounding, and citation acceptance logic was applied to each saved response.

| Task | Finish | Completion tokens (reasoning) | JSON/schema/citations | Runtime-equivalent acceptance | Latency |
|---|---|---:|---|---|---:|
| 001 | stop | 5,306 (3,429) | pass / pass / pass | accepted | 116.09 s |
| 003 | length | 8,192 (8,192) | fail / fail / fail | rejected | 178.97 s |
| 013 | stop | 1,877 (1,279) | pass / pass / pass | accepted | 40.86 s |
| 014 | length | 8,192 (6,077) | fail / fail / fail | rejected | 179.50 s |
| 061 | stop | 5,882 (4,470) | pass / pass / pass | accepted | 128.32 s |

Thus 8,192 repairs machine-readable output for 3/5 archived inputs, but Tasks003 and 014 still use the full allowance without completing JSON. It is not a sufficient universal fix. A limited post-hoc quote check on the three accepted outputs also found semantic-quality caveats: Task001 has one source_quote containing an ellipsis that is not an exact instruction span (7/8 quotes were exact substrings); Task013 has two requirements both quoting the entire same instruction; Task061 has five exact quotes, but an optional editor preference was represented as a requirement and marked UNKNOWN. These outputs pass current structural/citation checks but are not certified as semantically sound contracts.

The five-call replay cost 643.74 seconds total and 29,449 completion tokens (23,447 reasoning tokens), in addition to the earlier Task010/Task004 probes. This is offline diagnostic overhead, not runtime overhead measured during a task.

Raw requests/responses, validator fields, and costs are under `experiments/modularcua/ten_hour_20261106T151032Z/egc_output_budget_probe_20261106/all_core_contracts_max8192/`. The next necessary validation is a stricter source-span/requirement-quality gate plus a generation method that controls reasoning-token consumption; neither was implemented or benchmark-tested in this mission.

## Observed live chain

In each run, the runtime recorded a task-start contract request, received an assistant response whose logged payload contained a `reasoning` field, and rejected it with `raw_json_valid=false`, `schema_valid=false`, and `schema_error="response is not a JSON object"`. The same result is visible at event sequence 14 of each `module_calls.jsonl`. Since no contract was committed, later gate decisions report `no validated requirement contract or verifier unavailable`.

| Task | Contract response | Contract validator | Finish control | Feedback delivered |
|---|---|---|---|---|
| 001 | Received; logged response has reasoning text but no JSON object | REJECTED | `ALLOW_FINISH_UNVERIFIED` | 0 |
| 003 | Same | REJECTED | `ALLOW_FINISH_UNVERIFIED` | 0 |
| 013 | Same | REJECTED | `ALLOW_FINISH_UNVERIFIED` | 0 |
| 014 | Same | REJECTED | `ALLOW_FINISH_UNVERIFIED` | 0 |
| 061 | Same | REJECTED | No termination event recorded | 0 |

Exact per-task journals: `P1/attempt1/task-*/<run-id>/module_calls.jsonl`; rejected raw outputs are under each run's `module_outputs/` and the matching response record references the output file.

## Module-by-module status

| Module | Live evidence | Assessment |
|---|---|---|
| Requirement Contracts | One real Qwen request per task; all five outputs rejected as non-JSON/schema-invalid | Inference ran, but no valid contract reached runtime state. This is the earliest verified break in the chain. |
| Structured State Manager | One deterministic initialization commit per task, with task-start evidence and an `unknown/unextracted` initial state | Initialization is evidenced. No later evidence here establishes useful incremental verified-state tracking. |
| Provenance Tracker | Hundreds of deterministic tracker entries per task (321, 660, 438, 417, 321, respectively) | Runtime instrumentation ran. Event count alone does not prove a causally complete source→operation→artifact graph or that recovery consumed it. |
| Contract Updater | Marked `NOT_INVOKED` in each episode | No live incremental contract update. |
| Visual State Interpreter | Marked `NOT_INVOKED` in each episode | No live auxiliary visual interpretation call evidenced. |
| Self Verifier | Marked `NOT_INVOKED` in each episode; no verifier output used by the finish gate | No task-requirement verification chain established. |
| Recovery Controller | Marked `NOT_INVOKED` in each episode; no repair feedback delivered | No recovery was proposed and executed by this controller. |
| Termination | Four finish requests led to `ALLOW_FINISH_UNVERIFIED`; Task061 has no gate event | The callback ran for four tasks but could not verify or block completion. There is no evidence the gate improved outcomes. |
| History summarizer | Provider returned HTTP 400 in multiple episodes because at least 131,073 input tokens exceeded the 131,072 context limit; actor execution continued | Auxiliary context-management defect; it did not invalidate completed official evaluator outputs. |

## Root cause and appropriate claims

- **Root cause for absent verified control:** all five contract calls exhausted the 2,048-token completion budget in the reasoning channel and returned no JSON content; the gate then failed open when no contract/verifier was available.
- **Not established:** whether the underlying model could have returned a valid contract with different message formatting, whether a valid contract would have led to accurate visual checks, or whether a repair would improve any official score.
- **No valid evidence of EGC-caused recovery:** zero Actor feedback-delivery events and zero recovery-planner calls accepted/executed.
- **No success claim:** module activation/configuration and deterministic provenance logging are not equivalent to functioning verification or recovery.

## Corrective work required before another P1 comparison

1. Fix the auxiliary response/message contract so the extractor's actual generated content is available as a strict JSON object; preserve raw response evidence and fail validation closed.
2. Add a real runtime integration check using the same chat template/parser path as the production runner. Require a validated contract commit before P1 episodes are admitted as active-EGC trials.
3. Verify that screenshot evidence reaches the Self Verifier, that its verdict is schema- and citation-validated, and that a supported FAIL reaches the original Actor as an actual context update.
4. Make finish behavior match the preregistered policy. If no contract/verifier exists, record `UNKNOWN` and perform a bounded evidence request or label the run as EGC-disabled/invalid for the causal comparison; do not represent `ALLOW_FINISH_UNVERIFIED` as a successful verification gate.
5. Fix and bound history summarization below the actual context window; record auxiliary token usage and latency separately.

No code was changed by this audit; the current live P0 Task061 run and frozen Qwen service were left untouched.

## Source follow-up (2026-11-10; not yet validated)

The historical episode findings above remain unchanged. A later source update now disables Qwen thinking for auxiliary calls, retries one truncated response with a bounded token cap, rejects requirement quotes that are not exact spans of their cited evidence, and disables the history summarizer in the checked-in observe-only config. A bounded pre-finish feedback path is available only by explicit opt-in; it requests evidence and blocks unresolved finish attempts after a configured limit, but it does not perform repairs and has not been validated against OSWorld or the frozen inference endpoint. Do not reinterpret the archived P1 runs as having used these changes.

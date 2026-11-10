# ModularCUA implementation status

Updated 2026-11-10 against the source tree and archived benchmark reports.

## Current experiment status

Core V0 has five measured OSWorld-v2.1 results for Tasks 001, 003, 013, 014, and 061. The official mean partial score is 40.0% and binary success rate is 40.0% (2/5). These are one-run-per-task results, not a broad performance estimate. See `reports/P0_FIVE_TASK_RESULTS.md` for run identifiers, configuration/source digests, timing, and caveats.

The five P1 episodes also have official evaluator results: mean partial score 36.8%, binary success rate 20.0% (1/5). They do **not** validate active Evidence-Grounded Control. In all five, the requirement contract was rejected; no EGC feedback reached the Actor; and the finish callback allowed unverified completion in four episodes. See `reports/P1_FIVE_TASK_RESULTS.md` and `reports/P1_EGC_MODULE_AUDIT.md`.

## Implementation status

| Area | Status | Evidence and boundary |
|---|---|---|
| Independent model-to-IPython loop | Implemented | `src/modularcua/host/agent.py`; independent request, tool dispatch, accounting, context, and finish path. |
| OSWorld-v2.1 runner | Implemented for reviewed task IDs | `src/modularcua/environments/osworld_v2/runner.py`; launches a guest and invokes the official evaluator. Requires the matching parent checkout, assets, VM, and service. |
| Persistent guest IPython | Implemented with a custom bridge | `InteractiveShell` over the OSWorld `/execute` endpoint and a file mailbox; this is not Prime's Jupyter/ZeroMQ kernel protocol. |
| Event journal and artifacts | Implemented | Append-only episode events and content-addressed host-side artifacts. |
| P0 benchmark | Measured, limited sample | Five official results; 40.0% mean partial and 40.0% binary SR. One run per task. |
| P1 auxiliary EGC runtime | Observe-only by default; mechanism not validated | Historical P1 contract calls failed in all five audited episodes; no Actor feedback or executed recovery was recorded. |
| Pre-finish Actor feedback | Experimental opt-in, disabled by default and not validated | Bounded evidence requests can be delivered and unresolved finishes are blocked after the configured limit. No automatic repair is executed. |
| EGC response handling | Remediation implemented, not yet re-evaluated | Auxiliary Qwen calls now request non-thinking output and retry once on output truncation with a bounded token cap. This has not yet been validated against the frozen serving endpoint. |
| EGC context summarizer | Disabled by default | Historical P1 calls exceeded the model context limit. A bounded, token-aware implementation is still needed before re-enabling it. |
| Task-specific verification and repair | Not implemented end to end | Current file metadata and format checks do not establish semantic task correctness; no bounded Actor repair loop is wired. |
| Security isolation | Not a sandbox | Model-generated Python runs with the guest user's permissions. |

## Changes made in the current source update

- P1 run metadata now distinguishes `P1_EGC_OBSERVE_ONLY` from the opt-in `P1_EGC_BOUNDED_FEEDBACK_EXPERIMENTAL` condition and records actual Actor feedback delivery.
- Auxiliary EGC inference disables Qwen thinking mode, retries once when the provider reports output truncation, and records attempt budgets and usage.
- Requirement source quotes must match an exact span of cited evidence. The experimental pre-finish path can request evidence and fail closed, but it is disabled by default and does not perform repairs.
- The EGC config uses a 4,096-token initial cap with an 8,192-token ceiling and disables the history summarizer by default.

These changes have not been run against OSWorld or the frozen inference endpoint. Earlier benchmark reports remain historical records of the configurations actually executed; do not rewrite their condition labels or scores.

## Next work

1. Replay the archived contract requests through the updated production adapter and validator. Confirm valid JSON, schema acceptance, exact source-span grounding, latency, and total token use for all five tasks.
2. Implement an independently grounded, task-specific verifier and connect its result to the experimental feedback path. Preserve `UNKNOWN` when evidence is missing; add a bounded, targeted repair loop only after verification is trustworthy.
3. Run a single-task end-to-end pilot and require a valid contract, a verified PASS/FAIL/UNKNOWN result, and a delivered feedback event before calling the condition active EGC.
4. After the mechanism gate passes, run a pre-specified multi-run comparison with frozen source/config/model, isolated inference capacity, and per-task cost and outcome reporting.

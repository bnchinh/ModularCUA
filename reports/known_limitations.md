# Known limitations

Updated 2026-11-10. This list describes the current prototype and the historical runs included in `reports/`.

## Runtime and environment

1. The guest bridge uses `IPython.core.interactiveshell.InteractiveShell` over the OSWorld `/execute` endpoint and a file mailbox. It does not implement Prime's Jupyter/ZeroMQ protocol, IOPub streaming, HMAC framing, kernel snapshot/revival, or complete restart semantics.
2. The model adapter uses OpenAI Chat Completions. It is not wire-compatible with Prime's pinned Pi AI adapter; provider-specific reasoning, tool-call, image, error, and output-cap behavior may differ.
3. Model-generated Python runs in the OSWorld guest account. The capability registry documents helper operations but does not restrict Python imports, filesystem access, processes, or network.
4. GUI action instrumentation observes public PyAutoGUI calls and selected helpers. Arbitrary shell, application API, or nested library mutations may be missed; a zero counter is not evidence of no state change.
5. Context compaction is deterministic and character-bounded, not token-aware. The auxiliary history summarizer is disabled by default after historical calls exceeded the served context window. Re-enable it only after bounding the exact serialized prompt and reserving room for model output.

## Evidence-Grounded Control

6. Historical P1 runs did not demonstrate active EGC: requirement extraction failed schema validation in all five audited episodes, no Actor feedback was delivered, and no recovery action was executed.
7. Current source changes request non-thinking Qwen auxiliary output and retry one truncated response with a bounded token cap. These changes are not yet validated against the frozen endpoint; they do not by themselves establish correct contracts.
8. The runtime has no complete task-specific semantic verifier or bounded repair loop. Filesystem metadata changes and structural format checks are evidence of activity, not proof that the requested task postconditions hold.
9. P1 is observe-only by default. An opt-in experimental gate can request evidence and block unresolved finishes, but it uses the current model-based verifier, is not enabled in the checked-in configs, and has not been validated live. An absent/invalid contract or verifier must remain `UNKNOWN`, never a successful verification.

## Benchmark interpretation

10. The current five-task P0 and P1 aggregates each contain one rollout per task. The P1 chain failed, so score differences do not estimate the effect of correctly operating EGC; Task061 also shared an inference service concurrently across conditions.
11. The P0 and P1 reports refer to exact recorded source/config snapshots. Preserve those historical manifests and do not attribute the results to later code changes without a new run.
12. The reports are summaries; raw trajectories, screenshots, VM images, model weights, and benchmark assets are excluded from the public source bundle. Reproduction requires the pinned compatible OSWorld checkout and external infrastructure.

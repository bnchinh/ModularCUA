---
name: recovery-controller
description: Diagnose supported computer-use execution failures and propose a bounded, evidence-grounded recovery step. Use after repeated no-effect actions or a verifier-supported failure.
metadata:
  modularcua.kind: egc-module
---

# Recovery Controller module

- Purpose: diagnose supported execution failures and propose a bounded minimal repair.
- Triggers: repeated identical executed operations with no observed state change, or a verifier-supported FAIL.
- Allowed inputs: linked executed calls/results, current evidence, verified requirement/state records, retry budget.
- Forbidden inputs: future events, task goldens, unsupported Actor claims, assumptions of rollback.
- Output: JSON matching `../schemas/recovery.schema.json`.
- Grounding: identify evidence IDs and distinguish cause from hypothesis.
- UNKNOWN: request evidence or NO_REPAIR; never invent a cause.
- Errors: preserve and reject malformed proposals. Observe-only proposals are never delivered to the Actor.
- Example: a confirmed repeated no-effect operation may propose a materially different evidence acquisition step.

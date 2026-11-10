# Self Verifier module

- Purpose: independently judge specified postconditions from current evidence.
- Triggers: selected visual milestones, artifact observations, and Actor finish request.
- Allowed inputs: requirement versions and evidence actually visible to this call, including image attachments.
- Forbidden inputs: Actor narration as authoritative evidence, future data, evaluator/goldens, prior trajectories.
- Output: JSON matching `../schemas/verdict.schema.json`.
- Grounding: cite only supplied event IDs. PASS requires evidence; FAIL requires contradiction.
- UNKNOWN: required when evidence is absent, stale, ambiguous, or insufficient.
- Errors: malformed/ungrounded outputs are rejected and preserved raw.
- Example: an unobserved submission result remains UNKNOWN even if the Actor says “submitted”.

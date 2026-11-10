# Structured State module

- Purpose: maintain a compact evidence-linked state, with deterministic storage, freshness invalidation, and model-proposed visual facts.
- Triggers: initialization, selected fresh screenshot observations, and relevant environment changes.
- Allowed inputs: attached screenshot bytes and actual tool-result evidence at the invocation cutoff.
- Forbidden inputs: later screenshots, Actor claims treated as facts, evaluator state, hidden application state.
- Output: JSON matching `../schemas/state_update.schema.json`.
- Grounding: every fact cites a real event ID in this input. Distinguish OBSERVED, INFERRED, CLAIMED and preserve UNKNOWN.
- UNKNOWN: use missing_evidence; do not infer unreadable content.
- Freshness: transient GUI facts expire on a relevant newer observation; persistent document facts retain source provenance.
- Errors: raw proposal is retained; invalid/ungrounded proposals are not committed.
- Example: a newly visible window title may be transient; a clearly readable document constraint is persistent only with screenshot evidence.

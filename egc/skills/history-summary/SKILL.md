---
name: history-summary
description: Preserve task-relevant execution history, outcomes, failures, and unresolved facts when context is compacted. Use when an agent needs to summarize a long computer-use session without treating claims as verified results.
metadata:
  modularcua.kind: egc-module
---

# History Summary module

- Purpose: summarize prior history only at an actual runtime compaction boundary.
- Triggers: when the existing context compactor fires.
- Allowed inputs: pre-compaction messages and evidence refs up to the exact boundary.
- Forbidden inputs: later events, evaluation scores, imagined completed requirements.
- Output: structured JSON in `history_summarizer.md`.
- Grounding: separate verified progress, claims, failures and unknowns; cite source event IDs.
- UNKNOWN: retain unresolved items explicitly.
- Errors: preserve raw output; never substitute a hand-written model response.
- Example: report a recorded tool result as observed execution, not as a completed task requirement.

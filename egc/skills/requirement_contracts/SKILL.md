# Requirement Contracts module

- Purpose: extract source-grounded, versioned requirements without solving the task.
- Triggers: task_start; later source evidence may trigger contract_updater.
- Allowed inputs: exact task instruction, current screenshot/tool evidence, event IDs visible by the invocation boundary.
- Forbidden inputs: future events, historical trajectories, evaluator/golden data, benchmark answers, unseen document text.
- Output: JSON matching `../schemas/requirement.schema.json`; all extracted statuses start UNKNOWN or PENDING_SOURCE.
- Grounding: quote source text and cite existing event IDs only. Never fill unknown numbers or source facts.
- UNKNOWN: use UNKNOWN/PENDING_SOURCE and list the missing source.
- Errors: preserve raw output and validation failure; never repair silently.
- Example: a request to inspect an unopened file creates a pending-source requirement, with no guessed file contents.

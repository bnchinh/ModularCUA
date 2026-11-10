# ModularCUA architecture

## Core V0 control path

```text
official OSWorld-v2.1 task class + ModularCUA system prompt
  -> Python OpenAI-compatible model adapter
  -> independent AgentLoop
  -> one registered `ipython` tool call
  -> host bridge submits a cell to persistent guest IPython
  -> serialized result + screenshot/evidence event
  -> next model turn or explicit finish
  -> official DesktopEnv Task001 evaluator
```

The model/provider and benchmark evaluation stay on the host. GUI operations happen inside the OSWorld guest through the existing typed `PythonController` HTTP bridge. The host never executes model Python locally. Tool results correlate to the model's `tool_call_id`; images returned by `attach_image(path)` are content-addressed as artifacts and attached to the next model context as image content.

### Host components

- `host/model.py`: OpenAI-compatible Qwen adapter; keeps raw assistant fields, tool calls, request ID, finish reason, usage and latency. Sampling fields are omitted when the pinned Prime run omitted them.
- `host/prompt.py`: one `ipython(code)` capability and message builder.
- `host/agent.py`: independent deterministic turn loop; bounded model-request retry; tool schema validation; serialized dispatch; before-finish hook; usage accounting; turn-based context compaction.
- `host/kernel.py`: guest bootstrap and persistent IPython shell bridge; cells have unique IDs and execute serially in a guest process.
- `host/journal.py`: append-only JSONL plus content-addressed external artifacts.
- `host/modules.py`: lifecycle subscription/action authorization registry. With no modules, hooks have no prompt or tool effects.
- `host/context.py`: deterministic context compaction keeps immutable task text, recent messages and complete tool-call/result groups. Kernel variables and full event history live outside model context.
- `host/budget.py`: model-turn and wall-time budget.
- `environments/osworld_v2/runner.py`: loads the pinned task class/assets and ModularCUA prompt, starts a fresh Docker/QEMU VM, runs the independent loop and invokes the official task evaluator after the episode.

## Evidence-Grounded Control status

The repository contains two incomplete EGC pieces. `modules/verified.py` is a local lifecycle-hook fixture with a sentence-level UNKNOWN ledger and one before-finish message; it is not wired into the current `--stage p1` runner. `egc/runtime.py` records auxiliary evidence/module calls, but the current agent loop does not reliably inject its outputs into actor continuation, issue targeted recovery, or enforce a termination decision. Therefore P1 is **not yet active EGC** and must not be described or benchmarked as if the planned six modules were operational. A trustworthy task-specific artifact verifier and bounded repair path are also not yet present.

## Capability and permission boundaries

Only `ipython` is model-facing in this version. Guest capability helpers are bootstrapped by `host/capabilities.py`; no Agent-S seed pack is loaded. Generated guest Python can still use other installed modules, so the registry is an interface description and helper API, not a security sandbox. The kernel runs under the guest account and inherits that account's permissions.

## Session and failure behavior

The event log is append-only; screenshots/tool images are separately hashed. Model requests retry once after an exception. Tool exceptions are returned as correlated tool results. The current kernel bridge preserves namespace across ordinary cells but does not revive it after a guest worker crash; the runner records the error and does not claim prior variables survived. Context compaction is deterministic rather than Prime's model-generated compaction. No agent session resume is implemented yet.

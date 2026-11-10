# Prime and Agent-S component mapping

## Pinned sources inspected

Prime Agent: commit `a9b5d88b50db50860088772a408e867f8071b507`, package `prime-agent@0.8.0-beta.546.1.a9b5d88`, MIT. The archived package is at `experiments/agents4_qwen38_task001_20261104/runtime_host/opt/prime-agent/node_modules/prime-agent/`; its generated `.js.map` files embed original TypeScript sources. Upstream source links are pinned to that commit:

- [`agent-session.ts`](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/src/core/agent-session.ts)
- [`kernel/index.ts`](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/src/core/kernel/index.ts)
- [`tools/ipython.ts`](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/src/core/tools/ipython.ts)
- [`rlm-runtime.ts`](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/src/core/rlm-runtime.ts)
- [`extensions/types.ts`](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/src/core/extensions/types.ts)
- [RLM programming model](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/docs/rlm.md)
- [RLM runtime architecture](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/docs/rlm-runtime.md)

Relevant source-map line anchors in the pinned package:

| Upstream file / function | Source lines | Verified behavior |
| --- | ---: | --- |
| `src/core/agent-session.ts`, model dispatch via `agent.prompt(preparedMessages)` | 6013–6021; 8394 onward | Host owns agent session, dispatches a prepared conversation to provider-backed agent and handles post-turn state/compaction. |
| `src/core/agent-session.ts`, `compact()` | 7309 onward | Compaction is a session operation over retained branch history; it does not discard the independent kernel. |
| `src/core/kernel/index.ts`, `KernelManager.execute()` | 956–963 | Kernel execution is queued/serialized and successful work schedules a state snapshot. |
| `src/core/kernel/index.ts`, Jupyter `execute_request` and correlation | 1017–1026; 925 onward | Standard shell execution request; reply/output messages are associated with the active request message ID. |
| `src/core/tools/ipython.ts`, tool execution handler | 639–650 onward | IPython is explicitly sequential within one tool-call batch and starts a session kernel lazily. |
| `src/core/tools/ipython.ts`, kernel provisioner | 417 onward | Lazy startup/restoration and progress reporting. |
| `src/core/extensions/types.ts`, `ExtensionAPI.on()` | 1018–1032 onward | Typed extension lifecycle registration; includes message/tool/turn/provider events. |

The local Prime package is a compiled distribution with source maps, not a full Prime git checkout. The archived Agent-S manifest identifies the pinned Prime commit and package version; the source-map line anchors above resolve to the original TypeScript. Prime RLM docs say the model-facing tool is one persistent `ipython` tool and the TypeScript host owns provider calls, persistence, child lifecycle, accounting and policy.

Agent-S is pinned at `0fff0e634869dab72027435b4586e62300185d41` in `experiments/agents4_qwen38_task001_20261104/upstream/Agent-S/` (MIT). Its OSWorld system prompt and suffix are defined in `agent_s4/eval/osworld.py` (`TOOL_SYSTEM_PROMPT`, `INSTRUCTION_CONTEXT_SUFFIX`, `load_system_prompt` around line 294). Its Prime adapter in `agent_s4/harness/prime/evaluator.py` defines the OSWorld runtime addendum around lines 34–46, endpoint/model configuration around lines 232–380, and Prime CLI construction around lines 350–450. The Task001 evaluator is `evaluation_examples/task_class/task_001.py`; its exact file hash is pinned in the run manifest.

## Mapping

| Prime / Agent-S component | ModularCUA component | Classification | Difference / fidelity |
| --- | --- | --- | --- |
| Prime `AgentSession` and Pi-backed agent loop | `src/modularcua/host/agent.py` | Independent implementation | Own Python loop, turn count, message handling, dispatch, finish gate and retry path. No Prime CLI/session engine is invoked. OpenAI Chat Completions wire/request objects differ from Pi AI's OpenAI-completions adapter. |
| Prime `ipython` tool schema | `host/prompt.py` | Faithful adaptation | One `ipython(code)` tool and sequential dispatch; JSON schema is a direct compact equivalent. |
| Prime `KernelManager` over signed Jupyter/ZeroMQ | `host/kernel.py` | Paper/API-inspired adaptation | Guest owns one persistent IPython `InteractiveShell`; host uses atomic files through OSWorld `/execute`. It is not Jupyter/ZeroMQ and lacks Prime's protocol correlation, HMAC framing, control channel, namespace snapshot/revival and full output stream handling. |
| Prime `rlm-runtime.ts` and host requests | `host/modules.py`, `host/registry.py` | Independent minimal API | Typed host module events/actions, but no recursive RLM child lifecycle or host comm protocol in this iteration. |
| Prime session/event persistence | `host/journal.py` | Faithful adaptation | Append-only JSONL and content-addressed artifacts. No Prime session serialization/resume format. |
| Prime compaction | `host/context.py` | Paper-inspired minimal adaptation | Deterministic bounded transcript summary; no model-generated summary, Prime threshold logic, or persisted session branch. Kernel data and journal remain outside context. |
| Prime budget/accounting | `host/budget.py`, `host/agent.py` | Independent | Deterministic 150-turn/5400s caps and OpenAI token accounting. Not Prime's usage/context-tree attribution. |
| Prime/Agent-S OSWorld task adapter | `environments/osworld_v2/runner.py` | Independent adapter | Direct `DesktopEnv` setup/evaluation using the same task class. No Agent-S/Prime episode wrapper or Prime step runner. |
| ModularCUA OSWorld system prompt | `prompts/osworld_ipython_system.md` | Independent implementation | Current P0 uses its own prompt. It does not load Agent-S prompt constants or Prime's hidden provider prompt. |
| Agent-S combined seed | Not loaded or staged by current P0 | Excluded by independence requirement | Guest helpers are defined in `host/capabilities.py`; this is separate code and is not the Agent-S seed pack. |

## What is not reused

No Prime CLI, `AgentSession`, Pi AI/Pi Agent loop, compiled Prime extension lifecycle, RLM subagent manager, Prime kernel-manager code, Agent-S prompt, Agent-S runner, or Agent-S seed helper is imported or staged by the current P0 runner. No upstream code is vendored in ModularCUA. The harness owns its episode loop and uses an independently authored prompt and capability bootstrap.

## License and attribution

ModularCUA code is MIT-licensed in this directory. Agent-S and Prime are cited as MIT-licensed references at the pinned commits; the archived package metadata confirms Prime's MIT license. No Agent-S seed pack or Prime source component is vendored or staged by the current P0 runner.

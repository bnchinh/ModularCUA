# ModularCUA implementation status

Updated 2026-11-05 from the current source tree and archived run records.

## Current experiment state

The five-task corrected-source P0 suite is **pending a new freeze and then five sequential official evaluations**. A prior frozen-source Task001 run scored 1.00 / binary success (71 model turns, 69 IPython calls, 28 instrumented PyAutoGUI calls), but a later GUI diagnostic found and fixed a coordinate-space defect that changes the prompt/capability description. That score remains valid for its recorded source and excluded from the corrected-source aggregate. Prior Task003 evidence is from a different digest or was interrupted and remains excluded. The coordinate conversion, screenshot encoding, screenshot/action journaling, and earlier multimodal compaction fixes are covered by local tests; live no-task GUI integration now passes. P1/EGC is not being run.

The first P0 Task001 attempt `p0-task001-20261105T095012Z` at `experiments/modularcua/p0/p0-task001-20261105T095012Z/` reached real Qwen3.8-to-guest-IPython execution and was interrupted before evaluation. It is marked `INTERRUPTED_USER_REQUEST` / `NOT_MEASURED` and is excluded from results. A separate fresh attempt `p0-task001-20261105T104819Z` completed the 150-turn budget and official evaluation, scoring 0.00 partial / binary false. Its manifest, summary and evaluator record are under `experiments/modularcua/p0_resume_20261105/p0-task001-20261105T104819Z/`.

## Implementation evidence

| Requirement | Current status | Evidence / limitation |
|---|---|---|
| Independent model-to-IPython control loop | Implemented | `src/modularcua/host/agent.py`; owns request, parsing, dispatch, history, accounting, completion |
| Agent-S / Prime executor independence | Implemented in current runner | `src/modularcua/environments/osworld_v2/runner.py`; no Agent-S imports or seed staging; Prime is a studied reference only |
| Frozen Qwen3.8 configuration | Configured and live service verified | `configs/core_v0.yaml`; revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`; endpoint remained live after the run stopped |
| Actual OSWorld guest interaction | Demonstrated partially on Task001 | Interrupted run includes fresh Docker guest, task setup, screenshots and 24 IPython calls. It was not scored. |
| Multimodal screenshot request | Demonstrated on the partial run | Initial user message contains text and `image_url`; original screenshot artifact and request are in the run journal. |
| Persistent IPython state | Local fixture tests and live kernel preflight | `host/kernel.py`; this is an `InteractiveShell` over OSWorld's `/execute` bridge, not Prime's Jupyter/ZeroMQ kernel protocol. |
| Capability registry | Implemented as executable guest helpers and metadata | `host/capabilities.py`; Python remains unrestricted in the guest, so this is not a sandbox or enforcement boundary. |
| Append-only session journal | Implemented | `host/journal.py`; interrupted run has aligned request/response/tool/screenshot events. A terminal interruption record was appended. |
| P0 has no active EGC | Demonstrated by configuration and run events | Run manifest sets EGC OFF; no EGC events appear in the P0 journal. |
| Earlier P0 Task001 result | Forensic-only: 0.00 partial / binary false, source digest `8d00680f…` | `experiments/modularcua/p0_resume_20261105/p0-task001-20261105T104819Z/official_result.json` |
| Frozen P0 Task001 result | Measured: 1.00 partial / binary true, source digest `b7c82dff…` | `/media/vlilab/DATA1/OSWorld-V2/experiments/modularcua/p0_frozen_20261105T133222Z/p0-task001-20261105T133245Z/official_result.json` |
| P0 Task003 | Completed under source snapshot `2c013ebe…`; 0.00 partial / binary false, 87 model turns / 88 IPython calls | `experiments/modularcua/p0_resume_20261105/p0-task003-20261105T122840Z/official_result.json` |
| P0 Tasks 013/014/061 | Not yet scored under the corrected GUI source | New single-snapshot five-task suite pending freeze/launch. |
| Disposable GUI execution diagnostic | Model-driven Calendar round-trip and text-editor keyboard/scroll effects independently observed | `reports/GUI_EXECUTION_ROOT_CAUSE.md`; raw events/screenshots under `experiments/modularcua/gui_execution_20261105T*/` |
| Six-module active EGC P1 | Not implemented/verified as active | Existing `egc/runtime.py` describes itself as observe-only; the actor loop does not inject its outputs into continuation or enforce its finish decisions. |
| Official P1 results | Not measured | No P1 episodes from this comparison. |

## Local checks

Command: `PYTHONPATH=ModularCUA/src:$PWD python -m pytest ModularCUA/tests -q`

Result on 2026-11-05: **30 passed** after adding coordinate transformation, screenshot capability journaling, and action/result linkage tests. `compileall` passed. These local tests do not establish five-task OSWorld performance, Prime protocol parity, or active EGC behavior. A separate real GUI integration run passed actual mouse, typing, hotkey, scroll, screenshot, and persistence checks; the final suite still needs official per-task evaluation.

## Historical status reconciliation

Older text in `README.md` and legacy reports described Agent-S prompt/seed staging and a completed ModularCUA Core Task001 score. Those records refer to earlier, different conditions. The current independent P0 runner removes that dependency. Do not use earlier scores as P0/P1 results or as evidence of the current runner's official performance.

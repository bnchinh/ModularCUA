# ModularCUA

ModularCUA is an independent, research-oriented computer-use agent harness built to run OSWorld-v2.1 tasks with a frozen Qwen model. It owns its model adapter, prompt construction, model-to-IPython loop, persistent guest kernel bridge, event journal, action accounting, and OSWorld runner. Prime Agent was a design reference; the current runner does not delegate its control loop to Prime or Agent-S.

This repository is a research prototype. Its Core V0 path has been exercised in real OSWorld environments, but the implementation is not a drop-in general-purpose OSWorld runner. It supports a reviewed subset of task IDs and depends on the matching OSWorld-v2.1 checkout, assets, VM image, and a configured OpenAI-compatible model endpoint.

## What is included

- **Core runtime** — independent agent loop, model adapter, prompt builder, budget controller, context compaction, session journal, capability registry, and persistent guest IPython bridge under `src/modularcua/`.
- **OSWorld-v2.1 adapter** — task setup, environment launch, run manifest, event collection, and official post-run evaluator call under `src/modularcua/environments/osworld_v2/`.
- **EGC prototype** — evidence/requirement prompts, schemas, runtime, and ledger under `src/modularcua/egc/`, `egc/`, and `skills/`.
- **Configurations and prompt** — examples under `configs/` and the native IPython system prompt under `prompts/`.
- **Tests and utilities** — local test suite and episode audit/diagnosis scripts under `tests/` and `scripts/`.
- **OSWorld integration patch** — the small set of required host/guest bridge changes is in `integration/osworld_v2_modularcua.patch` in this repository. It excludes evaluator/scoring changes.
- **Research notes** — architecture, upstream mapping, implementation status, limitations, and P1 results.

This repository intentionally excludes VM images, model weights, credentials, Docker volumes, raw task trajectories, and Python virtual environments. The full P1 task report is included as a separate document for result provenance.

## Architecture

```text
OSWorld task + screenshot
        ↓
OpenAI-compatible model adapter
        ↓
ModularCUA agent loop ─── append-only event journal + artifact hashes
        ↓
one model-facing IPython tool
        ↓
persistent IPython kernel inside the OSWorld guest
        ↓
tool result / screenshot → next model turn or finish → official evaluator
```

Core V0 runs with research modules disabled. P1 enables the current EGC runtime and records auxiliary analysis, evidence, and verifier outputs. **The current EGC path is observe-only:** its outputs are not injected into Actor context and it does not execute repairs or gate completion. Therefore the current P1 label does not mean that an intervention or recovery was delivered. See `ARCHITECTURE.md`, `IMPLEMENTATION_STATUS.md`, and `reports/known_limitations.md` for exact status and historical differences.

## Requirements

1. A compatible OSWorld-v2.1 checkout at the expected repository root. The runner imports OSWorld modules and official task classes from the parent repository.
2. The reviewed task assets at the pinned asset revision, plus the expected VM/QEMU image and Docker environment.
3. Python 3.11 or newer and `uv` for the ModularCUA dependencies.
4. A running OpenAI-compatible inference endpoint that serves the selected model. Endpoint, model name, and sampling settings belong in a local config file; do not commit API credentials.

This repository contains source and lockfiles, not benchmark assets or infrastructure. Follow the parent OSWorld repository's own setup instructions before attempting a live run.

The commands below assume this repository is checked out as `ModularCUA/` at the OSWorld-v2.1 repository root. If you use a different directory name, replace `ModularCUA` in the commands accordingly.

For a clean checkout matching this project's OSWorld base revision, review and check the integration patch from the repository root before applying it:

```bash
git apply --check ModularCUA/integration/osworld_v2_modularcua.patch
git apply ModularCUA/integration/osworld_v2_modularcua.patch
```

Do not apply it twice. If the working tree already contains the same bridge changes, `git apply --check` is expected to report conflicts because the patch is already present.

## Setup

From the OSWorld-v2.1 repository root:

```bash
uv sync --project ModularCUA --locked
cp ModularCUA/configs/core_v0.yaml ModularCUA/configs/local.yaml
```

Edit `ModularCUA/configs/local.yaml` for your local model endpoint, model identifier/revision, and VM image path. The checked-in `core_v0.yaml` uses `http://localhost:8000/v1` as an example endpoint. Supply any real API key through the configured environment variable:

```bash
export OPENAI_API_KEY="your-local-endpoint-key"
```

For a local endpoint that does not require a key, use the endpoint’s documented placeholder value (often `EMPTY`). Keep real keys out of YAML, shell history, logs, and source control.

## Run one task

Core V0, Task001:

```bash
PYTHONPATH="ModularCUA/src:$PWD" \
python ModularCUA/src/modularcua/environments/osworld_v2/runner.py \
  --config ModularCUA/configs/local.yaml \
  --task-id 001 --stage p0 \
  --output "$PWD/experiments/modularcua/manual/p0-task001"
```

P1 / EGC-observation mode uses the same native Actor loop with the EGC runtime enabled:

```bash
PYTHONPATH="ModularCUA/src:$PWD" \
python ModularCUA/src/modularcua/environments/osworld_v2/runner.py \
  --config ModularCUA/configs/egc_observe_only.yaml \
  --task-id 001 --stage p1 \
  --output "$PWD/experiments/modularcua/manual/p1-task001"
```

Use a fresh output directory for each run. Confirm the task is in the runner's reviewed supported-task set and that its exact pinned assets are available. The five-task helper script is:

```bash
bash ModularCUA/scripts/run_p0_five_tasks.sh \
  "$PWD/experiments/modularcua/manual/p0-five-task-suite"
```

It starts a sequential official P0 suite for Tasks `001, 003, 013, 014, 061`; use it only when all required infrastructure is available and no other run is using the same VM/service resources.

## Example: inspect and interact with the guest desktop

The Actor's registered `ipython` tool executes Python in the persistent OSWorld guest kernel. For example, the Actor may inspect the screen and then use the returned screenshot to decide what to do:

```python
import pyautogui
from IPython.display import display

screen = pyautogui.screenshot()
display(screen)  # The runtime attaches image output to the next model context.
```

A later tool call can perform an interaction and capture the resulting screen:

```python
import pyautogui
import time
from IPython.display import display

pyautogui.click(640, 420)  # Screenshot pixel coordinates; do not rescale them.
time.sleep(0.5)
display(pyautogui.screenshot())
```

These are examples of guest-kernel code issued through the model-facing IPython tool. For an official run, use the CLI above: it creates the OSWorld environment, loads the benchmark instruction, starts the guest kernel, journals events, and invokes the official evaluator.

## Tests and diagnostics

Run the local tests from the OSWorld-v2.1 repository root:

```bash
PYTHONPATH="ModularCUA/src:$PWD" \
python -m pytest ModularCUA/tests -q
```

These tests check code-level behavior; they do not verify current model availability, all OSWorld task assets, or official benchmark performance. Useful diagnostics:

```bash
python ModularCUA/scripts/audit_episode.py --help
python ModularCUA/scripts/diagnose_gui_execution.py --help
```

## Result interpretation

- A run is officially measured only when its `official_result.json` reports `status=MEASURED` and includes both `partial_score` and `binary_success`.
- Infrastructure failures, interruptions, and missing evaluator records are **NOT MEASURED**, not score zero.
- `DONE` text, controller/verifier output, and visible screenshots are not substitutes for the official evaluator.
- Logs distinguish model turns, IPython calls, instrumented PyAutoGUI actions, screenshots, and GUI state effects. These counters are not interchangeable.
- Historical P0/P1 results in `reports/` refer to different snapshots/configurations. The P0/P1 five-task comparison is explicitly marked as an exploratory single-run comparison; the report explains that the EGC feedback path was not demonstrated end to end. The bundled all-task report keeps separate P1 variants and excludes unscored attempts from score aggregates.

## Upstream and licensing

ModularCUA is MIT licensed; see `LICENSE`. Prime Agent was used as a source reference for architecture and behavior, not as a delegated execution runtime. `PRIME_COMPONENT_MAPPING.md` records the mapping and fidelity gaps. Third-party packages and OSWorld components retain their own licenses. The integration patch is provided for the corresponding OSWorld checkout and does not change official evaluator code.




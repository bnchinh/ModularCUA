# ModularCUA

**ModularCUA** is a research harness for evaluating computer-use agents on OSWorld-v2.1. It provides an independent Python control loop, an OpenAI-compatible model adapter, a persistent guest IPython bridge, event journaling, and an OSWorld task runner.

This repository is an experimental research prototype. The Core V0 path has been exercised in OSWorld, but support is limited to a reviewed subset of tasks and requires the matching OSWorld checkout, benchmark assets, VM image, Docker environment, and a configured inference endpoint.

## Relationship to Prime Agent

Prime Agent informed the architecture, especially the use of a persistent IPython environment. ModularCUA implements its own Python control loop and OSWorld guest bridge; it does not import Prime Agent or delegate task execution to it. The design reference is pinned to [Prime Agent commit a9b5d88](https://github.com/PrimeIntellect-ai/prime-agent/tree/a9b5d88b50db50860088772a408e867f8071b507), including its [IPython tool](https://github.com/PrimeIntellect-ai/prime-agent/blob/a9b5d88b50db50860088772a408e867f8071b507/packages/coding-agent/src/core/tools/ipython.ts). [PRIME_COMPONENT_MAPPING.md](PRIME_COMPONENT_MAPPING.md) documents the component mapping and implementation differences.

## Architecture

```text
OSWorld task and screenshot
        |
OpenAI-compatible model adapter
        |
ModularCUA agent loop -- event journal and artifact hashes
        |
model-facing IPython tool
        |
persistent IPython kernel in the OSWorld guest
        |
tool result and screenshot -> next model turn or finish -> official evaluator
```

Core V0 runs without research modules. EGC/P1 is observe-only by default. An opt-in experimental pre-finish gate can request evidence and block unresolved finishes, but it has not been validated live, does not use an independent task-specific verifier, and does not execute repairs. See [ARCHITECTURE.md](ARCHITECTURE.md), [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), and [the EGC audit](reports/P1_EGC_MODULE_AUDIT.md) for evidence and limitations.

## Repository contents

- `src/modularcua/` - agent loop, model adapter, guest kernel bridge, capability helpers, event journal, OSWorld runner, and EGC runtime.
- `configs/`, `prompts/`, and `egc/` - example configurations, system prompt, EGC prompts, schemas, and skills.
- `integration/` - OSWorld host/guest bridge patch. It does not modify the official evaluator.
- `tests/` and `scripts/` - local tests and episode audit/diagnostic utilities.
- `reports/` - selected experiment results, audits, and known limitations.

VM images, model weights, credentials, Docker volumes, raw episode trajectories, and Python virtual environments are not included.

## Requirements

1. An OSWorld-v2.1 checkout at the compatible base revision. The runner imports its task classes and environment modules from the parent repository.
2. The required benchmark assets, VM/QEMU image, and Docker environment.
3. Python 3.11 or newer and `uv`.
4. An OpenAI-compatible inference endpoint serving the configured model.

## Setup

The commands below assume this repository is checked out in a directory named `ModularCUA/` at the OSWorld-v2.1 repository root. Use the parent OSWorld repository's setup instructions for benchmark assets and infrastructure.

Review and check the integration patch before applying it:

```bash
git apply --check ModularCUA/integration/osworld_v2_modularcua.patch
git apply ModularCUA/integration/osworld_v2_modularcua.patch
```

Do not apply the patch twice. If the bridge changes are already present, the check may report conflicts.

Install dependencies and create a local configuration:

```bash
uv sync --project ModularCUA --locked
cp ModularCUA/configs/core_v0.yaml ModularCUA/configs/local.yaml
```

Set the endpoint, model, and VM image path in `ModularCUA/configs/local.yaml`. Keep credentials outside source control and provide them through the configured environment variable, for example:

```bash
export OPENAI_API_KEY='your-local-endpoint-key'
```

Use the endpoint's documented placeholder value (often `EMPTY`) when authentication is not required.

## Run a task

From the OSWorld-v2.1 repository root, run Core V0 Task001 with a fresh output directory:

```bash
PYTHONPATH="ModularCUA/src:$PWD" \
python ModularCUA/src/modularcua/environments/osworld_v2/runner.py \
  --config ModularCUA/configs/local.yaml \
  --task-id 001 --stage p0 \
  --output "$PWD/experiments/modularcua/manual/p0-task001"
```

An EGC observation-only run uses `--config ModularCUA/configs/egc_observe_only.yaml --task-id 001 --stage p1`. Do not interpret that condition as active verification or recovery; review the audit before drawing conclusions.

## Evaluation and diagnostics

A run counts as officially measured only when `official_result.json` reports `status=MEASURED` and includes both `partial_score` and `binary_success`. Infrastructure failures, interruptions, and missing evaluator records are not score-zero results. Model claims, screenshots, and verifier output do not replace the official evaluator.

Run the local tests from the OSWorld-v2.1 repository root:

```bash
PYTHONPATH="ModularCUA/src:$PWD" \
python -m pytest ModularCUA/tests -q
```

These tests cover local code behavior; they do not establish benchmark performance or validate every task asset and model endpoint. Useful diagnostics:

```bash
python ModularCUA/scripts/audit_episode.py --help
python ModularCUA/scripts/diagnose_gui_execution.py --help
```

Historical results in `reports/` come from different source snapshots and configurations. Consult their per-run notes before comparing scores.

## License and attribution

ModularCUA is licensed under the MIT License; see [LICENSE](LICENSE). Prime Agent is cited as an architectural reference at the pinned commit above. No Prime Agent or Agent-S runtime code is imported or bundled by the current P0 runner. Third-party packages and OSWorld components remain subject to their own licenses.

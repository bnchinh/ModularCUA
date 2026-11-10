# SKILL.md integration: design and evaluation plan

Updated 2026-11-10. The runtime is implemented as an opt-in research feature; effectiveness and operational reliability have not been measured yet.

## Runtime behavior

ModularCUA follows the Agent Skills folder convention: each skill is a directory containing `SKILL.md`, with YAML frontmatter for `name` and `description`. The name must match the folder and use a lowercase hyphenated slug. Optional `metadata.modularcua.requires-tools` declares host tools needed by the skill. `allowed-tools` is preserved as metadata for inspection, but is not an authorization grant.

For Actor-facing skills, the runner discovers configured directories and puts only skill names and descriptions in the initial model context. The model calls `activate_skill` to load a relevant body and may call `read_skill_resource` for UTF-8 text under that active skill's `references/` or `assets/`. The loader bounds individual and per-run character counts, enforces root containment, rejects duplicate/invalid skills, and never exposes bundled executable scripts through the resource tool. Skills are task guidance and do not change policy, user intent, or the tools granted by the host. The current IPython host tool is powerful and executes in the guest with guest-user permissions; this feature is not a sandbox.

EGC skills are separately opt-in. The bundled `egc/skills/` instructions are bound to corresponding EGC module prompts by a static module-to-skill map; their name/hash and prompt hash are recorded with module invocation provenance. This mode does not put those skills in the Actor catalog.

## Existing experiment configurations

- `configs/core_v0.yaml`: Actor skill runtime disabled.
- `configs/skills_experiment.yaml`: Actor discovery and activation enabled.
- `configs/egc_observe_only.yaml`: EGC observe-only without SKILL.md prompt binding.
- `configs/egc_skillmd_experiment.yaml`: EGC observe-only with per-module SKILL.md binding.

Actor skills and EGC bindings are independent interventions. If both are enabled in a future combined config, label and analyze it as a separate condition.

## Evaluation protocol

1. Validate discovery and routing on a small pilot using a pre-written task-to-skill expectation map. Check rejected malformed metadata, duplicate names, path traversal/symlink attempts, unavailable required tools, activation limits, and resource limits before relying on benchmark results.
2. Compare skill-off and skill-on runs on the same task set. Freeze the source revision, config except for the skill flag, model revision, generation settings, environment/assets, step and time budgets, and task instructions. Use multiple runs per task and randomize condition order where practical.
3. Report only official outcomes from `official_result.json` with `status=MEASURED`. Keep infrastructure errors and interruptions visible as unmeasured rows; never treat them as score zero.
4. Report partial score and binary success by task and overall, uncertainty across repeated runs, skill activation precision/recall against the predeclared routing map, activation/rejection counts, loaded instruction/resource characters, latency/token cost where available, and failure categories.
5. Inspect event provenance for which skill version was activated, what resources were read, and whether the skill was actually used before interpreting outcome differences.

Summarize run folders with:

```bash
python ModularCUA/scripts/evaluate_skill_runs.py experiments/modularcua --expected-skills expected-skills.json --output skill-evaluation.md
```

The optional JSON file maps three-digit task IDs to expected skill-name arrays, for example `{"001": ["osworld-observation-checklist"]}`. The script provides descriptive summaries, not causal estimates. Skill-use/outcome correlation alone does not prove a skill caused a score change.

## Next production backlog

After this integration receives a benchmark pilot, harden the tool boundary, isolate execution, define review/versioning for third-party skills, add richer policy enforcement, and evaluate adversarial or conflicting skill content. These items are intentionally downstream of making SKILL.md discovery and use measurable.

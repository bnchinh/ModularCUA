#!/usr/bin/env python3
"""Summarize SKILL.md use and official outcomes from ModularCUA run folders.

This is descriptive run analysis, not a causal estimate. For matched comparisons,
keep task, model/revision, seed, source/config hashes, and budgets aligned.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _skill_usage(run_dir: Path, manifest: dict[str, Any]) -> tuple[set[str], set[str]]:
    actor_names = set(manifest.get("skills", {}).get("active", []))
    egc_names: set[str] = set()
    for filename in ("module_runtime_metrics.json",):
        metrics = _read_json(run_dir / filename) or {}
        for binding in metrics.get("skill_instruction_bindings", []):
            if binding.get("skill_name"):
                egc_names.add(binding["skill_name"])
    events = run_dir / "events.jsonl"
    if events.is_file():
        try:
            for line in events.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("event_type") in {"skill_activated", "skill_resource_read"}:
                    if event.get("skill_name"):
                        actor_names.add(event["skill_name"])
                if event.get("event_type") == "egc_run_finalized":
                    for binding in event.get("skill_instruction_bindings", []):
                        if binding.get("skill_name"):
                            egc_names.add(binding["skill_name"])
        except (OSError, json.JSONDecodeError):
            pass
    return actor_names, egc_names


def collect_runs(root: Path) -> list[dict[str, Any]]:
    rows = []
    for manifest_path in sorted(root.rglob("run_manifest.json")):
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        result = _read_json(manifest_path.parent / "official_result.json") or {}
        measured = result.get("status") == "MEASURED"
        rows.append({
            "run": manifest_path.parent.name,
            "condition": manifest.get("condition", manifest.get("configured_condition", "unknown")),
            "task": str(manifest.get("task_id", result.get("task_id", ""))).zfill(3),
            "measured": measured,
            "score": result.get("partial_score") if measured else None,
            "success": result.get("binary_success") if measured else None,
            "actor_skills": None,
            "egc_skills": None,
            "skill_metrics": manifest.get("skills", {}).get("metrics", {}),
            "manifest": manifest,
        })
        rows[-1]["actor_skills"], rows[-1]["egc_skills"] = _skill_usage(manifest_path.parent, manifest)
    return rows


def render(rows: list[dict[str, Any]], expected: dict[str, list[str]] | None = None) -> str:
    measured = [row for row in rows if row["measured"]]
    scores = [row["score"] for row in measured if isinstance(row["score"], (int, float))]
    successes = [row["success"] for row in measured if isinstance(row["success"], bool)]
    lines = [
        "# SKILL.md run evaluation",
        "",
        f"Runs found: {len(rows)}; officially measured: {len(measured)}.",
        (f"Mean partial score: {sum(scores) / len(scores):.3f}." if scores else "Mean partial score: unavailable."),
        (f"Binary success rate: {sum(successes) / len(successes):.1%} ({sum(successes)}/{len(successes)})."
         if successes else "Binary success rate: unavailable."),
        "",
        "## Per-run record",
        "",
        "| Run | Condition | Task | Official score | Binary success | Actor skills | EGC skill bindings | Activations | Resource chars |",
        "|---|---|---:|---:|---:|---|---|---:|---:|",
    ]
    for row in rows:
        score = f"{row['score']:.3f}" if isinstance(row["score"], (int, float)) else "not measured"
        success = str(row["success"]) if row["success"] is not None else "—"
        actor_names = ", ".join(sorted(row["actor_skills"])) or "none observed"
        egc_names = ", ".join(sorted(row["egc_skills"])) or "none observed"
        metrics = row["skill_metrics"]
        activations = metrics.get("activations", "—")
        resource_chars = metrics.get("resource_characters_loaded", "—")
        lines.append(f"| {row['run']} | {row['condition']} | {row['task']} | {score} | {success} | {actor_names} | {egc_names} | {activations} | {resource_chars} |")
    if expected is not None:
        tp = fp = fn = 0
        for row in measured:
            gold = set(expected.get(row["task"], []))
            predicted = row["actor_skills"]
            tp += len(gold & predicted)
            fp += len(predicted - gold)
            fn += len(gold - predicted)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        lines += ["", "## Expected skill routing", "",
                  f"Micro precision: {precision:.3f} ({tp}/{tp + fp}); micro recall: {recall:.3f} ({tp}/{tp + fn}).",
                  "The expected task-to-skill mapping is supplied by the researcher; review disagreements manually."]
    lines += ["", "## Interpretation", "",
              "These summaries are descriptive. They do not establish that skill use caused an outcome change. "
              "For an on/off estimate, use matched task sets and multiple runs, freeze source/config/model revision, "
              "generation settings and budgets, and report uncertainty, invalid runs, activation/resource costs, "
              "and the official evaluator result. Actor skill activations and EGC module bindings are reported separately.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path, help="Root directory containing run folders")
    parser.add_argument("--expected-skills", type=Path,
                        help="Optional JSON mapping task IDs to expected skill name arrays")
    parser.add_argument("--output", type=Path, help="Write Markdown report here instead of stdout")
    args = parser.parse_args()
    expected = json.loads(args.expected_skills.read_text(encoding="utf-8")) if args.expected_skills else None
    report = render(collect_runs(args.runs), expected)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()

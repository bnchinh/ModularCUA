from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


def build_turn_audit(run_root: Path) -> Path:
    """Post-hoc table sourced only from immutable live events; never calls a model."""
    events_path = run_root / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    by_turn: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        turn = event.get("model_turn_id")
        if turn is not None:
            by_turn[int(turn)].append(event)
    fields = ["episode_id", "model_turn_id", "model_response_event_id", "reasoning_pointer",
              "actual_tool_calls", "skill_invocations", "actual_observations", "tool_errors",
              "observable_next_decision", "egc_modules_triggered", "egc_verdict_refs",
              "recovery_recommendation", "advisory_reached_actor", "screenshot_evidence_refs",
              "elapsed_seconds", "source_events"]
    path = run_root / "turn_audit.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("# POST-HOC ANALYSIS; generated solely from the immutable live events.jsonl; not model-generated.\n")
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for turn in sorted(by_turn):
            rows = by_turn[turn]
            responses = [e for e in rows if e.get("event_type") == "model_response"]
            response = responses[-1] if responses else {}
            raw = response.get("response", {})
            reasoning = raw.get("reasoning") or raw.get("analysis") or raw.get("thinking")
            calls = [e for e in rows if e.get("event_type") == "tool_call"]
            results = [e for e in rows if e.get("event_type") == "tool_result"]
            errors = [e for e in rows if e.get("event_type") in {"model_error", "tool_call_rejected"}]
            modules = [e for e in rows if e.get("event_type") == "egc_module_triggered"]
            verdicts = [e for e in rows if e.get("event_type") == "egc_verdict_recorded"]
            recoveries = [e for e in rows if e.get("event_type") == "egc_recovery_proposed"]
            screenshots = [e for e in rows if e.get("event_type") == "screenshot"]
            next_response = next((e for e in events if e.get("event_type") == "model_response"
                                  and e.get("model_turn_id") == turn + 1), None)
            elapsed = max((float(e.get("timestamp", 0)) for e in rows), default=0) - min(
                (float(e.get("timestamp", 0)) for e in rows), default=0)
            writer.writerow({
                "episode_id": run_root.name,
                "model_turn_id": turn,
                "model_response_event_id": response.get("event_id", "MISSING"),
                "reasoning_pointer": (f"events.jsonl#{response.get('event_id')}:response.reasoning" if reasoning else "REASONING_NOT_AVAILABLE"),
                "actual_tool_calls": json.dumps([{"event_id": e.get("event_id"), "tool_call_id": e.get("tool_call_id"),
                                                  "name": e.get("tool_name"), "args_sha256": _sha_json(e.get("arguments", {}))}
                                                 for e in calls], ensure_ascii=False),
                "skill_invocations": "SKILL_INVOCATION_NOT_OBSERVED",
                "actual_observations": json.dumps([e.get("event_id") for e in screenshots], ensure_ascii=False),
                "tool_errors": json.dumps([e.get("event_id") for e in errors], ensure_ascii=False),
                "observable_next_decision": next_response.get("event_id", "NOT_RECORDED") if next_response else "NOT_RECORDED",
                "egc_modules_triggered": json.dumps([e.get("module_name") for e in modules], ensure_ascii=False),
                "egc_verdict_refs": json.dumps([e.get("event_id") for e in verdicts], ensure_ascii=False),
                "recovery_recommendation": json.dumps([e.get("decision") for e in recoveries], ensure_ascii=False),
                "advisory_reached_actor": "false",
                "screenshot_evidence_refs": json.dumps([e.get("evidence") for e in screenshots], ensure_ascii=False),
                "elapsed_seconds": f"{elapsed:.6f}",
                "source_events": json.dumps([e.get("event_id") for e in rows], ensure_ascii=False),
            })
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, 0o600)
    return path


def _sha_json(value: Any) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def write_live_reports(run_root: Path, summary: dict[str, Any]) -> None:
    events = [json.loads(line) for line in (run_root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    calls = [e for e in events if e.get("event_type") == "egc_module_response"]
    validates = [e for e in events if e.get("event_type") == "egc_module_validation"]
    accepted = {e.get("module_call_id"): e for e in validates if e.get("accepted")}
    module_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "accepted": 0, "rejected": 0, "errors": 0})
    for event in calls:
        module_counts[event.get("module_name", "unknown")]["calls"] += 1
        module_counts[event.get("module_name", "unknown")]["accepted"] += int(event.get("module_call_id") in accepted)
        module_counts[event.get("module_name", "unknown")]["rejected"] += int(event.get("module_call_id") not in accepted)
    for event in events:
        if event.get("event_type") == "egc_module_error":
            module_counts[event.get("module_name", "unknown")]["errors"] += 1
    build_turn_audit(run_root)
    task_id = str(summary.get("task_id"))
    report = run_root / f"EGC_TASK{task_id}_LIVE.md"
    report.write_text(
        f"# EGC Live Task {task_id}\n\n"
        f"- Status: `{summary.get('status')}`\n"
        f"- Official OSWorld-v2.1 Partial Score: `{summary.get('partial_score')}`\n"
        f"- Official binary success: `{summary.get('binary_success')}`\n"
        f"- Actor model turns / IPython calls: `{summary.get('model_turns')}` / `{summary.get('ipython_tool_calls')}`\n"
        f"- Actor input/output tokens: `{summary.get('input_tokens')}` / `{summary.get('output_tokens')}`\n"
        f"- Auxiliary module responses: `{len(calls)}`; each live input/output is under `module_inputs/`, `module_outputs/` and in `events.jsonl`.\n"
        f"- Actor feedback injection: `0` (observe-only). EGC repair actions executed: `0`.\n\n"
        "## Module response accounting\n\n"
        "| Module | Calls | Accepted | Rejected | Errors |\n|---|---:|---:|---:|---:|\n" +
        "".join(f"| {name} | {m['calls']} | {m['accepted']} | {m['rejected']} | {m['errors']} |\n"
               for name, m in sorted(module_counts.items())) +
        "\nAll module decisions are contemporaneous outputs or deterministic runtime records."
        " This report is post-hoc and contains no reconstructed model responses.\n",
        encoding="utf-8")
    os.chmod(report, 0o600)


from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def redact(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace("osworld-public-evaluation", "[REDACTED]")
    text = re.sub(r"(?i)(password(?:\s+is)?\s*[:=]?\s+)[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return text


def summarize(value: Any, limit: int = 700) -> str:
    if isinstance(value, list):
        pieces = []
        for part in value:
            if isinstance(part, dict) and part.get("type") == "text":
                pieces.append(str(part.get("text", "")))
            elif isinstance(part, dict) and part.get("type") in {"image_url", "image"}:
                pieces.append("[image attachment]")
            else:
                pieces.append(json.dumps(part, ensure_ascii=False, default=str))
        text = " | ".join(pieces)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value or "")
    return redact(text)[:limit]


def run(event_path: Path, output_path: Path) -> None:
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line]
    requests: dict[int, dict] = {}
    responses: dict[int, dict] = {}
    calls: dict[int, list[dict]] = defaultdict(list)
    results: dict[tuple[int, str], dict] = {}
    screenshots: dict[int, list[dict]] = defaultdict(list)
    compactions: dict[int, dict] = {}
    for event in events:
        kind = event.get("event_type")
        turn = event.get("model_turn_id")
        if kind == "model_request": requests[int(turn)] = event
        elif kind == "model_response": responses[int(turn)] = event
        elif kind == "tool_call": calls[int(turn)].append(event)
        elif kind == "tool_result": results[(int(turn), event.get("tool_call_id"))] = event
        elif kind == "screenshot" and turn is not None: screenshots[int(turn)].append(event)
        elif kind == "context_compaction": compactions[int(turn)] = event

    columns = [
        "turn", "request_event_id", "request_timestamp_utc", "request_message_count",
        "request_roles", "request_image_content_blocks", "request_characters_estimate",
        "response_event_id", "response_request_id", "response_latency_seconds", "response_finish_reason",
        "assistant_visible_content", "provider_reasoning_field_recorded",
        "tool_call_event_ids", "tool_call_ids", "tool_names", "generated_python_code",
        "tool_result_event_ids", "tool_result_summaries", "tool_error_count",
        "after_cell_screenshot_event_ids", "after_cell_screenshot_artifact_ids",
        "context_compaction_event_id", "source_events_jsonl",
    ]
    rows = []
    for turn in sorted(set(requests) | set(responses) | set(calls)):
        req, resp = requests.get(turn, {}), responses.get(turn, {})
        message_list = req.get("messages", [])
        roles = [message.get("role", "?") for message in message_list]
        image_blocks = 0
        chars = 0
        for message in message_list:
            content = message.get("content", "")
            if isinstance(content, list):
                for block in content:
                    image_blocks += int(isinstance(block, dict) and
                                        (block.get("type") in {"image_url", "image"} or
                                         "image_url" in block or "image" in block))
            chars += len(json.dumps(content, ensure_ascii=False, default=str))
        calls_for_turn = calls.get(turn, [])
        response = resp.get("response", {})
        response_calls = response.get("tool_calls") or []
        code_by_id = {}
        for tool_call in response_calls:
            call_id = tool_call.get("id")
            function = tool_call.get("function") or {}
            if function.get("name") == "ipython":
                try:
                    code_by_id[call_id] = json.loads(function.get("arguments") or "{}").get("code", "")
                except Exception:
                    code_by_id[call_id] = function.get("arguments", "")
        result_events = [results.get((turn, call.get("tool_call_id")), {}) for call in calls_for_turn]
        shots = screenshots.get(turn, [])
        rows.append({
            "turn": turn,
            "request_event_id": req.get("event_id"),
            "request_timestamp_utc": req.get("timestamp_utc"),
            "request_message_count": len(message_list),
            "request_roles": " > ".join(roles),
            "request_image_content_blocks": image_blocks,
            "request_characters_estimate": chars,
            "response_event_id": resp.get("event_id"),
            "response_request_id": resp.get("request_id"),
            "response_latency_seconds": resp.get("latency_seconds"),
            "response_finish_reason": resp.get("finish_reason"),
            "assistant_visible_content": redact(str(response.get("content") or "")),
            "provider_reasoning_field_recorded": bool(response.get("reasoning")),
            "tool_call_event_ids": "|".join(call.get("event_id", "") for call in calls_for_turn),
            "tool_call_ids": "|".join(call.get("tool_call_id", "") for call in calls_for_turn),
            "tool_names": "|".join(call.get("tool_name", "") for call in calls_for_turn),
            "generated_python_code": redact("\n--- NEXT TOOL CALL ---\n".join(
                code_by_id.get(call.get("tool_call_id"), "") for call in calls_for_turn)),
            "tool_result_event_ids": "|".join(result.get("event_id", "") for result in result_events),
            "tool_result_summaries": "\n--- NEXT RESULT ---\n".join(
                summarize(result.get("content"), 700) for result in result_events),
            "tool_error_count": sum(bool(result.get("is_error")) for result in result_events),
            "after_cell_screenshot_event_ids": "|".join(
                shot.get("event_id", "") for shot in shots if shot.get("phase") == "after_ipython_cell"),
            "after_cell_screenshot_artifact_ids": "|".join(
                shot.get("evidence", {}).get("artifact_id", "") for shot in shots
                if shot.get("phase") == "after_ipython_cell"),
            "context_compaction_event_id": compactions.get(turn, {}).get("event_id"),
            "source_events_jsonl": str(event_path),
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("event_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    run(args.event_path, args.output_path)

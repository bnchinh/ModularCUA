from __future__ import annotations

from typing import Any


IPYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "ipython",
        "description": "Execute Python and %%bash cells in one persistent IPython kernel. Variables, imports and working state persist between calls.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "IPython cell source"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}


def system_prompt(seed_instructions: str, runtime_addendum: str) -> str:
    return (seed_instructions.rstrip() + "\n\n" + runtime_addendum.strip()).strip()


def initial_messages(system: str, instruction: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instruction},
    ]


def append_assistant_and_results(messages: list[dict[str, Any]], assistant: dict[str, Any],
                                 results: list[dict[str, Any]]) -> None:
    messages.append({k: v for k, v in assistant.items() if not k.startswith("_")})
    for call, result in zip(assistant.get("tool_calls", []), results, strict=True):
        messages.append({
            "role": "tool", "tool_call_id": call["id"],
            "content": result.get("content", ""),
        })

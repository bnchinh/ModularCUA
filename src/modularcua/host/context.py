from __future__ import annotations

import json
from typing import Any

from modularcua.host.modules import EventBus


def compact_messages(messages: list[dict[str, Any]], *, keep_recent: int,
                     instruction: str, event_bus: EventBus) -> list[dict[str, Any]]:
    """Small deterministic compactor; kernel state and journal are separate and untouched."""
    event_bus.dispatch("before_compaction", {"message_count": len(messages)})
    if len(messages) <= keep_recent + 2:
        return messages
    system = messages[0]
    # The original task message may contain multimodal content parts. Keep that
    # exact message instead of matching it against the plain instruction string.
    task = next((m for m in messages[1:] if m.get("role") == "user" and
                 (m.get("content") == instruction or
                  (isinstance(m.get("content"), list) and any(
                      isinstance(part, dict) and part.get("type") == "text" and
                      part.get("text") == instruction for part in m["content"])))), None)
    start = max(2, len(messages) - keep_recent)
    # Never begin retained context with an orphan tool result. Include the
    # assistant tool-call message that owns it, even if that exceeds the cap.
    while start > 2 and messages[start].get("role") == "tool":
        start -= 1
    recent = messages[start:]
    history = messages[2:start]
    snippets = []
    prior_summaries = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Preserve prior compaction summaries across subsequent compactions.
        # Do not serialize multimodal payloads into the summary: the original
        # task message above retains its image parts verbatim.
        if role == "user":
            if isinstance(content, str) and content.startswith("Compacted prior interaction."):
                prior_summaries.append(content[:3000])
            continue
        if role == "assistant" and msg.get("tool_calls"):
            calls = [{"name": (tc.get("function") or {}).get("name"),
                      "arguments": (tc.get("function") or {}).get("arguments")}
                     for tc in msg["tool_calls"]]
            content = {"text": content, "tool_calls": calls}
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        if role == "assistant":
            snippets.append("assistant: " + content[:500])
        elif role == "tool":
            snippets.append("tool result: " + content[:700])
    summary = {
        "role": "user",
        "content": "Compacted prior interaction. Original task instruction remains immutable:\n"
                   + instruction + "\nPreviously retained summary (kernel state and full event journal persist):\n"
                   + (prior_summaries[-1] if prior_summaries else "(none)")
                   + "\nRecent events:\n" + "\n".join(snippets[-12:]),
    }
    return [system, task or {"role": "user", "content": instruction}, summary, *recent]

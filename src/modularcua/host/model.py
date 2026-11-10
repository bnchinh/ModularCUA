from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from openai import OpenAI


class OpenAICompatibleModel:
    """Thin provider adapter preserving Qwen/OpenAI-compatible response fields."""

    def __init__(self, *, endpoint: str, api_key: str, model: str,
                 timeout: float = 360, max_tokens: int = 32000,
                 temperature: float | None = None, top_p: float | None = None):
        self.client = OpenAI(base_url=endpoint, api_key=api_key, timeout=timeout,
                             max_retries=0)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
        }
        # Prime's pinned adapter omitted these fields unless explicitly set.
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        started = time.monotonic()
        response = self.client.chat.completions.create(**kwargs)
        latency = time.monotonic() - started
        choice = response.choices[0]
        raw = choice.message.model_dump(exclude_none=True)
        raw["_provider"] = {
            "request_id": getattr(response, "_request_id", None),
            "model": response.model,
            "usage": response.usage.model_dump() if response.usage else {},
            "finish_reason": choice.finish_reason,
            "latency_seconds": latency,
        }
        return raw

    def complete_aux(self, messages: list[dict[str, Any]], *, max_tokens: int) -> dict[str, Any]:
        """Auxiliary EGC inference, using the same frozen endpoint but no executable tools."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        started = time.monotonic()
        response = self.client.chat.completions.create(**kwargs)
        latency = time.monotonic() - started
        choice = response.choices[0]
        raw = choice.message.model_dump(exclude_none=True)
        raw["_provider"] = {
            "request_id": getattr(response, "_request_id", None),
            "model": response.model,
            "usage": response.usage.model_dump() if response.usage else {},
            "finish_reason": choice.finish_reason,
            "latency_seconds": latency,
        }
        return raw


def image_data_url(path: str | Path) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")

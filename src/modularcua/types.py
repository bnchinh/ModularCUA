from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ModelResult:
    assistant_message: dict[str, Any]
    text: str
    reasoning: str | None
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]
    request_id: str | None
    latency_seconds: float
    finish_reason: str | None


@dataclass
class ToolResult:
    tool_call_id: str
    content: Any
    is_error: bool = False
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


Verdict = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass
class RequirementContract:
    requirement_id: str
    instruction_evidence: str
    observable_property: str
    verification_method: str
    status: Verdict = "UNKNOWN"
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class LedgerEntry:
    requirement_id: str
    claimed_complete: bool = False
    operation_executed: bool = False
    operation_succeeded: bool = False
    environment_observed: bool = False
    independently_verified: bool = False
    status: Verdict = "UNKNOWN"
    evidence_refs: list[str] = field(default_factory=list)


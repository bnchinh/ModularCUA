from __future__ import annotations

import re
from typing import Any

from modularcua.host.modules import HookAction, Module
from modularcua.types import LedgerEntry, RequirementContract


class VerifiedExecutionModule(Module):
    """Minimal evidence ledger and one bounded before-finish audit."""

    name = "verified-execution-v1"
    subscriptions = {"task_start", "before_tool_call", "after_tool_call",
                     "artifact_updated", "before_finish", "task_end"}
    authorized_actions = {"continue_for_audit"}

    def __init__(self):
        self.contracts: list[RequirementContract] = []
        self.ledger: dict[str, LedgerEntry] = {}
        self.finish_audit_used = False
        self.operations: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []
        self.finish_claims: list[dict[str, str]] = []

    def on_event(self, event: str, payload: dict[str, Any]) -> list[HookAction]:
        if event == "task_start":
            instruction = payload["instruction"]
            clauses = [s.strip() for s in re.split(r"(?<=[.!?])\s+", instruction) if s.strip()]
            self.contracts = [RequirementContract(
                requirement_id=f"R{i:02d}", instruction_evidence=clause,
                observable_property=f"The task outcome satisfies: {clause}",
                verification_method="UNKNOWN until supported by independent runtime evidence",
            ) for i, clause in enumerate(clauses, 1)]
            self.ledger = {c.requirement_id: LedgerEntry(c.requirement_id) for c in self.contracts}
        elif event == "before_tool_call":
            self.operations.append({"tool_call_id": payload["tool_call_id"],
                                    "arguments": payload.get("arguments", {}),
                                    "executed": False, "succeeded": False,
                                    "evidence_refs": []})
        elif event == "after_tool_call":
            operation = next((op for op in reversed(self.operations)
                              if op["tool_call_id"] == payload["tool_call_id"]), None)
            if operation is not None:
                operation["executed"] = True
                operation["succeeded"] = not payload.get("is_error", False)
        elif event == "artifact_updated":
            # The caller provides observed file metadata, never Actor narration.
            self.artifacts.extend(payload.get("changes", []))
        elif event == "before_finish" and not self.finish_audit_used:
            text = str(payload.get("text", ""))
            self.finish_claims.append({"text": text, "source": "actor final response; claim only"})
            for contract in self.contracts:
                if contract.instruction_evidence.casefold() in text.casefold():
                    self.ledger[contract.requirement_id].claimed_complete = True
            unknown = [c for c in self.contracts if c.status == "UNKNOWN"]
            if unknown:
                self.finish_audit_used = True
                audit = "Before finishing, inspect current application or saved-artifact evidence for these explicit requirements. Update only what is directly observable; leave anything unproven as unknown. Requirements:\n"
                audit += "\n".join(f"- {c.requirement_id}: {c.instruction_evidence}" for c in unknown)
                return [HookAction("continue_for_audit", {"message": audit}, self.name)]
        return []

    def export(self) -> dict[str, Any]:
        return {
            "contracts": [c.__dict__ for c in self.contracts],
            "ledger": [e.__dict__ for e in self.ledger.values()],
            "operations": self.operations,
            "artifacts": self.artifacts,
            "actor_finish_claims": self.finish_claims,
            "finish_audit_used": self.finish_audit_used,
            "limitations": ["No requirement PASS is assigned from Actor text.",
                            "This first ledger records operation/artifact evidence but does not yet independently parse the calendar artifact."],
        }

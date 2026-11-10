from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from modularcua.host.model import image_data_url


MODULES = {
    "requirement_contracts": "requirement_extractor.md",
    "contract_updater": "contract_updater.md",
    "visual_state_interpreter": "visual_state_interpreter.md",
    "self_verifier": "self_verifier.md",
    "recovery_planner": "recovery_planner.md",
    "history_summarizer": "history_summarizer.md",
}
ALL_MODULES = (*MODULES.keys(), "structured_state", "provenance_tracker", "termination")


class EGCJournal:
    """Append-only auxiliary-call timeline that shares the actor journal's sequence."""

    def __init__(self, root: Path, journal):
        self.root, self.journal = root, journal
        self.calls_path = root / "module_calls.jsonl"
        self._lock = threading.Lock()
        self.event_index: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def remember(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.event_index[event["event_id"]] = event

    def emit(self, event_type: str, *, module_name: str, module_call_id: str | None,
             model_turn_id: int | None, tool_call_id: str | None,
             triggering_event_id: str | None, as_of_event_seq: int | None = None,
             status: str, **fields: Any) -> dict[str, Any]:
        event = self.journal.append(
            event_type, module_name=module_name, module_call_id=module_call_id,
            model_turn_id=model_turn_id, tool_call_id=tool_call_id,
            triggering_event_id=triggering_event_id,
            as_of_event_seq=(self.journal.event_seq if as_of_event_seq is None else as_of_event_seq),
            status=status, **fields,
        )
        self.remember(event)
        with self._lock:
            fd = os.open(self.calls_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
        return event


class EGCModelAdapter:
    """Independent text/vision calls with the frozen actor's served model and no tools."""

    def __init__(self, model, *, max_tokens: int = 4096,
                 max_tokens_cap: int = 8192, max_retries: int = 1):
        self.model = model
        self.max_tokens = max_tokens
        self.max_tokens_cap = max(max_tokens, max_tokens_cap)
        self.max_retries = max(0, max_retries)

    def complete(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        token_limit = self.max_tokens
        attempts: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []
        for attempt_index in range(self.max_retries + 1):
            raw = self.model.complete_aux(messages, max_tokens=token_limit,
                                          disable_thinking=True)
            provider = raw.get("_provider", {})
            usage = provider.get("usage", {}) or {}
            content = raw.get("content") or ""
            attempts.append({
                "attempt": attempt_index + 1,
                "max_tokens": token_limit,
                "finish_reason": provider.get("finish_reason"),
                "usage": usage,
                "latency_seconds": provider.get("latency_seconds"),
                "content_sha256": hashlib.sha256(str(content).encode()).hexdigest(),
            })
            responses.append(raw)
            truncated = provider.get("finish_reason") in {"length", "max_tokens"}
            if not truncated or attempt_index >= self.max_retries or token_limit >= self.max_tokens_cap:
                break
            token_limit = min(self.max_tokens_cap, token_limit * 2)

        final = responses[-1]
        final_provider = dict(final.get("_provider", {}))
        aggregate_usage = dict(final_provider.get("usage", {}) or {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens"):
            values = [int((item.get("_provider", {}).get("usage", {}) or {}).get(key, 0) or 0)
                      for item in responses]
            if any(values):
                aggregate_usage[key] = sum(values)
        final_provider["usage"] = aggregate_usage
        final_provider["latency_seconds"] = sum(
            float(item.get("_provider", {}).get("latency_seconds", 0) or 0)
            for item in responses)
        final_provider["aux_attempts"] = attempts
        final["_provider"] = final_provider
        final["_aux_attempts"] = attempts
        return final


class EGCRuntime:
    """Observe-only evidence modules; no return value is connected to the Actor loop."""

    def __init__(self, root: Path, journal, model, config: dict[str, Any]):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.inputs_dir = root / "module_inputs"
        self.outputs_dir = root / "module_outputs"
        self.prompts_dir = root / "prompts"
        for path in (self.inputs_dir, self.outputs_dir, self.prompts_dir):
            path.mkdir(exist_ok=True)
        self.journal = journal
        self.timeline = EGCJournal(root, journal)
        self.model = EGCModelAdapter(
            model,
            max_tokens=int(config.get("max_aux_tokens", 4096)),
            max_tokens_cap=int(config.get("max_aux_tokens_cap", 8192)),
            max_retries=int(config.get("max_aux_retries", 1)),
        )
        self.config = config
        self.actor_feedback_enabled = bool(config.get("actor_feedback_enabled", False))
        self.max_feedback_rounds = max(0, int(config.get("max_feedback_rounds", 2)))
        self.feedback_rounds = 0
        self.execution_mode = ("BOUNDED_FEEDBACK_EXPERIMENTAL" if self.actor_feedback_enabled
                               else "OBSERVE_ONLY")
        self.enabled = config.get("modules", {name: True for name in ALL_MODULES})
        self.evidence: list[dict[str, Any]] = []
        self.contract_versions: list[dict[str, Any]] = []
        self.state: dict[str, dict[str, Any]] = {}
        self.verdicts: list[dict[str, Any]] = []
        self.requirement_status: dict[str, str] = {}
        self.provenance: dict[str, Any] = {"nodes": [], "edges": [], "unknown_edges": []}
        self.current_turn: int | None = None
        self.last_trigger: dict[str, Any] = {}
        self.screenshot_count = 0
        self.last_screenshot_hash: str | None = None
        self.recent_action_hashes: list[tuple[str, str | None, str, str]] = []
        self.consecutive_repeat_count = 0
        self.recovery_called_for_hash: str | None = None
        self.pending_action: tuple[str, dict[str, Any], dict[str, Any], str] | None = None
        self.initial_screenshot: tuple[dict[str, Any], bytes] | None = None
        self.metrics: dict[str, Any] = {
            "model_calls": {}, "model_latency_seconds": {}, "input_tokens": {},
            "output_tokens": {}, "deterministic_events": {}, "module_errors": 0,
        }
        self.actor_request_hashes: list[dict[str, Any]] = []
        self.metrics["actor_feedback_deliveries"] = 0

    @staticmethod
    def _sha(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def _artifact(self, data: bytes, suffix: str, mime: str) -> dict[str, Any]:
        digest = self._sha(data)
        path = self.artifacts / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return {"artifact_id": digest, "sha256": digest, "path": str(path),
                "size_bytes": len(data), "mime_type": mime}

    def _record_evidence(self, event: dict[str, Any], *, text: str = "",
                         artifacts: list[dict[str, Any]] | None = None,
                         source_type: str = "ACTOR_EVENT") -> dict[str, Any]:
        ref = {"event_id": event["event_id"], "event_seq": event["event_seq"],
               "event_type": event["event_type"], "source_type": source_type,
               "text": text, "artifacts": artifacts or []}
        self.evidence.append(ref)
        return ref

    def deterministic(self, module_name: str, trigger: dict[str, Any], operation: str,
                      payload: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
        if not self.enabled.get(module_name, True):
            return self.timeline.emit(
                "egc_module_skipped", module_name=module_name, module_call_id=None,
                model_turn_id=trigger.get("model_turn_id", self.current_turn),
                tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
                status="DISABLED", reason="module disabled in run configuration",
            )
        self.metrics["deterministic_events"][module_name] = self.metrics["deterministic_events"].get(module_name, 0) + 1
        call_id = str(uuid.uuid4())
        trigger_id = trigger.get("event_id")
        # Persist the exact deterministic module input before recording the call.
        # This lets the event stream reconstruct what was available at decision time.
        input_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":"), default=str).encode()
        input_path = self.inputs_dir / f"{call_id}.json"
        input_path.write_bytes(input_bytes)
        os.chmod(input_path, 0o600)
        input_sha = self._sha(input_bytes)
        event = self.timeline.emit(
            "egc_module_triggered", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger_id,
            status="TRIGGERED", trigger_reason=operation,
        )
        self.timeline.emit(
            "egc_module_input", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger_id,
            status="RECORDED", as_of_event_seq=event["event_seq"],
            input_snapshot_ref=str(input_path), input_payload_sha256=input_sha,
            evidence_refs=payload.get("evidence_refs", []),
        )
        result = {"operation": operation, "result": payload, "status": status}
        output_path = self.outputs_dir / f"{call_id}.json"
        output_doc = {"module_name": module_name, "module_call_id": call_id,
                      "triggering_event_id": trigger_id, "as_of_event_seq": event["event_seq"],
                      "deterministic": True, "input_ref": str(input_path),
                      "input_sha256": input_sha, "result": result}
        output_path.write_text(json.dumps(output_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.chmod(output_path, 0o600)
        return self.timeline.emit(
            "egc_state_committed" if module_name == "structured_state" else "egc_verdict_recorded",
            module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger_id,
            status=status, deterministic=True, result=result,
            input_snapshot_ref=str(input_path), input_payload_sha256=input_sha,
            output_ref=str(output_path),
        )

    def _message_and_snapshot(self, module_name: str, trigger: dict[str, Any],
                              user_payload: dict[str, Any],
                              image_refs: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        prompt_source = Path(__file__).resolve().parents[3] / "egc" / "prompts" / MODULES[module_name]
        prompt = prompt_source.read_text(encoding="utf-8")
        prompt_path = self.prompts_dir / MODULES[module_name]
        if not prompt_path.exists():
            prompt_path.write_text(prompt, encoding="utf-8")
        elif prompt_path.read_text(encoding="utf-8") != prompt:
            raise RuntimeError(f"Run-local prompt artifact changed unexpectedly: {prompt_path}")
        prompt_sha = self._sha(prompt.encode())
        user_text = json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        image_artifacts = []
        for ref in image_refs:
            path = Path(ref["path"])
            raw = path.read_bytes()
            data_url = image_data_url(path)
            content.append({"type": "image_url", "image_url": {"url": data_url}})
            image_artifacts.append({**ref, "mime_type": ref.get("mime_type", "image/png"),
                                    "transmitted_sha256": self._sha(raw)})
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": content}]
        payload_bytes = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode()
        payload_sha = self._sha(payload_bytes)
        module_call_id = str(uuid.uuid4())
        input_file = self.inputs_dir / f"{module_call_id}.json"
        input_file.write_bytes(payload_bytes)
        os.chmod(input_file, 0o600)
        trigger_event_id = trigger.get("event_id")
        allowed = {ref["event_id"] for ref in user_payload.get("evidence_refs", []) if ref.get("event_id")}
        cutoff = self.journal.event_seq
        snapshot = {
            "episode_id": self.journal.root.name, "module_call_id": module_call_id,
            "triggering_event_id": trigger_event_id,
            "triggering_model_turn_id": trigger.get("model_turn_id", self.current_turn),
            "evidence_cutoff_sequence": cutoff,
            "evidence_cutoff_event_id": trigger_event_id,
            "relevant_evidence_refs": user_payload.get("evidence_refs", []),
            "model_visible_messages": messages,
            "image_attachments": image_artifacts,
            "prompt_version": prompt_path.name, "prompt_sha256": prompt_sha,
            "input_payload_sha256": payload_sha,
            "model_name": self.model.model.model,
            "model_revision": self.config.get("model_revision"),
            "generation": {"max_tokens": self.model.max_tokens,
                           "max_tokens_cap": self.model.max_tokens_cap,
                           "max_retries": self.model.max_retries,
                           "enable_thinking": False,
                           "temperature": None, "top_p": None,
                           "tools": None, "tool_choice": None},
        }
        snapshot_path = self.inputs_dir / f"{module_call_id}.snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(snapshot_path, 0o600)
        return module_call_id, messages, {**snapshot, "input_file": str(input_file),
                                         "snapshot_file": str(snapshot_path),
                                         "allowed_event_ids": sorted(allowed), "cutoff": cutoff}

    def infer(self, module_name: str, trigger: dict[str, Any], user_payload: dict[str, Any],
              *, image_refs: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        if not self.enabled.get(module_name, True):
            self.timeline.emit("egc_module_skipped", module_name=module_name,
                               module_call_id=None, model_turn_id=self.current_turn,
                               tool_call_id=trigger.get("tool_call_id"),
                               triggering_event_id=trigger.get("event_id"),
                               status="DISABLED", reason="module disabled in run configuration")
            return None
        call_id, messages, snapshot = self._message_and_snapshot(
            module_name, trigger, user_payload, image_refs or [])
        trigger_event = self.timeline.emit(
            "egc_module_triggered", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
            status="TRIGGERED", trigger_reason=user_payload.get("trigger_reason", "event"),
            as_of_event_seq=snapshot["evidence_cutoff_sequence"],
        )
        input_event = self.timeline.emit(
            "egc_module_input", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
            status="RECORDED", as_of_event_seq=snapshot["evidence_cutoff_sequence"],
            input_snapshot_ref=snapshot["snapshot_file"],
            exact_messages_ref=snapshot["input_file"],
            prompt_sha256=snapshot["prompt_sha256"],
            input_payload_sha256=snapshot["input_payload_sha256"],
            evidence_refs=user_payload.get("evidence_refs", []),
            image_attachments=snapshot["image_attachments"],
        )
        request_event = self.timeline.emit(
            "egc_module_request", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
            status="DISPATCHED", as_of_event_seq=snapshot["evidence_cutoff_sequence"],
            request_event_id=input_event["event_id"], model_name=snapshot["model_name"],
            generation=snapshot["generation"], prompt_sha256=snapshot["prompt_sha256"],
            input_payload_sha256=snapshot["input_payload_sha256"],
        )
        started = time.monotonic()
        try:
            raw = self.model.complete(messages)
        except Exception as exc:
            self.metrics["module_errors"] += 1
            self.metrics["model_calls"][module_name] = self.metrics["model_calls"].get(module_name, 0) + 1
            self.metrics["model_latency_seconds"][module_name] = self.metrics["model_latency_seconds"].get(module_name, 0.0) + (time.monotonic() - started)
            self.timeline.emit(
                "egc_module_error", module_name=module_name, module_call_id=call_id,
                model_turn_id=trigger.get("model_turn_id", self.current_turn),
                tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
                status="ERROR", as_of_event_seq=snapshot["evidence_cutoff_sequence"],
                error=repr(exc), latency_seconds=time.monotonic() - started,
                raw_response="NOT_AVAILABLE_PROVIDER_ERROR",
            )
            return None
        provider = raw.pop("_provider", {})
        raw_text = raw.get("content") or ""
        parsed = None
        parse_error = None
        try:
            parsed = json.loads(raw_text)
        except Exception as exc:
            parse_error = repr(exc)
        citations = self._citations(parsed) if isinstance(parsed, dict) else []
        unknown_citations = [x for x in citations if x not in snapshot["allowed_event_ids"]]
        citation_valid = not unknown_citations
        schema_valid, schema_error = self._validate(module_name, parsed) if isinstance(parsed, dict) else (False, "response is not a JSON object")
        if isinstance(parsed, dict):
            grounding_valid, citation_error = self._validate_grounding(module_name, parsed, snapshot["allowed_event_ids"])
            quote_valid, quote_errors = self._validate_source_quotes(
                module_name, parsed, snapshot["relevant_evidence_refs"])
            grounding_valid = grounding_valid and quote_valid
            citation_error.extend(quote_errors)
            citation_valid = citation_valid and grounding_valid
            if citation_error:
                unknown_citations.extend(citation_error)
        needs_citation = isinstance(parsed, dict) and self._has_factual_content(module_name, parsed)
        if needs_citation and not citations:
            citation_valid = False
            unknown_citations = ["MISSING_REQUIRED_EVIDENCE_CITATION"]
        accepted = bool(schema_valid and citation_valid)
        output_doc = {
            "module_name": module_name, "module_call_id": call_id,
            "triggering_event_id": trigger.get("event_id"),
            "as_of_event_seq": snapshot["evidence_cutoff_sequence"],
            "raw_response": raw, "raw_text": raw_text, "parsed_output": parsed,
            "parse_error": parse_error, "schema_valid": schema_valid,
            "schema_error": schema_error, "citations": citations,
            "citation_valid": citation_valid, "unknown_citations": unknown_citations,
            "accepted": accepted, "provider": provider,
        }
        out_path = self.outputs_dir / f"{call_id}.json"
        out_path.write_text(json.dumps(output_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(out_path, 0o600)
        response_event = self.timeline.emit(
            "egc_module_response", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
            status="RECEIVED", as_of_event_seq=snapshot["evidence_cutoff_sequence"],
            output_ref=str(out_path), raw_response=raw, raw_text=raw_text,
            provider_request_id=provider.get("request_id"), usage=provider.get("usage", {}),
            latency_seconds=provider.get("latency_seconds", time.monotonic() - started),
            finish_reason=provider.get("finish_reason"),
        )
        validation_event = self.timeline.emit(
            "egc_module_validation", module_name=module_name, module_call_id=call_id,
            model_turn_id=trigger.get("model_turn_id", self.current_turn),
            tool_call_id=trigger.get("tool_call_id"), triggering_event_id=trigger.get("event_id"),
            status="ACCEPTED" if accepted else "REJECTED",
            as_of_event_seq=snapshot["evidence_cutoff_sequence"],
            raw_json_valid=parse_error is None, schema_valid=schema_valid,
            schema_error=schema_error, citation_valid=citation_valid,
            unknown_citations=unknown_citations, accepted=accepted,
            response_event_id=response_event["event_id"], output_ref=str(out_path),
        )
        self._cost(module_name, provider)
        if accepted:
            self._commit(module_name, parsed, trigger, validation_event)
        return {**output_doc, "validation_event_id": validation_event["event_id"]}

    @staticmethod
    def _citations(value: Any) -> list[str]:
        keys = {"evidence_ids", "source_event_ids", "source_event_id", "evidence_event_ids",
                "source_evidence_refs", "supporting_event_ids", "snapshot_event_id",
                "newly_observed_screenshot_event_id", "compaction_event_id"}
        found: list[str] = []
        def visit(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in keys:
                        if isinstance(v, str): found.append(v)
                        elif isinstance(v, list): found.extend(str(x) for x in v)
                    else: visit(v)
            elif isinstance(obj, list):
                for x in obj: visit(x)
        visit(value)
        return found

    @staticmethod
    def _validate(module_name: str, obj: dict[str, Any]) -> tuple[bool, str | None]:
        required = {
            "requirement_contracts": {"requirements", "source_event_ids", "unresolved_requirements", "missing_sources", "ambiguities"},
            "contract_updater": {"unchanged_requirement_ids", "newly_discovered_constraints", "revised_requirement_definitions", "source_evidence_refs", "unresolved_ambiguities", "contradictions"},
            "visual_state_interpreter": {"snapshot_event_id", "state_updates", "potentially_stale_facts", "contradictions", "missing_evidence"},
            "self_verifier": {"snapshot_event_id", "verdicts"},
            "recovery_planner": {"decision", "failure_type", "requirement_id", "supporting_event_ids", "suspected_cause", "cause_confidence", "repair_instruction", "preserve_requirements", "verification_plan", "reason"},
            "history_summarizer": {"summary", "source_event_ids"},
        }.get(module_name, set())
        missing = sorted(required - obj.keys())
        if missing:
            return False, "missing keys: " + ", ".join(missing)
        array_keys = {
            "requirement_contracts": ("requirements", "source_event_ids", "unresolved_requirements", "missing_sources", "ambiguities"),
            "contract_updater": ("unchanged_requirement_ids", "newly_discovered_constraints", "revised_requirement_definitions", "source_evidence_refs", "unresolved_ambiguities", "contradictions"),
            "visual_state_interpreter": ("state_updates", "potentially_stale_facts", "contradictions", "missing_evidence"),
            "self_verifier": ("verdicts",),
            "recovery_planner": ("supporting_event_ids", "preserve_requirements", "verification_plan"),
            "history_summarizer": ("source_event_ids",),
        }.get(module_name, ())
        if any(not isinstance(obj.get(key), list) for key in array_keys):
            return False, "one or more required array fields are not arrays"
        row_keys = {
            "requirement_contracts": ("requirements", {"requirement_id", "description", "source_quote", "source_event_ids", "constraint_type", "required_evidence", "verification_method", "status"}),
            "contract_updater": ("newly_discovered_constraints", {"requirement_id", "source_quote", "source_event_ids"}),
            "visual_state_interpreter": ("state_updates", {"fact_id", "entity", "property", "value", "source_type", "confidence", "evidence_ids", "environment_version", "freshness"}),
            "self_verifier": ("verdicts", {"requirement_id", "verdict", "confidence", "evidence_ids", "observed_property", "expected_property", "reason", "missing_evidence", "suggested_check"}),
        }.get(module_name)
        if row_keys:
            row_name, row_required = row_keys
            rows = obj.get(row_name, [])
            if any(not isinstance(row, dict) or not row_required <= row.keys() for row in rows):
                return False, f"invalid {row_name} item shape"
            if row_name in {"requirements", "verdicts"}:
                row_ids = [row.get("requirement_id") for row in rows]
                if any(not isinstance(requirement_id, str) or not requirement_id.strip()
                       for requirement_id in row_ids):
                    return False, f"invalid requirement_id in {row_name}"
                if len(row_ids) != len(set(row_ids)):
                    return False, f"duplicate requirement_id in {row_name}"
            citation_key = ("source_event_ids" if row_name in {
                                "requirements", "newly_discovered_constraints",
                                "revised_requirement_definitions"}
                            else "evidence_ids" if row_name == "verdicts" else None)
            if citation_key and any(
                    not isinstance(row.get(citation_key), list)
                    or any(not isinstance(event_id, str) for event_id in row[citation_key])
                    for row in rows):
                return False, f"invalid {citation_key} in {row_name}"
        if module_name == "contract_updater":
            for key in ("revised_requirement_definitions",):
                if any(not isinstance(row, dict) or not {"requirement_id", "source_quote", "source_event_ids"} <= row.keys()
                       for row in obj.get(key, [])):
                    return False, f"invalid {key} item shape"
        if module_name == "history_summarizer" and not isinstance(obj.get("summary"), dict):
            return False, "summary must be an object"
        if module_name == "self_verifier":
            for verdict in obj.get("verdicts", []):
                if verdict.get("verdict") not in {"PASS", "FAIL", "UNKNOWN"}:
                    return False, "invalid verdict enum"
        if module_name == "recovery_planner" and obj.get("decision") not in {"REPAIR", "ACQUIRE_EVIDENCE", "NO_REPAIR"}:
            return False, "invalid recovery decision"
        return True, None

    def _validate_grounding(self, module_name: str, obj: dict[str, Any], allowed: list[str]) -> tuple[bool, list[str]]:
        allow = set(allowed)
        errors = []
        if module_name in {"requirement_contracts", "contract_updater"}:
            rows = obj.get("requirements", []) if module_name == "requirement_contracts" else (
                obj.get("newly_discovered_constraints", []) + obj.get("revised_requirement_definitions", []))
            for row in rows:
                ids = row.get("source_event_ids", []) if isinstance(row, dict) else []
                if not ids or any(x not in allow for x in ids):
                    errors.append("UNGROUNDED_REQUIREMENT:" + str(row.get("requirement_id", "unknown")))
        elif module_name == "visual_state_interpreter":
            for row in obj.get("state_updates", []):
                ids = row.get("evidence_ids", []) if isinstance(row, dict) else []
                if not ids or any(x not in allow for x in ids):
                    errors.append("UNGROUNDED_STATE_FACT:" + str(row.get("fact_id", "unknown")))
        elif module_name == "self_verifier":
            known = {r.get("requirement_id") for version in self.contract_versions
                     for key in ("requirements", "revised_requirement_definitions", "newly_discovered_constraints")
                     for r in version.get(key, []) if isinstance(r, dict)}
            for row in obj.get("verdicts", []):
                if not isinstance(row, dict):
                    errors.append("INVALID_VERDICT_ROW")
                    continue
                ids = row.get("evidence_ids", [])
                if row.get("requirement_id") not in known:
                    errors.append("UNKNOWN_REQUIREMENT_ID:" + str(row.get("requirement_id")))
                if row.get("verdict") in {"PASS", "FAIL"} and (not ids or any(x not in allow for x in ids)):
                    errors.append("UNGROUNDED_VERDICT:" + str(row.get("requirement_id")))
        elif module_name == "recovery_planner":
            ids = obj.get("supporting_event_ids", [])
            if obj.get("decision") != "NO_REPAIR" and (not ids or any(x not in allow for x in ids)):
                errors.append("UNGROUNDED_RECOVERY_PROPOSAL")
        return not errors, errors

    @staticmethod
    def _validate_source_quotes(module_name: str, obj: dict[str, Any],
                                evidence_refs: list[dict[str, Any]]) -> tuple[bool, list[str]]:
        """Require extracted contract quotes to be exact spans of cited evidence."""
        row_keys = {
            "requirement_contracts": ("requirements", "source_event_ids"),
            "contract_updater": ("newly_discovered_constraints", "source_event_ids"),
        }.get(module_name)
        if row_keys is None:
            return True, []
        row_name, citation_key = row_keys
        by_event = {str(ref.get("event_id")): str(ref.get("text", ""))
                    for ref in evidence_refs if ref.get("event_id")}
        errors = []
        for index, row in enumerate(obj.get(row_name, [])):
            if not isinstance(row, dict):
                continue  # The schema validator reports the malformed row.
            quote = row.get("source_quote")
            source_ids = row.get(citation_key, [])
            if not isinstance(quote, str) or not quote.strip() or not isinstance(source_ids, list):
                errors.append(f"INVALID_SOURCE_QUOTE:{index}")
                continue
            if not any(quote in by_event.get(str(event_id), "") for event_id in source_ids):
                errors.append(f"SOURCE_QUOTE_NOT_EXACT_SPAN:{row.get('requirement_id', index)}")
        return not errors, errors

    def _cost(self, module_name: str, provider: dict[str, Any]) -> None:
        self.metrics["model_calls"][module_name] = self.metrics["model_calls"].get(module_name, 0) + 1
        self.metrics["model_latency_seconds"][module_name] = self.metrics["model_latency_seconds"].get(module_name, 0.0) + float(provider.get("latency_seconds") or 0.0)
        usage = provider.get("usage", {}) or {}
        self.metrics["input_tokens"][module_name] = self.metrics["input_tokens"].get(module_name, 0) + int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        self.metrics["output_tokens"][module_name] = self.metrics["output_tokens"].get(module_name, 0) + int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)

    def _commit(self, module_name: str, parsed: dict[str, Any], trigger: dict[str, Any],
                validation_event: dict[str, Any]) -> None:
        if module_name == "requirement_contracts":
            version = {"version": 1, "source_event_ids": parsed.get("source_event_ids", []),
                       "requirements": parsed.get("requirements", []),
                       "unresolved_requirements": parsed.get("unresolved_requirements", []),
                       "triggering_event_id": trigger.get("event_id"),
                       "validation_event_id": validation_event["event_id"]}
            self.contract_versions.append(version)
            self._write_projection("requirement_contract_versions.json", self.contract_versions)
            self.timeline.emit("egc_requirement_updated", module_name=module_name,
                               module_call_id=None, model_turn_id=self.current_turn,
                               tool_call_id=trigger.get("tool_call_id"),
                               triggering_event_id=trigger.get("event_id"), status="COMMITTED",
                               requirement_version=1, requirement_ids=[r.get("requirement_id") for r in version["requirements"]],
                               source_event_ids=version["source_event_ids"],
                               validation_event_id=validation_event["event_id"])
        elif module_name == "contract_updater":
            version_num = len(self.contract_versions) + 1
            previous = self.contract_versions[-1].get("requirements", []) if self.contract_versions else []
            merged = {r.get("requirement_id"): dict(r) for r in previous if isinstance(r, dict) and r.get("requirement_id")}
            for row in parsed.get("revised_requirement_definitions", []) + parsed.get("newly_discovered_constraints", []):
                if isinstance(row, dict) and row.get("requirement_id"):
                    merged[row["requirement_id"]] = dict(row)
            version = {"version": version_num, "requirements": list(merged.values()),
                       "update": parsed, **parsed,
                       "triggering_event_id": trigger.get("event_id"),
                       "validation_event_id": validation_event["event_id"]}
            self.contract_versions.append(version)
            self._write_projection("requirement_contract_versions.json", self.contract_versions)
            self.timeline.emit("egc_requirement_updated", module_name=module_name,
                               module_call_id=None, model_turn_id=self.current_turn,
                               tool_call_id=trigger.get("tool_call_id"),
                               triggering_event_id=trigger.get("event_id"), status="COMMITTED",
                               requirement_version=version_num,
                               source_event_ids=parsed.get("source_evidence_refs", []),
                               validation_event_id=validation_event["event_id"])
        elif module_name == "visual_state_interpreter":
            for item in parsed.get("state_updates", []):
                fact_id = item.get("fact_id") or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:16]
                claim_status = {"CLAIMED": "CLAIMED", "INFERRED": "INFERRED"}.get(
                    item.get("source_type"), "OBSERVED")
                self.state[fact_id] = {**item, "status": "UNKNOWN" if not item.get("evidence_ids") else claim_status,
                                       "committed_at_event_id": trigger.get("event_id")}
            self._write_projection("structured_state.json", self.state)
            self.timeline.emit("egc_state_committed", module_name="structured_state",
                               module_call_id=None, model_turn_id=self.current_turn,
                               tool_call_id=trigger.get("tool_call_id"),
                               triggering_event_id=trigger.get("event_id"), status="COMMITTED",
                               fact_ids=list(self.state), state_snapshot_ref=str(self.root / "structured_state.json"),
                               validation_event_id=validation_event["event_id"])
        elif module_name == "self_verifier":
            self.verdicts.extend(parsed.get("verdicts", []))
            for verdict in parsed.get("verdicts", []):
                if verdict.get("verdict") in {"PASS", "FAIL", "UNKNOWN"}:
                    self.requirement_status[verdict["requirement_id"]] = verdict["verdict"]
            self.timeline.emit("egc_verdict_recorded", module_name=module_name,
                               module_call_id=None, model_turn_id=self.current_turn,
                               tool_call_id=trigger.get("tool_call_id"),
                               triggering_event_id=trigger.get("event_id"), status="RECORDED",
                               verdicts=parsed.get("verdicts", []),
                               validation_event_id=validation_event["event_id"])
        elif module_name == "recovery_planner":
            self.timeline.emit("egc_recovery_proposed", module_name=module_name,
                               module_call_id=None, model_turn_id=self.current_turn,
                               tool_call_id=trigger.get("tool_call_id"),
                               triggering_event_id=trigger.get("event_id"), status="PROPOSED",
                               decision=parsed.get("decision"), recovery=parsed,
                               delivered_to_actor=False,
                               validation_event_id=validation_event["event_id"])
        elif module_name == "history_summarizer":
            self._write_projection("history_summaries.jsonl", parsed, append=True)

    def _write_projection(self, filename: str, value: Any, *, append: bool = False) -> None:
        path = self.root / filename
        if append:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(value, ensure_ascii=False) + "\n")
                f.flush(); os.fsync(f.fileno())
        else:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)

    def task_start(self, event: dict[str, Any], instruction: str) -> None:
        self.journal.execution_mode = self.execution_mode
        self.current_turn = None
        ref = self._record_evidence(event, text=instruction, source_type="TASK_INSTRUCTION")
        self.deterministic("structured_state", event, "initialize", {
            "evidence_refs": [ref], "persistent_facts": [], "unknown_requirements": "unextracted",
        })
        self.provenance["nodes"].append({"node_id": event["event_id"], "type": "task_instruction",
                                          "source_event_id": event["event_id"]})
        self.infer("requirement_contracts", event, {
            "trigger_reason": "task_start", "task_instruction": instruction,
            "evidence_refs": [ref],
            "forbidden_information": "No later document content, evaluator, benchmark solution, or prior task trajectory.",
        })
        if self.initial_screenshot:
            screenshot_event, screenshot_bytes = self.initial_screenshot
            self.observed_screenshot(screenshot_event, screenshot_bytes, phase="initial")

    def set_initial_screenshot(self, event: dict[str, Any] | None, image_bytes: bytes | None) -> None:
        if event is not None and image_bytes:
            self.initial_screenshot = (event, image_bytes)

    def observed_screenshot(self, event: dict[str, Any], image_bytes: bytes, *, phase: str,
                            model_turn_id: int | None = None, tool_call_id: str | None = None) -> None:
        ref = self._artifact(image_bytes, ".png", "image/png")
        self.screenshot_count += 1
        evidence = self._record_evidence(event, text=f"{phase} screenshot captured by DesktopEnv controller.",
                                         artifacts=[ref], source_type="SCREENSHOT_OBSERVATION")
        self.provenance["nodes"].append({"node_id": ref["artifact_id"], "type": "environment_screenshot",
                                          "source_event_id": event["event_id"], "sha256": ref["sha256"],
                                          "phase": phase})
        self.provenance["edges"].append({"from": event["event_id"], "to": ref["artifact_id"],
                                          "type": "OBSERVED_AT", "source_event_ids": [event["event_id"]]})
        self.deterministic("provenance_tracker", event, "record_screenshot_observation", {
            "evidence_refs": [evidence], "artifact": ref, "phase": phase,
            "model_turn_id": model_turn_id, "tool_call_id": tool_call_id,
        })
        for fact_id, fact in list(self.state.items()):
            if fact.get("source_type") == "TRANSIENT_GUI":
                self.state[fact_id] = {**fact, "freshness": "STALE"}
        self._write_projection("structured_state.json", self.state)
        self.last_screenshot_hash = ref["sha256"]
        if self.pending_action:
            code_hash, call_event, result_event, code = self.pending_action
            if self.recent_action_hashes and self.recent_action_hashes[-1][0] == code_hash and self.recent_action_hashes[-1][1] == ref["sha256"]:
                self.consecutive_repeat_count += 1
            else:
                self.consecutive_repeat_count = 1
            self.recent_action_hashes.append((code_hash, ref["sha256"], call_event["event_id"], result_event["event_id"]))
            threshold = int(self.config.get("recovery_repeat_threshold", 3))
            if self.consecutive_repeat_count >= threshold and self.recovery_called_for_hash != code_hash:
                code_ref = next((e for e in self.evidence if e["event_id"] == call_event["event_id"]), None)
                result_ref = next((e for e in self.evidence if e["event_id"] == result_event["event_id"]), None)
                refs = [x for x in (code_ref, result_ref, evidence) if x]
                self.infer("recovery_planner", event, {
                    "trigger_reason": "repeated_identical_executed_tool_code_and_byte_identical_screenshot",
                    "evidence_refs": refs, "executed_code_sha256": code_hash,
                    "repeat_count": self.consecutive_repeat_count,
                    "task_instruction": self.evidence[0]["text"],
                    "current_contracts": self.contract_versions[-1] if self.contract_versions else {},
                    "current_state": self.state, "mode": "OBSERVE_ONLY; do not send proposal to Actor.",
                }, image_refs=[ref])
                self.recovery_called_for_hash = code_hash
            self.pending_action = None
        interval = max(1, int(self.config.get("visual_state_every_n_screenshots", 3)))
        due = self.screenshot_count == 1 or self.screenshot_count % interval == 0 or phase.startswith("final")
        if due and self.contract_versions:
            self.infer("visual_state_interpreter", event, {
                "trigger_reason": "initial_or_scheduled_current_screenshot",
                "snapshot_event_id": event["event_id"], "task_instruction": self.evidence[0]["text"],
                "evidence_refs": [*self._refs_for_state(), evidence], "existing_state": self.state,
                "environment_version": event["event_id"],
            }, image_refs=[ref])
            self.infer("contract_updater", event, {
                "trigger_reason": "new_source_or_application_screenshot",
                "existing_contract_version": self.contract_versions[-1],
                "newly_observed_screenshot_event_id": event["event_id"],
                "task_instruction": self.evidence[0]["text"],
                "evidence_refs": [*self._refs_for_contracts(), evidence],
                "rule": "Add source facts only if they are legible in this screenshot. Keep all other details unknown.",
            }, image_refs=[ref])
            self.infer("self_verifier", event, {
                "trigger_reason": "milestone_screenshot", "snapshot_event_id": event["event_id"],
                "task_instruction": self.evidence[0]["text"], "requirements": self.contract_versions[-1],
                "evidence_refs": [*self._refs_for_contracts(), *self._refs_for_state(), evidence],
            }, image_refs=[ref])

    def actor_model_request(self, event: dict[str, Any], messages: list[dict[str, Any]],
                            tools: list[dict[str, Any]]) -> None:
        """Hash the exact actor payload without modifying it or exposing it to EGC modules."""
        raw = json.dumps(messages, ensure_ascii=False, separators=(",", ":"), default=str).encode()
        tool_raw = json.dumps(tools, ensure_ascii=False, separators=(",", ":"), default=str).encode()
        record = {"model_turn_id": event.get("model_turn_id"),
                  "model_request_event_id": event["event_id"],
                  "payload_sha256": self._sha(raw), "message_count": len(messages),
                  "tool_schema_sha256": self._sha(tool_raw),
                  "execution_mode": self.execution_mode}
        self.actor_request_hashes.append(record)
        self.journal.append("egc_actor_request_observed", module_name="runtime",
                            module_call_id=None, model_turn_id=event.get("model_turn_id"),
                            tool_call_id=None, triggering_event_id=event["event_id"],
                            as_of_event_seq=event["event_seq"], status="OBSERVED",
                            actor_payload_sha256=record["payload_sha256"],
                            actor_tool_schema_sha256=record["tool_schema_sha256"],
                            message_count=len(messages), actor_context_modified=False)

    def tool_result(self, call_event: dict[str, Any], result_event: dict[str, Any],
                    code: str, content: Any, artifacts: list[dict[str, Any]], *, is_error: bool,
                    model_turn_id: int, tool_call_id: str) -> None:
        self.current_turn = model_turn_id
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        call_ref = self._record_evidence(call_event, text=code, source_type="EXECUTED_TOOL_CALL")
        result_ref = self._record_evidence(result_event, text=text, artifacts=artifacts,
                                           source_type="TOOL_RESULT")
        self.deterministic("provenance_tracker", result_event, "link_executed_operation",
                           {"evidence_refs": [call_ref, result_ref], "nodes_added": [
                               {"node_id": call_event["event_id"], "type": "tool_call"},
                               {"node_id": result_event["event_id"], "type": "tool_result"}],
                            "edges_added": [{"from": call_event["event_id"], "to": result_event["event_id"],
                                             "type": "EXECUTED_AS", "source_event_ids": [call_event["event_id"], result_event["event_id"]]}],
                            "opaque_side_effects": "PROVENANCE_UNKNOWN"})
        self.provenance["nodes"].extend([{"node_id": call_event["event_id"], "type": "tool_call"},
                                          {"node_id": result_event["event_id"], "type": "tool_result"}])
        self.provenance["edges"].append({"from": call_event["event_id"], "to": result_event["event_id"],
                                          "type": "EXECUTED_AS", "source_event_ids": [call_event["event_id"], result_event["event_id"]]})
        image_refs = []
        for artifact in artifacts:
            if str(artifact.get("media_type", artifact.get("mime_type", ""))).startswith("image/") and Path(artifact.get("path", "")).is_file():
                copied = self._artifact(Path(artifact["path"]).read_bytes(), Path(artifact["path"]).suffix or ".png",
                                        artifact.get("media_type", artifact.get("mime_type", "image/png")))
                image_refs.append(copied)
                self.provenance["nodes"].append({"node_id": copied["artifact_id"], "type": "observed_screenshot",
                                                  "source_event_id": result_event["event_id"], "sha256": copied["sha256"],
                                                  "actor_attach_source_path": artifact.get("source_path")})
                self.provenance["edges"].append({"from": result_event["event_id"], "to": copied["artifact_id"],
                                                  "type": "OBSERVED_AT", "source_event_ids": [result_event["event_id"]]})
                if artifact.get("source_path"):
                    self.provenance["nodes"].append({"node_id": "source-path:" + str(artifact["source_path"]),
                                                      "type": "guest_image_source_path",
                                                      "path": artifact["source_path"],
                                                      "content_hash": "NOT_AVAILABLE_FOR_UNTRANSFORMED_SOURCE"})
                    self.provenance["edges"].append({"from": "source-path:" + str(artifact["source_path"]),
                                                      "to": copied["artifact_id"], "type": "ATTACHED_AS",
                                                      "source_event_ids": [result_event["event_id"]],
                                                      "note": "Attached image bytes are content-addressed; the original guest file hash was not read."})
        self._write_projection("provenance_graph.json", self.provenance)
        if is_error:
            self.consecutive_repeat_count = 0
            return
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        self.pending_action = (code_hash, call_event, result_event, code)

    def _process_screenshot(self, trigger: dict[str, Any], image_ref: dict[str, Any],
                            turn: int, tool_call_id: str, *refs: dict[str, Any],
                            code: str = "") -> None:
        ev_refs = [self._record_evidence(trigger, text="Screenshot bytes from actual tool output.",
                                         artifacts=[image_ref], source_type="SCREENSHOT_OBSERVATION")]
        self.deterministic("structured_state", trigger, "advance_observation_version", {
            "evidence_refs": ev_refs, "new_environment_version": trigger["event_id"],
            "invalidated_transient_facts": [fact_id for fact_id, fact in self.state.items()
                                             if fact.get("source_type") == "TRANSIENT_GUI"],
        })
        for fact_id, fact in list(self.state.items()):
            if fact.get("source_type") == "TRANSIENT_GUI":
                self.state[fact_id] = {**fact, "freshness": "STALE"}
        self._write_projection("structured_state.json", self.state)
        interval = max(1, int(self.config.get("visual_state_every_n_screenshots", 3)))
        should_interpret = self.screenshot_count == 1 or self.screenshot_count % interval == 0
        if should_interpret and self.enabled.get("structured_state", True):
            state_out = self.infer("visual_state_interpreter", trigger, {
                "trigger_reason": "scheduled_fresh_screenshot", "snapshot_event_id": trigger["event_id"],
                "task_instruction": self.evidence[0]["text"], "evidence_refs": ev_refs,
                "existing_state": self.state, "environment_version": trigger["event_id"],
            }, image_refs=[image_ref])
            if state_out and state_out.get("accepted"):
                pass
        if self.enabled.get("contract_updater", True) and should_interpret and self.contract_versions:
            self.infer("contract_updater", trigger, {
                "trigger_reason": "new_screenshot_evidence_available",
                "existing_contract_version": self.contract_versions[-1],
                "newly_observed_screenshot_event_id": trigger["event_id"],
                "task_instruction": self.evidence[0]["text"], "evidence_refs": ev_refs,
                "rule": "Add source facts only if they are readable in this screenshot; otherwise leave them unresolved.",
            }, image_refs=[image_ref])
        if should_interpret and self.contract_versions:
            self.infer("self_verifier", trigger, {
                "trigger_reason": "selective_postcondition_check_on_new_visual_evidence",
                "snapshot_event_id": trigger["event_id"], "task_instruction": self.evidence[0]["text"],
                "requirements": self.contract_versions[-1], "evidence_refs": ev_refs,
                "current_state": self.state,
            }, image_refs=[image_ref])

    def history_compaction(self, event: dict[str, Any], messages_before: list[dict[str, Any]],
                           summary: str) -> None:
        evidence = self._history_evidence_refs(event)
        evidence.append(self._record_evidence(event, text="Actual pre-compaction model messages (bounded excerpt).",
                                              source_type="COMPACTION_BOUNDARY"))
        self.infer("history_summarizer", event, {
            "trigger_reason": "native_ModularCUA_compaction_fired",
            "task_instruction": self.evidence[0]["text"],
            "compaction_event_id": event["event_id"], "evidence_refs": evidence,
            "pre_compaction_messages": messages_before,
            "deterministic_native_summary": summary,
        })

    def artifact_updated(self, event: dict[str, Any], changes: list[dict[str, Any]], *,
                         model_turn_id: int, tool_call_id: str) -> None:
        ref = self._record_evidence(event, text=json.dumps(changes, ensure_ascii=False),
                                    source_type="GUEST_FILESYSTEM_METADATA_DIFF")
        nodes = []
        edges = []
        structural_checks = []
        for change in changes:
            path = str(change.get("path", ""))
            before, after = change.get("before"), change.get("after")
            output_id = (after or {}).get("sha256") or f"{path}:{(after or {}).get('mtime_ns')}:{(after or {}).get('size')}"
            nodes.append({"node_id": output_id, "type": "guest_file_version", "path": path,
                          "metadata": after, "source_event_id": event["event_id"]})
            edges.append({"from": tool_call_id, "to": output_id, "type": "MODIFIED_BY",
                          "source_event_ids": [event["event_id"]]})
            if before:
                edges.append({"from": (before or {}).get("sha256") or f"{path}:before",
                              "to": output_id, "type": "VERSIONED_AS",
                              "source_event_ids": [event["event_id"]]})
            if path.lower().endswith(".ics"):
                if isinstance(after, dict) and "icalendar_structurally_closed" in after:
                    ok = bool(after["icalendar_structurally_closed"])
                    structural_checks.append({"check": "iCalendar container and VEVENT block structure",
                                              "verdict": "PASS" if ok else "FAIL",
                                              "event_count": after.get("icalendar_vevent_count"),
                                              "artifact_sha256": after.get("sha256"),
                                              "evidence_ids": [event["event_id"]],
                                              "scope": "format_structure_only; not task-semantic correctness"})
                else:
                    structural_checks.append({"check": "iCalendar structure", "verdict": "UNKNOWN",
                                              "evidence_ids": [event["event_id"]],
                                              "scope": "file content was not available to deterministic parser"})
        self.provenance["nodes"].extend(nodes)
        self.provenance["edges"].extend(edges)
        self._write_projection("provenance_graph.json", self.provenance)
        self.deterministic("provenance_tracker", event, "link_observed_file_changes",
                           {"evidence_refs": [ref], "nodes_added": nodes, "edges_added": edges})
        for check in structural_checks:
            self.timeline.emit("egc_verdict_recorded", module_name="deterministic_artifact_verifier",
                               module_call_id=None, model_turn_id=model_turn_id,
                               tool_call_id=tool_call_id, triggering_event_id=event["event_id"],
                               status=check["verdict"], deterministic=True,
                               verdict=check["verdict"], scope=check["scope"],
                               structural_check=check, evidence_refs=[ref])
        if self.contract_versions and self.enabled.get("self_verifier", True):
            self.infer("self_verifier", event, {
                "trigger_reason": "artifact_created_or_updated",
                "snapshot_event_id": event["event_id"],
                "task_instruction": self.evidence[0]["text"],
                "requirements": self.contract_versions[-1], "evidence_refs": [ref],
                "artifact_metadata_changes": changes,
                "current_state": self.state,
            }, image_refs=self._latest_images())

    def before_finish(self, event: dict[str, Any], actor_text: str) -> dict[str, Any] | None:
        """Optionally request bounded evidence before allowing an Actor finish."""
        if not self.actor_feedback_enabled:
            return None
        claim_ref = self._record_evidence(event, text=actor_text, source_type="ACTOR_FINISH_CLAIM")
        contract = self.contract_versions[-1] if self.contract_versions else None
        requirements = contract.get("requirements", []) if isinstance(contract, dict) else []
        verification = None
        if requirements and self.enabled.get("self_verifier", True):
            for requirement in requirements:
                requirement_id = str(requirement.get("requirement_id", "UNKNOWN"))
                self.requirement_status[requirement_id] = "UNKNOWN"
            evidence_refs = [*self._refs_for_contracts(), *self._refs_for_state(),
                             *self._recent_evidence_refs(), claim_ref]
            verification = self.infer("self_verifier", event, {
                "trigger_reason": "pre_finish_bounded_gate",
                "snapshot_event_id": event["event_id"],
                "task_instruction": self.evidence[0]["text"] if self.evidence else "",
                "requirements": contract, "evidence_refs": evidence_refs,
                "current_state": self.state, "actor_final_claim": actor_text,
            }, image_refs=self._latest_images())

        unresolved = []
        if not requirements:
            unresolved.append({"requirement_id": "REQUIREMENT_CONTRACT",
                               "status": "UNKNOWN"})
        else:
            for requirement in requirements:
                requirement_id = str(requirement.get("requirement_id", "UNKNOWN"))
                status = self.requirement_status.get(requirement_id, "UNKNOWN")
                if status != "PASS":
                    unresolved.append({"requirement_id": requirement_id, "status": status})
        if not unresolved:
            self.timeline.emit("egc_termination_decision", module_name="termination",
                               module_call_id=str(uuid.uuid4()), model_turn_id=self.current_turn,
                               tool_call_id=None, triggering_event_id=event.get("event_id"),
                               status="MODEL_VERIFIER_PASS", decision="ALLOW_FINISH",
                               intervention_allowed=True, intervention_delivered=False,
                               verifier_validation_event_id=(verification or {}).get("validation_event_id"),
                               unresolved_requirement_ids=[])
            return None

        decision = ("REQUEST_EVIDENCE" if self.feedback_rounds < self.max_feedback_rounds
                    else "BLOCK_FINISH")
        if decision == "REQUEST_EVIDENCE":
            self.feedback_rounds += 1
            rows = ", ".join(f"{item['requirement_id']}={item['status']}" for item in unresolved)
            message = ("EGC pre-finish check is unresolved: " + rows + ". Obtain fresh, relevant UI or "
                       "artifact evidence. Address any FAIL result and gather evidence for UNKNOWN results; "
                       "then reassess the task. Do not claim a requirement is complete without evidence.")
            feedback_event = self.timeline.emit(
                "egc_actor_feedback_delivered", module_name="termination",
                module_call_id=str(uuid.uuid4()), model_turn_id=self.current_turn,
                tool_call_id=None, triggering_event_id=event.get("event_id"),
                status="DELIVERED", decision=decision,
                intervention_allowed=True, intervention_delivered=True,
                feedback_round=self.feedback_rounds, unresolved_requirements=unresolved,
                verifier_validation_event_id=(verification or {}).get("validation_event_id"),
                message=message,
            )
            self.metrics["actor_feedback_deliveries"] += 1
            return {"action": "FEEDBACK", "message": message,
                    "event_id": feedback_event["event_id"]}

        self.timeline.emit("egc_termination_decision", module_name="termination",
                           module_call_id=str(uuid.uuid4()), model_turn_id=self.current_turn,
                           tool_call_id=None, triggering_event_id=event.get("event_id"),
                           status="BLOCKED_UNVERIFIED", decision=decision,
                           intervention_allowed=True, intervention_delivered=False,
                           feedback_rounds=self.feedback_rounds,
                           unresolved_requirements=unresolved,
                           verifier_validation_event_id=(verification or {}).get("validation_event_id"))
        return {"action": "BLOCK", "unresolved_requirements": unresolved}

    def finish(self, event: dict[str, Any], actor_text: str) -> None:
        ref = self._record_evidence(event, text=actor_text, source_type="ACTOR_FINISH_CLAIM")
        if (not self.actor_feedback_enabled and self.contract_versions
                and self.enabled.get("self_verifier", True)):
            self.infer("self_verifier", event, {
                "trigger_reason": "actor_finish_request", "snapshot_event_id": event["event_id"],
                "task_instruction": self.evidence[0]["text"], "requirements": self.contract_versions[-1],
                "evidence_refs": [*self._refs_for_contracts(), *self._refs_for_state(), *self._recent_evidence_refs(), ref],
                "current_state": self.state, "actor_final_claim": actor_text,
            }, image_refs=self._latest_images())
        unresolved = [r for r in (self.contract_versions[-1].get("requirements", []) if self.contract_versions else [])
                      if self.requirement_status.get(r.get("requirement_id"), "UNKNOWN") != "PASS"]
        decision = "ALLOW_FINISH" if not unresolved else "REQUEST_EVIDENCE"
        if self.enabled.get("termination", True):
            event_out = self.timeline.emit(
                "egc_termination_decision", module_name="termination", module_call_id=str(uuid.uuid4()),
                model_turn_id=self.current_turn, tool_call_id=None,
                triggering_event_id=event["event_id"],
                status=("MODEL_VERIFIER_PASS" if self.actor_feedback_enabled and not unresolved
                        else "ADVISORY_ONLY"),
                decision=decision, intervention_allowed=self.actor_feedback_enabled,
                intervention_delivered=False,
                unresolved_requirement_ids=[r.get("requirement_id") for r in unresolved],
                unknown_requirement_count=len(unresolved), actor_finish_event_id=event["event_id"],
            )
            self._write_projection("termination_decision.json", event_out)
        else:
            self.timeline.emit("egc_module_skipped", module_name="termination", module_call_id=None,
                               model_turn_id=self.current_turn, tool_call_id=None,
                               triggering_event_id=event["event_id"], status="DISABLED",
                               reason="module disabled in run configuration")

    def _recent_evidence_refs(self, limit: int = 12) -> list[dict[str, Any]]:
        return [{k: ref.get(k) for k in ("event_id", "event_seq", "event_type", "source_type", "text", "artifacts")}
                for ref in self.evidence[-limit:]]

    def _refs_for_contracts(self) -> list[dict[str, Any]]:
        event_ids: set[str] = set()
        for version in self.contract_versions:
            for key in ("source_event_ids", "source_evidence_refs"):
                event_ids.update(str(x) for x in version.get(key, []) if isinstance(x, str))
            for key in ("requirements", "revised_requirement_definitions", "newly_discovered_constraints"):
                for item in version.get(key, []):
                    if isinstance(item, dict):
                        event_ids.update(str(x) for x in item.get("source_event_ids", []) if isinstance(x, str))
        return [dict(ref) for ref in self.evidence if ref.get("event_id") in event_ids]

    def _refs_for_state(self) -> list[dict[str, Any]]:
        event_ids = {str(event_id) for fact in self.state.values()
                     for event_id in fact.get("evidence_ids", []) if isinstance(event_id, str)}
        return [dict(ref) for ref in self.evidence if ref.get("event_id") in event_ids]

    def _history_evidence_refs(self, boundary: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            events = [json.loads(line) for line in self.journal.path.read_text(encoding="utf-8").splitlines()]
        except Exception:
            return []
        refs = []
        max_seq = int(boundary.get("event_seq", 0))
        for item in events:
            if int(item.get("event_seq", 0)) >= max_seq:
                continue
            if item.get("event_type") not in {"model_request", "model_response", "tool_call", "tool_result", "screenshot", "artifact_updated"}:
                continue
            if item.get("event_type") == "model_response":
                text = json.dumps(item.get("response", {}), ensure_ascii=False)
            elif item.get("event_type") == "tool_call":
                text = json.dumps(item.get("arguments", {}), ensure_ascii=False)
            elif item.get("event_type") == "tool_result":
                text = json.dumps(item.get("content", ""), ensure_ascii=False, default=str)
            else:
                text = ""
            artifacts = item.get("artifacts", [])
            if item.get("event_type") == "screenshot" and item.get("evidence"):
                artifacts = [item["evidence"]]
            refs.append({"event_id": item["event_id"], "event_seq": item["event_seq"],
                         "event_type": item["event_type"], "source_type": "PRE_COMPACTION_HISTORY",
                         "text": text, "artifacts": artifacts})
        return refs

    def _latest_images(self) -> list[dict[str, Any]]:
        for ref in reversed(self.evidence):
            for artifact in ref.get("artifacts", []):
                if artifact.get("mime_type", "").startswith("image/") and Path(artifact.get("path", "")).is_file():
                    return [artifact]
        return []

    def finalize(self, actor_summary: dict[str, Any]) -> None:
        triggered = {e.get("module_name") for e in self.timeline.events
                    if e.get("event_type") == "egc_module_triggered"}
        for name, enabled in self.enabled.items():
            if not enabled:
                continue
            if name not in triggered:
                self.timeline.emit("egc_module_skipped", module_name=name, module_call_id=None,
                                   model_turn_id=self.current_turn, tool_call_id=None,
                                   triggering_event_id=None, status="NOT_INVOKED",
                                   reason="No configured event trigger occurred before episode termination.")
        self._write_projection("verified_ledger.json", {
            "generated_from_live_events": True,
            "requirement_versions": self.contract_versions,
            "state": self.state,
            "verdicts": self.verdicts,
            "requirement_status": self.requirement_status,
            "actor_claims_are_not_verification": True,
            "limitations": ["No benchmark evaluator data entered EGC prompts.",
                            ("Bounded feedback was enabled experimentally; it does not execute repairs."
                             if self.actor_feedback_enabled else
                             "Observe-only outputs were never injected into the Actor.")],
        })
        self._write_projection("provenance_graph.json", self.provenance)
        self._write_projection("module_runtime_metrics.json", {
            **self.metrics, "execution_mode": self.execution_mode,
            "actor_summary": actor_summary,
            "egc_advisories_delivered": self.metrics["actor_feedback_deliveries"],
            "egc_repair_actions_executed": 0,
            "actor_request_hashes": self.actor_request_hashes,
        })
        self.journal.append("egc_run_finalized", module_name="runtime", module_call_id=None,
                            model_turn_id=self.current_turn, tool_call_id=None,
                            triggering_event_id=None, as_of_event_seq=self.journal.event_seq,
                            status="COMPLETED", execution_mode=self.execution_mode,
                            metrics=self.metrics,
                            actor_feedback_injected=self.metrics["actor_feedback_deliveries"] > 0)

    @staticmethod
    def _has_factual_content(module_name: str, parsed: dict[str, Any]) -> bool:
        if module_name == "requirement_contracts":
            return bool(parsed.get("requirements"))
        if module_name == "contract_updater":
            return bool(parsed.get("newly_discovered_constraints") or parsed.get("revised_requirement_definitions"))
        if module_name == "visual_state_interpreter":
            return bool(parsed.get("state_updates") or parsed.get("contradictions"))
        if module_name == "self_verifier":
            return any(v.get("verdict") in {"PASS", "FAIL"} for v in parsed.get("verdicts", []))
        if module_name == "recovery_planner":
            return parsed.get("decision") != "NO_REPAIR"
        if module_name == "history_summarizer":
            return bool(parsed.get("source_event_ids"))
        return False

from __future__ import annotations

import json
import base64
import io
import time
import uuid
from typing import Any, Callable

from PIL import Image

from modularcua.host.context import compact_messages
from modularcua.host.budget import BudgetController
from modularcua.host.journal import SessionJournal
from modularcua.host.modules import EventBus
from modularcua.host.prompt import IPYTHON_TOOL, initial_messages
from modularcua.types import ToolResult


RUNTIME_ADDENDUM = """## OSWorld IPython runtime\n\nYour only model-facing tool is a persistent IPython kernel. Use the guest `cua` capability registry for screenshot, mouse, keyboard, shell, file, and application operations. Guest Python state persists across calls and context compaction. Never assume that a requested operation succeeded; inspect its result.\n\nCoordinate contract: coordinates for both `cua` and direct `pyautogui` mouse actions are pixels in the most recently attached full-screen desktop screenshot. The runtime converts those screenshot coordinates to native guest pixels. Do not multiply coordinates by a scale factor or use native-screen coordinates. A cropped/zoomed image is for reading only; take and attach a fresh full-screen screenshot before any coordinate-based action. Every public PyAutoGUI action is journaled with requested screenshot coordinates and executed native coordinates."""


class AgentLoop:
    """Independent model -> IPython -> result control loop."""

    def __init__(self, model, kernel, journal: SessionJournal, *, max_steps: int = 150,
                 compact_after: int = 50, keep_recent: int = 12,
                 modules: EventBus | None = None,
                 after_tool_observer: Callable[[int, str], Any] | None = None,
                 artifact_probe: Callable[[str], dict[str, Any]] | None = None,
                 egc=None,
                 max_wall_seconds: float = 5400,
                 max_tool_output_chars: int = 30000):
        self.model, self.kernel, self.journal = model, kernel, journal
        self.max_steps, self.compact_after, self.keep_recent = max_steps, compact_after, keep_recent
        self.modules = modules or EventBus()
        self.after_tool_observer = after_tool_observer
        self.artifact_probe = artifact_probe
        self.egc = egc
        self.max_tool_output_chars = max_tool_output_chars
        self.budget = BudgetController(max_steps, max_wall_seconds)
        self.model_turns = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.pyautogui_action_attempts = 0
        self.pyautogui_actions_executed = 0

    def run(self, instruction: str, system: str, initial_screenshot: bytes | None = None) -> dict[str, Any]:
        messages = initial_messages(system, instruction)
        if initial_screenshot:
            image = Image.open(io.BytesIO(initial_screenshot)).convert("RGB")
            image.thumbnail((1200, 1200))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=82)
            messages[1]["content"] = [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}},
            ]
        module_payload = {"instruction": instruction}
        self.modules.dispatch("task_start", module_payload)
        start_event = self.journal.append("task_start", instruction=instruction)
        if self.egc:
            self.egc.task_start(start_event, instruction)
        for turn in range(1, self.max_steps + 1):
            stop_reason = self.budget.stop_reason(turn)
            if stop_reason:
                self.journal.append("budget_exhausted", model_turn_id=turn-1, reason=stop_reason)
                return {"status": stop_reason, "turns": turn-1, "tool_calls": self.tool_calls,
                        "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                        "messages": messages,
                        "pyautogui_action_attempts": self.pyautogui_action_attempts,
                        "pyautogui_actions_executed": self.pyautogui_actions_executed}
            self.model_turns = turn
            self.modules.dispatch("before_model_call", {"turn": turn, "messages": messages})
            request_event = self.journal.append("model_request", model_turn_id=turn, messages=messages,
                                                tools=[IPYTHON_TOOL], model=getattr(self.model, "model", None),
                                                generation={"max_tokens": getattr(self.model, "max_tokens", None),
                                                            "temperature": getattr(self.model, "temperature", None),
                                                            "top_p": getattr(self.model, "top_p", None)})
            if self.egc:
                self.egc.current_turn = turn
                self.egc.actor_model_request(request_event, messages, [IPYTHON_TOOL])
            started = time.monotonic()
            raw = None
            for attempt in range(2):
                try:
                    raw = self.model.complete(messages, [IPYTHON_TOOL])
                    break
                except Exception as exc:
                    self.journal.append("model_error", model_turn_id=turn, attempt=attempt+1,
                                        error=repr(exc), duration_seconds=time.monotonic()-started)
                    if attempt == 1:
                        return {"status": "model_error", "error": repr(exc), "turns": turn-1,
                                "tool_calls": self.tool_calls, "input_tokens": self.input_tokens,
                                "output_tokens": self.output_tokens, "messages": messages,
                                "pyautogui_action_attempts": self.pyautogui_action_attempts,
                                "pyautogui_actions_executed": self.pyautogui_actions_executed}
                    time.sleep(1)
            provider = raw.pop("_provider", {})
            usage = provider.get("usage", {}) or {}
            self.input_tokens += int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            self.output_tokens += int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
            tool_calls = raw.get("tool_calls") or []
            text = raw.get("content") or ""
            response_event = self.journal.append("model_response", model_turn_id=turn, response=raw,
                                                usage=provider.get("usage", {}), latency_seconds=provider.get("latency_seconds"),
                                                request_id=provider.get("request_id"), finish_reason=provider.get("finish_reason"))
            if not tool_calls:
                gates = self.modules.dispatch("before_finish", {"turn": turn, "text": text})
                if gates:
                    messages.append({"role": "assistant", "content": text})
                    messages.append({"role": "user", "content": "\n\n".join(a.payload["message"] for a in gates)})
                    continue
                finish_event = self.journal.append("agent_finish", model_turn_id=turn, response=text,
                                                  model_response_event_id=response_event["event_id"])
                if self.egc:
                    self.egc.finish(finish_event, text)
                self.modules.dispatch("task_end", {"turn": turn, "status": "finished"})
                return {"status": "finished", "answer": text, "turns": turn,
                        "tool_calls": self.tool_calls, "input_tokens": self.input_tokens,
                        "output_tokens": self.output_tokens, "messages": messages,
                        "pyautogui_action_attempts": self.pyautogui_action_attempts,
                        "pyautogui_actions_executed": self.pyautogui_actions_executed}

            messages.append({k: v for k, v in raw.items() if not k.startswith("_")})
            results: list[dict[str, Any]] = []
            for idx, tc in enumerate(tool_calls):
                call_id = tc.get("id") or str(uuid.uuid4())
                tc["id"] = call_id
                messages[-1]["tool_calls"][idx]["id"] = call_id
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception as exc:
                    args = None
                    error = f"invalid tool arguments: {exc}"
                else:
                    error = None
                if error:
                    out = ToolResult(call_id, error, is_error=True)
                    self.journal.append("tool_call_rejected", model_turn_id=turn,
                                        tool_call_id=call_id, raw_arguments=fn.get("arguments"),
                                        reason=error)
                elif fn.get("name") != "ipython" or not isinstance(args.get("code"), str):
                    out = ToolResult(call_id, f"unsupported tool call: {fn.get('name')}", is_error=True)
                    artifacts = []
                    self.journal.append("tool_call_rejected", model_turn_id=turn,
                                        tool_call_id=call_id, tool_name=fn.get("name"),
                                        arguments=args, reason="tool is not registered or schema is invalid")
                else:
                    self.modules.dispatch("before_tool_call", {"model_turn_id": turn, "tool_call_id": call_id,
                                                                 "name": fn["name"], "arguments": args})
                    before_artifacts = self.artifact_probe(args["code"]) if self.artifact_probe else None
                    start = time.monotonic()
                    artifacts = []
                    call_event = self.journal.append("tool_call", model_turn_id=turn, tool_call_id=call_id,
                                        tool_name=fn["name"], arguments=args)
                    action_rows = []
                    try:
                        data = self.kernel.execute(args["code"])
                        action_rows = data.get("executed_actions", [])
                        action_event_ids = self._record_gui_actions(action_rows, turn, call_id, call_event)
                        content, artifacts = _format_kernel_result(data, self.journal, self.max_tool_output_chars)
                        out = ToolResult(call_id, content, is_error=data.get("status") != "ok",
                                         duration_seconds=time.monotonic()-start)
                    except Exception as exc:
                        action_rows = getattr(exc, "executed_actions", [])
                        action_event_ids = self._record_gui_actions(action_rows, turn, call_id, call_event)
                        out = ToolResult(call_id, repr(exc), is_error=True,
                                         duration_seconds=time.monotonic()-start)
                    self.tool_calls += 1
                    result_event = self.journal.append("tool_result", model_turn_id=turn, tool_call_id=call_id,
                                        content=out.content, is_error=out.is_error,
                                        duration_seconds=out.duration_seconds,
                                        artifacts=artifacts,
                                        pyautogui_action_event_ids=action_event_ids,
                                        pyautogui_action_count=sum(1 for row in action_rows
                                                                   if row.get("method") != "screenshot"),
                                        gui_action_count=len(action_event_ids),
                                        gui_action_count_completeness="PyAutoGUI calls only; shell/API-based GUI mutations may be unobserved")
                    if self.egc:
                        self.egc.tool_result(call_event, result_event, args["code"], out.content,
                                             artifacts, is_error=out.is_error,
                                             model_turn_id=turn, tool_call_id=call_id)
                    self.modules.dispatch("after_tool_call", {"model_turn_id": turn, "tool_call_id": call_id,
                                                               "result": out.content, "is_error": out.is_error})
                    if self.artifact_probe:
                        after_artifacts = self.artifact_probe(args["code"])
                        changes = []
                        for path in set(before_artifacts or {}) | set(after_artifacts or {}):
                            before = (before_artifacts or {}).get(path)
                            after = (after_artifacts or {}).get(path)
                            if before != after:
                                changes.append({"path": path, "before": before, "after": after})
                        if changes:
                            artifact_event = self.journal.append("artifact_updated", model_turn_id=turn,
                                                tool_call_id=call_id, changes=changes,
                                                source="guest filesystem metadata probe")
                            self.modules.dispatch("artifact_updated", {"model_turn_id": turn,
                                                                         "tool_call_id": call_id,
                                                                         "changes": changes})
                            if self.egc:
                                self.egc.artifact_updated(artifact_event, changes, model_turn_id=turn,
                                                          tool_call_id=call_id)
                    if self.after_tool_observer:
                        observation = self.after_tool_observer(turn, call_id)
                        observation_event_id = observation.get("event_id") if isinstance(observation, dict) else observation
                        for action_event_id in action_event_ids:
                            self.journal.append("gui_action_observation", model_turn_id=turn,
                                                tool_call_id=call_id, gui_action_event_id=action_event_id,
                                                screenshot_event_id=observation_event_id,
                                                tool_result_event_id=result_event["event_id"],
                                                tool_result_appended_to_context=True,
                                                model_visible_image_artifact_ids=[
                                                    artifact["artifact_id"] for artifact in artifacts
                                                    if str(artifact.get("media_type", "")).startswith("image/")],
                                                observation_status="AVAILABLE" if observation_event_id else "MISSING",
                                                fed_to_model=False if observation_event_id else None)
                result_msg = {"content": out.content}
                results.append(result_msg)
            for tc, result in zip(tool_calls, results, strict=True):
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": result["content"]})
            if turn % self.compact_after == 0:
                precompact_messages = messages
                messages = compact_messages(messages, keep_recent=self.keep_recent,
                                            instruction=instruction, event_bus=self.modules)
                compaction_event = self.journal.append("context_compaction", model_turn_id=turn,
                                    retained_messages=len(messages), kernel_state="preserved")
                if self.egc:
                    summary = messages[2].get("content", "") if len(messages) > 2 else ""
                    self.egc.history_compaction(compaction_event, precompact_messages, str(summary))
        self.modules.dispatch("task_end", {"turn": self.model_turns, "status": "budget_exhausted"})
        self.journal.append("budget_exhausted", model_turn_id=self.model_turns, max_steps=self.max_steps)
        return {"status": "budget_exhausted", "turns": self.model_turns,
                "tool_calls": self.tool_calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "messages": messages,
                "pyautogui_action_attempts": self.pyautogui_action_attempts,
                "pyautogui_actions_executed": self.pyautogui_actions_executed}

    def _record_gui_actions(self, action_rows: list[dict[str, Any]], turn: int,
                            call_id: str, call_event: dict[str, Any]) -> list[str]:
        event_ids = []
        for row in action_rows:
            status = row.get("status", "UNKNOWN")
            action_event = self.journal.append(
                "gui_action_executed", model_turn_id=turn, tool_call_id=call_id,
                action_id=row.get("action_id"), action_sequence=row.get("sequence"),
                primitive=row.get("method"), capability=row.get("capability"),
                arguments=row.get("arguments"), status=status,
                backend_call_status="RETURNED" if status == "executed" else "RAISED",
                effect_status="NOT_ASSESSED",
                requested_model_coordinates=row.get("requested_model_coordinates"),
                exception=row.get("exception"), duration_seconds=row.get("duration_seconds"),
                started_unix=row.get("started_unix"), parent_event_id=call_event["event_id"],
                instrumentation_scope=("registered cua screenshot capability" if row.get("method") == "screenshot"
                                       else "pyautogui public API; nested implementation calls are coalesced"))
            event_ids.append(action_event["event_id"])
            if row.get("method") != "screenshot":
                self.pyautogui_action_attempts += 1
                if status == "executed":
                    self.pyautogui_actions_executed += 1
        return event_ids


def _format_kernel_result(result: dict[str, Any], journal: SessionJournal,
                          max_chars: int = 30000) -> tuple[Any, list[dict[str, Any]]]:
    parts: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    if result.get("status") != "ok":
        parts.append({"type": "text", "text": "Execution failed."})
    for output in result.get("outputs", []):
        if output.get("type") == "text":
            text = output.get("text", "")
            if text:
                if len(text) > max_chars:
                    ref = journal.artifact(text.encode("utf-8"), ".txt", "text/plain")
                    artifacts.append(ref)
                    text = text[:max_chars] + f"\n[truncated in model context; full output artifact {ref['artifact_id']}]"
                parts.append({"type": "text", "text": text})
        elif output.get("type") == "image":
            encoded = output.get("data", "")
            raw = base64.b64decode(encoded)
            mime = output.get("mime_type", "image/jpeg")
            suffix = ".png" if mime == "image/png" else ".jpg"
            ref = journal.artifact(raw, suffix, mime)
            ref["source_path"] = output.get("path")
            artifacts.append(ref)
            parts.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
            }})
    if result.get("error"):
        parts.append({"type": "text", "text": str(result["error"])})
    if not parts:
        parts = [{"type": "text", "text": "Cell executed with no textual output."}]
    return parts, artifacts

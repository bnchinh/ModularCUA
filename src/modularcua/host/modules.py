from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable


LIFECYCLE_EVENTS = {
    "task_start", "before_model_call", "before_tool_call", "after_tool_call",
    "artifact_updated", "before_compaction", "before_finish", "task_end",
}


@dataclass
class HookAction:
    kind: str
    payload: dict[str, Any]
    requested_by: str


class Module:
    name = "module"
    subscriptions: set[str] = set()
    authorized_actions: set[str] = set()

    def on_event(self, event: str, payload: dict[str, Any]) -> list[HookAction]:
        return []


class EventBus:
    def __init__(self, enabled_modules: list[Module] | None = None):
        self._subscribers: dict[str, list[Module]] = defaultdict(list)
        for module in enabled_modules or []:
            self.register(module)

    def register(self, module: Module) -> None:
        if not module.subscriptions <= LIFECYCLE_EVENTS:
            raise ValueError(f"{module.name} subscribed to unknown lifecycle event")
        for event in module.subscriptions:
            self._subscribers[event].append(module)

    def dispatch(self, event: str, payload: dict[str, Any]) -> list[HookAction]:
        actions: list[HookAction] = []
        for module in self._subscribers.get(event, []):
            for action in module.on_event(event, payload):
                if action.kind not in module.authorized_actions:
                    raise PermissionError(f"{module.name} requested unauthorized action {action.kind}")
                actions.append(action)
        return actions

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    output_schema: dict[str, Any]


class CapabilityRegistry:
    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, name: str, handler: Callable[..., Any], *, description: str = "",
                 input_schema: dict[str, Any] | None = None,
                 output_schema: dict[str, Any] | None = None) -> None:
        if name in self._capabilities:
            raise ValueError(f"capability already registered: {name}")
        self._capabilities[name] = Capability(
            name=name, description=description,
            input_schema=input_schema or {"type": "object"},
            handler=handler, output_schema=output_schema or {"type": "object"},
        )

    def invoke(self, name: str, **kwargs: Any) -> Any:
        if name not in self._capabilities:
            raise KeyError(f"capability not available: {name}")
        return self._capabilities[name].handler(**kwargs)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def descriptors(self) -> list[dict[str, Any]]:
        return [{"name": cap.name, "description": cap.description,
                 "input_schema": cap.input_schema, "output_schema": cap.output_schema}
                for cap in self._capabilities.values()]

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .context import NativeRunContext
from .errors import CapabilityUnavailable, ToolNotGranted

@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[NativeRunContext, dict[str, Any]], Any]
    required_capability: str = ""
    read_resource: str = ""
    write_resource: str = ""
    risk: str = ""
    source_projector: Callable[[Any], list[dict[str, Any]]] | None = None

    def eligible(self, context: NativeRunContext) -> bool:
        if self.required_capability and not context.capability_available(self.required_capability):
            return False
        if not context.tool_enabled(self.name):
            return False
        # Network is opt-in even when the PermissionBroker grants the risk.
        # A missing composer/tool selection must not silently trigger internet access.
        if self.risk=="network" and context.enabled_tools is None:
            return False
        if self.read_resource and self.read_resource not in context.permission_scope.resources_read and "*" not in context.permission_scope.resources_read:
            return False
        if self.write_resource and self.write_resource not in context.permission_scope.resources_write and "*" not in context.permission_scope.resources_write:
            return False
        if self.risk and self.risk not in context.permission_scope.risks and "*" not in context.permission_scope.risks:
            return False
        return True

    def execute(self, context: NativeRunContext, args: dict[str, Any]) -> Any:
        if self.required_capability:
            context.require_capability(self.required_capability)
        if self.read_resource:
            context.permission_scope.require_read(self.read_resource)
        if self.write_resource:
            context.permission_scope.require_write(self.write_resource)
        if self.risk:
            context.permission_scope.require_risk(self.risk)
        return self.handler(context, args)

    def as_llm_tool(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name or spec.name in self._tools:
            raise ValueError(f"duplicate/invalid tool: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise CapabilityUnavailable(f"tool:{name}") from exc

    def list(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools.values())

    def granted_names(
        self,
        context: NativeRunContext,
        candidate_names: tuple[str, ...] | list[str],
    ) -> tuple[str, ...]:
        return tuple(
            x for x in candidate_names
            if x in self._tools and self._tools[x].eligible(context)
        )

    def schemas(self, names) -> list[dict[str, Any]]:
        return [self._tools[x].as_llm_tool() for x in names if x in self._tools]

    def execute_granted(
        self,
        context: NativeRunContext,
        *,
        granted_names: set[str] | frozenset[str] | tuple[str, ...],
        name: str,
        args: dict[str, Any],
    ) -> Any:
        if name not in set(granted_names):
            raise ToolNotGranted(f"tool was not granted for this turn: {name}")
        return self.get(name).execute(context, args)

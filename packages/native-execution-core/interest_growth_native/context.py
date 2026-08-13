from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Any

from .contracts import DomainPolicy, HostTutorBinding
from .errors import CapabilityUnavailable, PermissionDenied, ValidationError

@dataclass(frozen=True, slots=True)
class PermissionScope:
    resources_read: frozenset[str] = frozenset()
    resources_write: frozenset[str] = frozenset()
    risks: frozenset[str] = frozenset()

    def require_read(self, resource: str) -> None:
        if resource not in self.resources_read and "*" not in self.resources_read:
            raise PermissionDenied(f"read permission required: {resource}")

    def require_write(self, resource: str) -> None:
        if resource not in self.resources_write and "*" not in self.resources_write:
            raise PermissionDenied(f"write permission required: {resource}")

    def require_risk(self, risk: str) -> None:
        if risk not in self.risks and "*" not in self.risks:
            raise PermissionDenied(f"risk permission required: {risk}")

@dataclass(frozen=True, slots=True)
class NativeRunContext:
    area_id: str
    session_id: str
    domain_policy: DomainPolicy
    area_capabilities: frozenset[str]
    global_capabilities: frozenset[str]
    permission_scope: PermissionScope = field(default_factory=PermissionScope)
    selected_capability: str | None = None
    user_message: str = ""
    conversation_history: tuple[dict[str, Any], ...] = ()
    enabled_tools: frozenset[str] | None = None
    allowed_builtin_tools: frozenset[str] | None = None
    knowledge_base_ids: tuple[str, ...] = ()
    persona_context: str = ""
    persona_fingerprint: str = ""
    skills_manifest: str = ""
    skills_fingerprint: str = ""
    memory_context: str = ""
    source_manifest: str = ""
    host_tutor: HostTutorBinding | None = None
    config_overrides: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    server_tool_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def domain_pack_id(self) -> str:
        return self.domain_policy.domain_pack_id

    def validate(self) -> None:
        if not self.area_id.strip():
            raise ValidationError("area_id is required")
        if not self.session_id.strip():
            raise ValidationError("session_id is required")
        if not self.domain_pack_id.strip():
            raise ValidationError("domain_pack_id is required")
        if not self.global_capabilities:
            raise ValidationError(
                "global_capabilities must be explicitly supplied; production must fail closed"
            )

    def capability_available(self, capability_id: str) -> bool:
        area = capability_id in self.area_capabilities or "*" in self.area_capabilities
        glob = capability_id in self.global_capabilities or "*" in self.global_capabilities
        return area and glob

    def require_capability(self, capability_id: str) -> None:
        if not self.capability_available(capability_id):
            raise CapabilityUnavailable(f"capability disabled/unavailable: {capability_id}")

    def tool_enabled(self, tool_name: str) -> bool:
        if self.allowed_builtin_tools is not None and tool_name not in self.allowed_builtin_tools:
            return False
        if self.enabled_tools is not None and tool_name not in self.enabled_tools:
            return False
        return True

    def bind_tool_args(self, tool_name: str, model_args: dict[str, Any]) -> dict[str, Any]:
        merged = dict(model_args)
        binding = self.server_tool_bindings.get(tool_name)
        if binding:
            merged.update(binding)
        return merged

    def child(self, **updates: Any) -> "NativeRunContext":
        return replace(self, **updates)

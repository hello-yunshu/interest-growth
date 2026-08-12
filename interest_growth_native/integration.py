from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

from .bundle import NativeEngineBundle
from .context import NativeRunContext,PermissionScope
from .contracts import DomainPolicy,HostTutorBinding

@dataclass(frozen=True,slots=True)
class InterestGrowthAreaSnapshot:
    area_id:str
    domain_policy:DomainPolicy
    capability_ids:frozenset[str]
    # No fail-open default. The host MUST pass real global plugin lifecycle.
    global_capability_ids:frozenset[str]

class InterestGrowthBridge:
    def __init__(
        self,bundle:NativeEngineBundle,*,
        permission_resolver:Callable[[str],PermissionScope]
    ):
        self.bundle=bundle;self.permission_resolver=permission_resolver

    def context(
        self,*,area:InterestGrowthAreaSnapshot,session_id:str,user_message="",
        history=None,selected_capability=None,kb_ids=None,persona_context="",
        persona_fingerprint="",skills_manifest="",skills_fingerprint="",
        memory_context="",source_manifest="",operation="tutor",
        host_tutor:HostTutorBinding|None=None,metadata=None,server_tool_bindings=None,
        enabled_tools=None,allowed_builtin_tools=None,config_overrides=None,
    ):
        return NativeRunContext(
            area_id=area.area_id,session_id=session_id,
            domain_policy=area.domain_policy,
            area_capabilities=area.capability_ids,
            global_capabilities=area.global_capability_ids,
            permission_scope=self.permission_resolver(operation),
            selected_capability=selected_capability,user_message=user_message,
            conversation_history=tuple(history or ()),
            enabled_tools=(frozenset(enabled_tools) if enabled_tools is not None else None),
            allowed_builtin_tools=(frozenset(allowed_builtin_tools) if allowed_builtin_tools is not None else None),
            knowledge_base_ids=tuple(kb_ids or ()),
            persona_context=persona_context,persona_fingerprint=persona_fingerprint,
            skills_manifest=skills_manifest,skills_fingerprint=skills_fingerprint,
            memory_context=memory_context,source_manifest=source_manifest,
            host_tutor=host_tutor,metadata=dict(metadata or {}),
            server_tool_bindings={str(k):dict(v) for k,v in dict(server_tool_bindings or {}).items()},
            config_overrides=dict(config_overrides or {}),
        )

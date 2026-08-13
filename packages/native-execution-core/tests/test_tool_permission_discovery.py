from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.context import PermissionScope
from .helpers import StaticResolver,ctx,kb,store

def test_read_source_hook_not_offered_without_source_read_permission():
    b=NativeEngineBundle(
        knowledge_resolver=StaticResolver([kb()]),store=store(),
        product_tool_hooks={"read_source":lambda c,a:{"text":"x"}},
    )
    c=ctx().child(permission_scope=PermissionScope(
        resources_read=frozenset({"tutor"}),
        resources_write=frozenset({"tutor"}),
        risks=frozenset({"llm"}),
    ))
    assert "read_source" not in set(b.tutor._granted_tools(c))

def test_network_tool_requires_both_permission_and_explicit_user_enablement():
    b=NativeEngineBundle(knowledge_resolver=StaticResolver([kb()]),store=store())
    c=ctx(selected_capability="capability.research-evidence")
    assert "paper_search" not in set(b.tutor._granted_tools(c))
    enabled=c.child(enabled_tools=frozenset({"paper_search"}))
    assert "paper_search" in set(b.tutor._granted_tools(enabled))

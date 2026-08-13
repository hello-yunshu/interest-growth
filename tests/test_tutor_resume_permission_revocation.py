from __future__ import annotations

import pytest

from interest_growth_native.bundle import NativeEngineBundle
from interest_growth_native.context import PermissionScope
from interest_growth_native.errors import AreaIsolationError
from interest_growth_native.llm import LLMResponse
from .helpers import ALL_CAPS, StaticResolver, ctx, kb, store

NETWORK_PERMS = PermissionScope(
    resources_read=frozenset({"knowledge", "tutor", "agent_memory"}),
    resources_write=frozenset({"tutor", "agent_memory"}),
    risks=frozenset({"llm", "network"}),
)
NO_NETWORK_PERMS = PermissionScope(
    resources_read=NETWORK_PERMS.resources_read,
    resources_write=NETWORK_PERMS.resources_write,
    risks=frozenset({"llm"}),
)


class AskOnce:
    available = True

    def __init__(self, resumed_response):
        self.n = 0
        self.seen_schemas = []
        self.resumed_response = resumed_response

    def complete(self, **kwargs):
        self.seen_schemas.append([t["function"]["name"] for t in (kwargs.get("tools") or [])])
        self.n += 1
        if self.n == 1:
            return LLMResponse("", ({"id": "q1", "name": "ask_user", "arguments": {"question": "go?"}},))
        return self.resumed_response(self.n)


def _tracked_bundle(hooks, llm):
    return NativeEngineBundle(
        knowledge_resolver=StaticResolver([kb()]), store=store(), llm=llm,
        product_tool_hooks=hooks,
    )


def test_resume_rejects_web_search_after_network_revoked():
    web_calls = []
    llm = AskOnce(lambda n: LLMResponse("", ({"id": "w1", "name": "web_search", "arguments": {"query": "x"}},)))
    b = _tracked_bundle({"web_search": lambda c, a: web_calls.append(a)}, llm)
    first = b.tutor.start(ctx(user_message="start"))
    assert first.run.state == "waiting_input"
    resumed = b.tutor.resume(ctx(perms=NO_NETWORK_PERMS, user_message="start"),
                             run_id=first.run.id, user_input="yes")
    assert resumed.run.state == "error"
    assert web_calls == []
    assert "web_search" not in llm.seen_schemas[-1]
    assert "ask_user" in llm.seen_schemas[-1]


def test_resume_rejects_tool_after_area_capability_disabled():
    from interest_growth_native.capabilities import CAP_KNOWLEDGE
    llm = AskOnce(lambda n: LLMResponse("", ({"id": "r1", "name": "rag", "arguments": {"query": "q"}},)))
    b = _tracked_bundle({}, llm)
    first = b.tutor.start(ctx(user_message="start"))
    assert first.run.state == "waiting_input"
    disabled = ctx(
        user_message="start",
        caps=ALL_CAPS - {CAP_KNOWLEDGE},
        global_caps=ALL_CAPS,
    )
    resumed = b.tutor.resume(disabled, run_id=first.run.id, user_input="yes")
    assert resumed.run.state == "error"
    assert "rag" not in llm.seen_schemas[-1]


def test_new_tool_grant_after_pause_does_not_expand_old_turn():
    web_calls = []
    llm = AskOnce(lambda n: LLMResponse("", ({"id": "w1", "name": "web_search", "arguments": {"query": "x"}},)))
    b = _tracked_bundle({"web_search": lambda c, a: web_calls.append(a)}, llm)
    start_ctx = ctx(user_message="start", enabled_tools=frozenset({"reason", "brainstorm"}))
    first = b.tutor.start(start_ctx)
    assert first.run.state == "waiting_input"
    expanded = ctx(user_message="start", enabled_tools=frozenset({"reason", "brainstorm", "web_search"}))
    resumed = b.tutor.resume(expanded, run_id=first.run.id, user_input="yes")
    assert resumed.run.state == "error"
    assert web_calls == []
    assert "web_search" not in llm.seen_schemas[-1]


def test_executed_tool_results_survive_permission_revocation():
    class ReasonAskResume:
        available = True

        def __init__(self):
            self.n = 0
            self.resume_messages = None

        def complete(self, **kwargs):
            self.n += 1
            if self.n == 1:
                return LLMResponse("", ({"id": "t1", "name": "reason", "arguments": {"q": "x"}},))
            if self.n == 2:
                return LLMResponse("", ({"id": "q1", "name": "ask_user", "arguments": {"question": "go?"}},))
            self.resume_messages = kwargs["messages"]
            return LLMResponse("completed after revocation")

    llm = ReasonAskResume()
    b = _tracked_bundle({"reason": lambda c, a: {"marker": "TOOLCTX"}}, llm)
    first = b.tutor.start(ctx(user_message="start"))
    assert first.run.state == "waiting_input"
    resumed = b.tutor.resume(ctx(perms=NO_NETWORK_PERMS, user_message="start"),
                             run_id=first.run.id, user_input="yes")
    assert resumed.run.state == "completed"
    assert "TOOLCTX" in str(llm.resume_messages)
    assert resumed.run.id == first.run.id


def test_resume_cannot_cross_interest_area():
    b = _tracked_bundle({}, AskOnce(lambda n: LLMResponse("done")))
    first = b.tutor.start(ctx(user_message="start"))
    assert first.run.state == "waiting_input"
    with pytest.raises(AreaIsolationError):
        b.tutor.resume(ctx(area="other", user_message="start"), run_id=first.run.id, user_input="yes")

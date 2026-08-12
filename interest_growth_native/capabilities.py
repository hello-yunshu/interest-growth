from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import NativeRunContext

CAP_TUTOR = "capability.tutor-runtime"
CAP_RESEARCH = "capability.research-evidence"
CAP_KNOWLEDGE = "capability.knowledge-rag"
CAP_MASTERY = "capability.mastery"
CAP_PRACTICE = "capability.practice"
CAP_NOTEBOOK = "capability.learning-notebook"
CAP_COWRITER = "capability.co-writer"
CAP_BOOK = "capability.living-book"
CAP_VISUALIZE = "capability.visualize"
CAP_DEEP_SOLVE = "capability.deep-solve"

@dataclass(frozen=True, slots=True)
class PromptBlock:
    name: str
    content: str

@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    id: str
    owned_tools: tuple[str, ...] = ()
    exclusive_tools: bool = False
    prompt_factory: Callable[["NativeRunContext"], PromptBlock | None] | None = None

class CapabilityRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        if not spec.id or spec.id in self._specs:
            raise ValueError(f"duplicate/invalid capability: {spec.id}")
        self._specs[spec.id] = spec

    def get(self, capability_id: str) -> CapabilitySpec:
        from .errors import CapabilityUnavailable
        try:
            return self._specs[capability_id]
        except KeyError as exc:
            raise CapabilityUnavailable(capability_id) from exc

    def list(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specs.values())

    def available(self, context: "NativeRunContext") -> tuple[CapabilitySpec, ...]:
        return tuple(x for x in self._specs.values() if context.capability_available(x.id))

    def selected(self, context: "NativeRunContext") -> CapabilitySpec | None:
        if not context.selected_capability:
            return None
        spec = self.get(context.selected_capability)
        context.require_capability(spec.id)
        return spec

    def compose_tools(
        self,
        context: "NativeRunContext",
        baseline_tools: Iterable[str],
    ) -> tuple[str, ...]:
        selected = self.selected(context)
        if selected and selected.exclusive_tools:
            return tuple(sorted({"ask_user", *selected.owned_tools}))
        names = {x for x in baseline_tools if context.tool_enabled(x)}
        names.add("ask_user")
        if selected:
            names.update(selected.owned_tools)
        return tuple(sorted(names))

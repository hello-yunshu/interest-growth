from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from pg_domain import ResearchPlan, ResearchResult

T = TypeVar("T", bound=BaseModel)


class ResearchEngine(ABC):
    @abstractmethod
    async def create_plan(self, question: str, depth: str = "normal") -> ResearchPlan: ...

    @abstractmethod
    async def run(self, plan: ResearchPlan) -> ResearchResult: ...

    async def stream(self, plan: ResearchPlan) -> AsyncIterator[dict[str, Any]]:
        result = await self.run(plan)
        yield {"type": "result", "result": result}

    async def cancel(self, run_id: str) -> bool:
        return False

    @abstractmethod
    def normalize_result(self, raw: dict[str, Any]) -> ResearchResult: ...


class KnowledgeEngine(ABC):
    """Rebuildable knowledge/index engine; never the product fact store."""

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...

    @abstractmethod
    async def providers(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def list_bases(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def create_with_file(
        self, name: str, path: str | Path, *, provider: str = "llamaindex"
    ) -> dict[str, Any]: ...

    async def create_with_files(
        self,
        name: str,
        files: list[tuple[str | Path, str | None]],
        *,
        provider: str = "llamaindex",
    ) -> dict[str, Any]:
        if not files:
            raise ValueError("at least one source file is required")
        first_path, _ = files[0]
        result = await self.create_with_file(name, first_path, provider=provider)
        for path, _ in files[1:]:
            await self.add_document(name, path, provider=provider)
        return result

    @abstractmethod
    async def add_document(
        self, name: str, path: str | Path, *, provider: str | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def rebuild(self, name: str) -> dict[str, Any]: ...

    @abstractmethod
    async def progress(self, name: str) -> dict[str, Any]: ...


class ParsingEngine(ABC):
    @abstractmethod
    async def preview_text(self, knowledge_base: str, filename: str) -> str: ...


class RetrievalEngine(ABC):
    @abstractmethod
    async def retrieve(
        self,
        query: str,
        *,
        knowledge_bases: list[str],
        skills: list[str] | None = None,
    ) -> dict[str, Any]: ...


class LearningEngine(ABC):
    @abstractmethod
    async def guided_path(
        self,
        content: str,
        *,
        knowledge_bases: list[str] | None = None,
        skills: list[str] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def deep_question(
        self,
        content: str,
        *,
        knowledge_bases: list[str] | None = None,
        skills: list[str] | None = None,
    ) -> dict[str, Any]: ...


class MemoryEngine(ABC):
    @abstractmethod
    async def overview(self) -> dict[str, Any]: ...

    @abstractmethod
    async def read_doc(self, layer: str, key: str) -> dict[str, Any]: ...


class VisualizationEngine(ABC):
    @abstractmethod
    async def visualize(
        self,
        content: str,
        *,
        knowledge_bases: list[str] | None = None,
    ) -> dict[str, Any]: ...


class SkillEngine(ABC):
    @abstractmethod
    async def list_skills(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def sync_directory(self, root: str | Path) -> dict[str, Any]: ...


class LLMProvider(ABC):
    @abstractmethod
    async def text(self, prompt: str, *, system: str | None = None) -> str: ...

    @abstractmethod
    async def structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T: ...

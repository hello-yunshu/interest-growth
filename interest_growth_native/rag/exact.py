from __future__ import annotations

import asyncio
import hashlib
import inspect
import shutil
import threading
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Mapping

from ..contracts import KnowledgeBaseSnapshot, SourceLocator, SourceTextSnapshot
from ..errors import ExactRagAdapterError, ExactRagDependencyError, ExactRagProvenanceError
from .types import RetrievalCandidate


def _checked_distribution(name: str, reviewed_prefixes: tuple[str, ...]) -> str:
    try:
        version = metadata.version(name)
    except metadata.PackageNotFoundError as exc:
        raise ExactRagDependencyError(
            f"reviewed exact adapter requires optional distribution {name!r}"
        ) from exc
    if not any(version.startswith(prefix) for prefix in reviewed_prefixes):
        expected = ", ".join(f"{prefix}x" for prefix in reviewed_prefixes)
        raise ExactRagDependencyError(
            f"{name} {version} is outside the reviewed API line ({expected}); review required"
        )
    return version


def _score(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _locator(values: Mapping[str, Any], *, filename: str) -> SourceLocator:
    def integer(name: str) -> int | None:
        value = values.get(name)
        try:
            return int(value) if value is not None and str(value).strip() else None
        except (TypeError, ValueError):
            return None

    return SourceLocator(
        filename=filename,
        page=integer("page") or integer("page_number") or integer("start_index"),
        section=str(values.get("section") or values.get("title") or ""),
        char_start=integer("char_start"),
        char_end=integer("char_end"),
        slide=integer("slide"),
        sheet=str(values.get("sheet") or ""),
        cell_range=str(values.get("cell_range") or ""),
    )


def _candidate(
    *,
    engine_id: str,
    kb_id: str,
    source: SourceTextSnapshot,
    chunk_id: str,
    text: str,
    score: float,
    ordinal: int,
    locator: SourceLocator | None = None,
    raw_citation: Mapping[str, Any] | None = None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        kb_id=kb_id,
        source_id=source.source_id,
        source_fingerprint=source.fingerprint,
        filename=source.filename,
        score=score,
        text=text,
        ordinal=ordinal,
        locator=locator or source.locator,
        engine_id=engine_id,
        raw_citation=dict(raw_citation or {}),
    )


class _AsyncLoopRunner:
    """Own one event loop so upstream async storage objects never cross loops."""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        loop.run_forever()
        loop.close()

    def run(self, awaitable: Any) -> Any:
        if not inspect.isawaitable(awaitable):
            return awaitable
        if self._loop is None:
            raise ExactRagAdapterError("upstream adapter event loop did not start")
        return asyncio.run_coroutine_threadsafe(awaitable, self._loop).result()

    def close(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2)


@dataclass(slots=True)
class _Built:
    kb: KnowledgeBaseSnapshot
    upstream: Any
    extra: Any = None


class LlamaIndexExactAdapter:
    """Reviewed binding to LlamaIndex VectorStoreIndex, not native lexical search."""

    engine_id = "llamaindex"
    upstream_distribution = "llama-index-core"
    reviewed_version = "0.14 API line reviewed 2026-08-13"

    def __init__(self, *, embed_model: Any = None, runtime: Any = None) -> None:
        if runtime is None:
            _checked_distribution(self.upstream_distribution, ("0.14.",))
            from llama_index.core import Document, VectorStoreIndex

            runtime = SimpleNamespace(Document=Document, VectorStoreIndex=VectorStoreIndex)
        self.runtime = runtime
        self.embed_model = embed_model

    def build(self, kb: KnowledgeBaseSnapshot) -> _Built:
        documents = [
            self.runtime.Document(
                text=source.text,
                id_=source.source_id,
                metadata={
                    "source_id": source.source_id,
                    "source_fingerprint": source.fingerprint,
                    "filename": source.filename,
                    "page": source.locator.page,
                    "section": source.locator.section,
                },
            )
            for source in kb.sources
        ]
        kwargs = {"embed_model": self.embed_model} if self.embed_model is not None else {}
        index = self.runtime.VectorStoreIndex.from_documents(documents, **kwargs)
        return _Built(kb, index)

    def retrieve(self, built: _Built, *, query: str, top_k: int) -> list[RetrievalCandidate]:
        retriever = built.upstream.as_retriever(similarity_top_k=top_k)
        hits = retriever.retrieve(query)
        sources = {source.source_id: source for source in built.kb.sources}
        output = []
        for ordinal, hit in enumerate(hits[:top_k]):
            node = getattr(hit, "node", hit)
            values = dict(getattr(node, "metadata", {}) or {})
            source_id = str(values.get("source_id") or "")
            source = sources.get(source_id)
            if source is None:
                raise ExactRagProvenanceError(
                    "LlamaIndex result omitted the canonical source_id metadata"
                )
            content = (
                node.get_content() if callable(getattr(node, "get_content", None))
                else str(getattr(node, "text", ""))
            )
            output.append(_candidate(
                engine_id=self.engine_id,
                kb_id=built.kb.kb_id,
                source=source,
                chunk_id=str(getattr(node, "node_id", None) or getattr(node, "id_", "") or f"llama-{ordinal}"),
                text=content,
                score=_score(getattr(hit, "score", None), 1.0 / (ordinal + 1)),
                ordinal=ordinal,
                locator=_locator(values, filename=source.filename),
                raw_citation={"upstream": "llama-index-core", "node_id": str(getattr(node, "node_id", ""))},
            ))
        return output


class LightRagExactAdapter:
    """Reviewed binding to HKUDS LightRAG structured retrieval (`aquery_data`)."""

    engine_id = "lightrag"
    upstream_distribution = "lightrag-hku"
    reviewed_version = "1.5 API line reviewed 2026-08-13"

    def __init__(self, *, storage_root: str | Path, rag_kwargs: Mapping[str, Any], runtime: Any = None) -> None:
        if runtime is None:
            _checked_distribution(self.upstream_distribution, ("1.5.",))
            from lightrag import LightRAG, QueryParam

            runtime = SimpleNamespace(LightRAG=LightRAG, QueryParam=QueryParam)
        self.runtime = runtime
        self.storage_root = Path(storage_root)
        self.rag_kwargs = dict(rag_kwargs)

    def _workspace(self, kb: KnowledgeBaseSnapshot) -> Path:
        digest = hashlib.sha256(f"{kb.kb_id}:{kb.fingerprint}".encode()).hexdigest()[:16]
        return self.storage_root / f"{kb.kb_id}-{digest}"

    def build(self, kb: KnowledgeBaseSnapshot) -> _Built:
        workspace = self._workspace(kb)
        workspace.mkdir(parents=True, exist_ok=True)
        runner = _AsyncLoopRunner()
        try:
            kwargs = dict(self.rag_kwargs)
            kwargs.update({"working_dir": str(workspace), "auto_manage_storages_states": False})
            rag = self.runtime.LightRAG(**kwargs)
            runner.run(rag.initialize_storages())
            runner.run(rag.ainsert(
                [source.text for source in kb.sources],
                ids=[source.source_id for source in kb.sources],
                file_paths=[source.filename for source in kb.sources],
            ))
        except Exception:
            runner.close()
            raise
        return _Built(kb, rag, runner)

    def retrieve(self, built: _Built, *, query: str, top_k: int) -> list[RetrievalCandidate]:
        params = self.runtime.QueryParam(mode="mix", top_k=top_k, chunk_top_k=top_k)
        payload = built.extra.run(built.upstream.aquery_data(query, params))
        if payload.get("status") not in {None, "success"}:
            raise ExactRagAdapterError(f"LightRAG retrieval failed: {payload.get('message', 'unknown error')}")
        chunks = list((payload.get("data") or {}).get("chunks") or [])
        sources = {source.filename: source for source in built.kb.sources}
        output = []
        for ordinal, row in enumerate(chunks[:top_k]):
            alias = Path(str(row.get("file_path") or "")).name
            source = sources.get(alias)
            if source is None:
                raise ExactRagProvenanceError(
                    f"LightRAG returned an unknown collision-safe file path: {alias!r}"
                )
            output.append(_candidate(
                engine_id=self.engine_id,
                kb_id=built.kb.kb_id,
                source=source,
                chunk_id=str(row.get("chunk_id") or f"lightrag-{ordinal}"),
                text=str(row.get("content") or ""),
                score=_score(row.get("score") or row.get("relevance_score"), 1.0 / (ordinal + 1)),
                ordinal=ordinal,
                locator=_locator(row, filename=source.filename),
                raw_citation={
                    "upstream": "lightrag-hku",
                    "reference_id": str(row.get("reference_id") or ""),
                    "file_path": alias,
                },
            ))
        return output


class GraphRagExactAdapter:
    """Reviewed binding to Microsoft GraphRAG build_index + local_search APIs."""

    engine_id = "graphrag"
    upstream_distribution = "graphrag"
    reviewed_version = "3.1 API line reviewed 2026-08-13"

    def __init__(
        self,
        *,
        storage_root: str | Path,
        settings_root: str | Path,
        runtime: Any = None,
        search_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        if runtime is None:
            _checked_distribution(self.upstream_distribution, ("3.1.",))
            import pandas as pd
            import graphrag.api as api
            from graphrag.config.load_config import load_config

            runtime = SimpleNamespace(pd=pd, api=api, load_config=load_config)
        self.runtime = runtime
        self.storage_root = Path(storage_root)
        self.settings_root = Path(settings_root)
        self.search_kwargs = dict(search_kwargs or {})

    def _workspace(self, kb: KnowledgeBaseSnapshot) -> Path:
        digest = hashlib.sha256(f"{kb.kb_id}:{kb.fingerprint}".encode()).hexdigest()[:16]
        return self.storage_root / f"{kb.kb_id}-{digest}"

    def _prepare_workspace(self, kb: KnowledgeBaseSnapshot) -> tuple[Path, dict[str, SourceTextSnapshot]]:
        workspace = self._workspace(kb)
        input_dir = workspace / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        settings = self.settings_root / "settings.yaml"
        if not settings.is_file():
            raise ExactRagDependencyError("GraphRAG settings_root must contain settings.yaml")
        shutil.copy2(settings, workspace / "settings.yaml")
        prompts = self.settings_root / "prompts"
        if prompts.is_dir():
            shutil.copytree(prompts, workspace / "prompts", dirs_exist_ok=True)
        aliases: dict[str, SourceTextSnapshot] = {}
        for source in kb.sources:
            alias = f"{source.filename}.txt"
            (input_dir / alias).write_text(source.text, encoding="utf-8")
            aliases[alias] = source
            aliases[Path(alias).stem] = source
        return workspace, aliases

    def _read_table(self, output: Path, name: str, *, required: bool = True) -> Any:
        if callable(getattr(self.runtime, "read_table", None)):
            return self.runtime.read_table(output, name, required=required)
        path = output / f"{name}.parquet"
        if not path.is_file():
            if required:
                raise ExactRagAdapterError(f"GraphRAG did not produce {path.name}")
            return None
        return self.runtime.pd.read_parquet(path)

    def build(self, kb: KnowledgeBaseSnapshot) -> _Built:
        workspace, aliases = self._prepare_workspace(kb)
        config = self.runtime.load_config(workspace)
        runner = _AsyncLoopRunner()
        results = runner.run(self.runtime.api.build_index(config=config))
        failures = [item for item in results or [] if getattr(item, "errors", None)]
        if failures:
            runner.close()
            raise ExactRagAdapterError(f"GraphRAG indexing failed in {len(failures)} workflow(s)")
        output = workspace / "output"
        tables = {
            "documents": self._read_table(output, "documents"),
            "text_units": self._read_table(output, "text_units"),
            "entities": self._read_table(output, "entities"),
            "relationships": self._read_table(output, "relationships"),
            "communities": self._read_table(output, "communities"),
            "community_reports": self._read_table(output, "community_reports"),
            "covariates": self._read_table(output, "covariates", required=False),
        }
        document_sources: dict[str, SourceTextSnapshot] = {}
        for row in tables["documents"].to_dict("records"):
            title = Path(str(row.get("title") or row.get("name") or "")).name
            source = aliases.get(title) or aliases.get(Path(title).stem)
            if source is not None:
                document_sources[str(row.get("id"))] = source
        extra = SimpleNamespace(
            runner=runner,
            config=config,
            tables=tables,
            document_sources=document_sources,
        )
        return _Built(kb, workspace, extra)

    @staticmethod
    def _records(context: Any) -> list[dict[str, Any]]:
        frames: Iterable[Any]
        if isinstance(context, dict):
            frames = context.values()
        elif isinstance(context, list):
            frames = context
        else:
            frames = (context,)
        output = []
        for frame in frames:
            if callable(getattr(frame, "to_dict", None)):
                output.extend(frame.to_dict("records"))
        return output

    def retrieve(self, built: _Built, *, query: str, top_k: int) -> list[RetrievalCandidate]:
        tables = built.extra.tables
        kwargs = {
            "config": built.extra.config,
            "entities": tables["entities"],
            "communities": tables["communities"],
            "community_reports": tables["community_reports"],
            "text_units": tables["text_units"],
            "relationships": tables["relationships"],
            "covariates": tables["covariates"],
            "community_level": 2,
            "response_type": "Multiple Paragraphs",
            "query": query,
        }
        kwargs.update(self.search_kwargs)
        _, context = built.extra.runner.run(self.runtime.api.local_search(**kwargs))
        text_units = {
            str(row.get("id")): row for row in tables["text_units"].to_dict("records")
        }
        output = []
        for ordinal, row in enumerate(self._records(context)):
            unit = text_units.get(str(row.get("id"))) or row
            document_ids = unit.get("document_ids") or unit.get("document_id") or []
            if isinstance(document_ids, str):
                document_ids = [document_ids]
            source = next(
                (built.extra.document_sources.get(str(doc_id)) for doc_id in document_ids
                 if built.extra.document_sources.get(str(doc_id)) is not None),
                None,
            )
            if source is None:
                continue
            text = str(unit.get("text") or unit.get("content") or row.get("text") or "")
            if not text:
                continue
            output.append(_candidate(
                engine_id=self.engine_id,
                kb_id=built.kb.kb_id,
                source=source,
                chunk_id=str(unit.get("id") or f"graphrag-{ordinal}"),
                text=text,
                score=_score(row.get("score") or row.get("rank"), 1.0 / (ordinal + 1)),
                ordinal=ordinal,
                locator=_locator(unit, filename=source.filename),
                raw_citation={"upstream": "graphrag", "text_unit_id": str(unit.get("id") or "")},
            ))
            if len(output) >= top_k:
                break
        if self._records(context) and not output:
            raise ExactRagProvenanceError(
                "GraphRAG context could not be mapped through documents.parquet to Host Sources"
            )
        return output


class PageIndexExactAdapter:
    """Reviewed binding to the official PageIndex document/retrieval client."""

    engine_id = "pageindex"
    upstream_distribution = "pageindex"
    reviewed_version = "0.2.8 SDK reviewed 2026-08-22"

    def __init__(
        self,
        *,
        api_key: str,
        storage_root: str | Path,
        runtime: Any = None,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> None:
        if not api_key:
            raise ExactRagDependencyError("PageIndex API key must be supplied from server-side secret storage")
        if runtime is None:
            _checked_distribution(self.upstream_distribution, ("0.2.8",))
            from pageindex import PageIndexClient

            runtime = SimpleNamespace(PageIndexClient=PageIndexClient)
        self.client = runtime.PageIndexClient(api_key=api_key)
        self.storage_root = Path(storage_root)
        self.poll_interval = poll_interval
        self.timeout = timeout

    def _wait(self, getter: Callable[[str], Mapping[str, Any]], operation_id: str) -> Mapping[str, Any]:
        deadline = time.monotonic() + self.timeout
        while True:
            payload = getter(operation_id)
            status = str(payload.get("status") or "").lower()
            if status in {"completed", "complete", "success", "succeeded", "ready"}:
                return payload
            if status in {"failed", "error", "cancelled"}:
                raise ExactRagAdapterError(f"PageIndex operation failed: {payload}")
            if time.monotonic() >= deadline:
                raise ExactRagAdapterError("PageIndex operation timed out")
            time.sleep(self.poll_interval)

    @staticmethod
    def _operation_id(payload: Mapping[str, Any], *keys: str) -> str:
        value = next((payload.get(key) for key in keys if payload.get(key)), "")
        if not value:
            raise ExactRagAdapterError(f"PageIndex response omitted operation id: {payload}")
        return str(value)

    def build(self, kb: KnowledgeBaseSnapshot) -> _Built:
        digest = hashlib.sha256(f"{kb.kb_id}:{kb.fingerprint}".encode()).hexdigest()[:16]
        input_dir = self.storage_root / f"{kb.kb_id}-{digest}" / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        documents: dict[str, SourceTextSnapshot] = {}
        for source in kb.sources:
            if not source.original_bytes:
                raise ExactRagAdapterError(
                    f"PageIndex requires original Host bytes for Source {source.source_id}"
                )
            path = input_dir / source.filename
            path.write_bytes(source.original_bytes)
            submitted = self.client.submit_document(str(path))
            doc_id = self._operation_id(submitted, "doc_id", "document_id")
            getter = getattr(self.client, "get_document", None) or getattr(self.client, "get_tree_result")
            self._wait(getter, doc_id)
            documents[doc_id] = source
        return _Built(kb, documents)

    @staticmethod
    def _hits(payload: Any) -> list[Mapping[str, Any]]:
        output: list[Mapping[str, Any]] = []
        if isinstance(payload, list):
            for item in payload:
                output.extend(PageIndexExactAdapter._hits(item))
        elif isinstance(payload, dict):
            has_text = any(payload.get(key) for key in ("text", "content", "snippet", "summary"))
            if has_text and any(key in payload for key in ("page", "page_number", "start_index", "node_id", "score")):
                output.append(payload)
            else:
                for key in ("result", "results", "retrieval", "nodes", "data", "matches"):
                    if key in payload:
                        output.extend(PageIndexExactAdapter._hits(payload[key]))
        return output

    def retrieve(self, built: _Built, *, query: str, top_k: int) -> list[RetrievalCandidate]:
        output = []
        for doc_id, source in built.upstream.items():
            submit_query = getattr(self.client, "submit_query", None) or getattr(
                self.client, "submit_retrieval_query"
            )
            submitted = submit_query(doc_id, query, thinking=False)
            retrieval_id = self._operation_id(submitted, "retrieval_id", "id")
            get_retrieval = getattr(self.client, "get_retrieval", None) or getattr(
                self.client, "get_retrieval_result"
            )
            payload = self._wait(get_retrieval, retrieval_id)
            for row in self._hits(payload):
                ordinal = len(output)
                text = str(row.get("text") or row.get("content") or row.get("snippet") or row.get("summary") or "")
                output.append(_candidate(
                    engine_id=self.engine_id,
                    kb_id=built.kb.kb_id,
                    source=source,
                    chunk_id=str(row.get("node_id") or row.get("id") or f"pageindex-{ordinal}"),
                    text=text,
                    score=_score(row.get("score") or row.get("relevance_score"), 1.0 / (ordinal + 1)),
                    ordinal=ordinal,
                    locator=_locator(row, filename=source.filename),
                    raw_citation={"upstream": "pageindex", "doc_id": doc_id},
                ))
        output.sort(key=lambda item: item.score, reverse=True)
        return output[:top_k]


__all__ = [
    "LlamaIndexExactAdapter",
    "LightRagExactAdapter",
    "GraphRagExactAdapter",
    "PageIndexExactAdapter",
]

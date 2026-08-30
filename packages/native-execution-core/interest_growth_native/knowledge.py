from __future__ import annotations

import hashlib, json, re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .capabilities import CAP_KNOWLEDGE
from .context import NativeRunContext
from .contracts import KnowledgeBaseSnapshot, KnowledgeResolver, SourceLocator
from .errors import AreaIsolationError, ExactRagProvenanceError
from .rag import RetrievalChunk, RagEngineRegistry

def _source_fp(source) -> str:
    if source.fingerprint:
        return source.fingerprint
    return hashlib.sha256(source.text.encode("utf-8")).hexdigest()

def effective_kb_fingerprint(kb: KnowledgeBaseSnapshot) -> str:
    payload = {
        "kb_id": kb.kb_id,
        "declared": kb.fingerprint,
        "engine_id": kb.engine_id,
        "engine_config": kb.engine_config,
        "sources": [
            {
                "source_id": s.source_id,
                "fingerprint": _source_fp(s),
                "filename": s.filename,
                "locator": {
                    "page": s.locator.page,
                    "section": s.locator.section,
                    "slide": s.locator.slide,
                    "sheet": s.locator.sheet,
                    "cell_range": s.locator.cell_range,
                },
            }
            for s in kb.sources
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def collision_safe_adapter_snapshot(kb: KnowledgeBaseSnapshot) -> KnowledgeBaseSnapshot:
    """Return an adapter-facing whole-KB snapshot with collision-safe filenames.

    v0.3 encoded Source identity into upstream filenames so two local Sources
    named `paper.pdf` could never overwrite each other. Exact third-party
    adapters receive the same safety property while source_id remains explicit.
    """
    safe_sources=[]
    for source in kb.sources:
        name=Path(source.filename or "source").name
        suffix=re.sub(r"[^A-Za-z0-9.]", "", Path(name).suffix)[:16]
        base=name[:-len(suffix)] if suffix else name
        source_hash=hashlib.sha256(source.source_id.encode()).hexdigest()[:12]
        sid=re.sub(r"[^A-Za-z0-9_-]+","-",source.source_id).strip("-")[:48] or "source"
        base=re.sub(r"[^A-Za-z0-9._-]+","-",base).strip("-") or "source"
        alias=f"{sid}-{source_hash}__{base}{suffix}"
        safe_sources.append(replace(source,filename=alias))
    return replace(kb,sources=tuple(safe_sources))

def _split_source(kb_id: str, source, *, target=900, overlap=100):
    text = re.sub(r"\r\n?", "\n", source.text).strip()
    if not text: return []
    parts=[]; start=0; ordinal=0
    while start < len(text):
        end=min(len(text),start+target)
        piece=text[start:end]
        loc=replace(
            source.locator,
            filename=source.filename or source.locator.filename,
            char_start=(
                (source.locator.char_start or 0)+start
                if source.locator.char_start is not None else start
            ),
            char_end=(
                (source.locator.char_start or 0)+end
                if source.locator.char_start is not None else end
            ),
        )
        cid=hashlib.sha256(
            f"{kb_id}|{source.source_id}|{_source_fp(source)}|{ordinal}|{start}|{end}".encode()
        ).hexdigest()[:24]
        parts.append(RetrievalChunk(
            id=cid, kb_id=kb_id, source_id=source.source_id,
            source_fingerprint=_source_fp(source),
            filename=source.filename, text=piece, ordinal=ordinal,
            locator=loc, metadata=dict(source.metadata),
        ))
        if end >= len(text): break
        start=max(start+1,end-overlap); ordinal+=1
    return parts

class NativeRetrievalEngine:
    """Read-only retrieval over host-owned KB/Source snapshots."""
    def __init__(self, resolver: KnowledgeResolver, registry: RagEngineRegistry | None = None):
        self.resolver=resolver; self.registry=registry or RagEngineRegistry()
        self._cache: dict[tuple[str,str,str], Any]={}

    def _resolve(self, context, kb_ids):
        found=self.resolver.resolve(area_id=context.area_id,kb_ids=tuple(kb_ids))
        found_ids={x.kb_id for x in found}
        missing=set(kb_ids)-found_ids
        if missing:
            raise AreaIsolationError(f"KB unavailable in current Area: {sorted(missing)}")
        return found

    def _built(self,kb):
        fp=effective_kb_fingerprint(kb)
        key=(kb.kb_id,fp,kb.engine_id)
        if key in self._cache:return self._cache[key]
        exact=self.registry.exact(kb.engine_id)
        if exact is not None:
            adapter_kb=collision_safe_adapter_snapshot(kb)
            built=("exact", exact, exact.build(adapter_kb), kb)
        elif kb.engine_id in self.registry._native:
            chunks=[]
            for s in kb.sources: chunks.extend(_split_source(kb.kb_id,s))
            built=("native", self.registry.native_factory(kb.engine_id)(chunks))
        else:
            raise KeyError(f"unknown RAG engine: {kb.engine_id}")
        # Drop older cache generations for the same KB/engine.
        for old in [x for x in self._cache if x[0]==kb.kb_id and x[2]==kb.engine_id and x!=key]:
            del self._cache[old]
        self._cache[key]=built
        return built

    def retrieve(self,context:NativeRunContext,*,kb_ids,query,top_k=6):
        context.require_capability(CAP_KNOWLEDGE)
        context.permission_scope.require_read("knowledge")
        merged=[]
        for kb in self._resolve(context,kb_ids):
            built=self._built(kb)
            if built[0]=="native":
                merged.extend(built[1].search(query,top_k=top_k))
            else:
                _,adapter,index,original_kb=built
                candidates=adapter.retrieve(index,query=query,top_k=top_k)
                source_map={s.source_id:s for s in original_kb.sources}
                normalized=[]
                for candidate in candidates:
                    source=source_map.get(candidate.source_id)
                    if source is None:
                        raise ExactRagProvenanceError(
                            f"{kb.engine_id} returned an unmappable Source ID; result rejected"
                        )
                    if candidate.engine_id != kb.engine_id:
                        raise ExactRagProvenanceError(
                            f"{kb.engine_id} adapter returned engine_id={candidate.engine_id!r}"
                        )
                    mapped_locator=(
                        source.locator if candidate.locator==SourceLocator()
                        else replace(candidate.locator, filename=source.filename)
                    )
                    candidate=replace(
                        candidate,
                        kb_id=kb.kb_id,
                        filename=source.filename,
                        source_fingerprint=_source_fp(source),
                        locator=mapped_locator,
                    )
                    normalized.append(candidate)
                merged.extend(normalized)
        merged.sort(key=lambda x:x.score,reverse=True)
        return merged[:top_k]

    def prepare(self, context: NativeRunContext, *, kb_ids) -> tuple[str, ...]:
        """Build exact/native projections while Host retains ingestion-run truth."""
        context.require_capability(CAP_KNOWLEDGE)
        context.permission_scope.require_read("knowledge")
        prepared = []
        for kb in self._resolve(context, kb_ids):
            self._built(kb)
            prepared.append(effective_kb_fingerprint(kb))
        return tuple(prepared)

    def invalidate(self,kb_id:str):
        for key in [x for x in self._cache if x[0]==kb_id]:del self._cache[key]

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..contracts import SourceLocator

@dataclass(frozen=True, slots=True)
class RetrievalChunk:
    id: str
    kb_id: str
    source_id: str
    source_fingerprint: str
    filename: str
    text: str
    ordinal: int
    locator: SourceLocator = field(default_factory=SourceLocator)
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: str
    kb_id: str
    source_id: str
    source_fingerprint: str
    filename: str
    score: float
    text: str
    ordinal: int
    locator: SourceLocator
    engine_id: str
    raw_citation: dict[str, Any] = field(default_factory=dict)
    status: str = "candidate_not_evidence"

    def public_source(self) -> dict[str, Any]:
        return {
            "kb_id": self.kb_id,
            "source_id": self.source_id,
            "source_fingerprint": self.source_fingerprint,
            "filename": self.filename,
            "chunk_id": self.chunk_id,
            "score": self.score,
            "engine_id": self.engine_id,
            "location": {
                "page": self.locator.page,
                "section": self.locator.section,
                "char_start": self.locator.char_start,
                "char_end": self.locator.char_end,
                "slide": self.locator.slide,
                "sheet": self.locator.sheet,
                "cell_range": self.locator.cell_range,
            },
            "excerpt": self.text[:1200],
            "status": self.status,
        }

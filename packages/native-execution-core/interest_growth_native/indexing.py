from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from .contracts import KnowledgeBaseSnapshot

@dataclass(frozen=True,slots=True)
class IndexBuildTicket:
    kb_id:str
    engine_id:str
    task_id:str
    effective_fingerprint:str

@dataclass(frozen=True,slots=True)
class IndexBuildStatus:
    task_id:str
    state:str
    progress:float|None=None
    message:str=""
    error_type:str=""

class WholeKbAsyncIndexAdapter(Protocol):
    """Optional exact-engine ingestion contract.

    Host `KnowledgeIngestionRun` remains authoritative for task identity/state.
    The adapter receives one whole-KB snapshot per rebuild; it must not expose
    fake per-Source progress as product truth.
    """
    engine_id:str
    def start_build(self,kb:KnowledgeBaseSnapshot)->IndexBuildTicket: ...
    def poll(self,ticket:IndexBuildTicket)->IndexBuildStatus: ...
    def cancel(self,ticket:IndexBuildTicket)->None: ...

def verify_task_identity(ticket:IndexBuildTicket,status:IndexBuildStatus)->None:
    if status.task_id!=ticket.task_id:
        raise ValueError("index task-id mismatch; completion must not be attributed to another run")

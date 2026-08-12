from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .context import NativeRunContext
from .execution_store import SQLiteExecutionStore

@dataclass(frozen=True,slots=True)
class AgentMemoryRecord:
    id:str;layer:str;kind:str;content:str;source_run_id:str|None;metadata:dict[str,Any]

class AgentMemoryExecutor:
    ALLOWED={"working","session_summary","retrieval_hint"}
    def __init__(self,store:SQLiteExecutionStore):self.store=store
    def write(self,context:NativeRunContext,*,layer,kind,content,source_run_id=None,metadata=None):
        context.permission_scope.require_write("agent_memory")
        if layer not in self.ALLOWED:raise ValueError("invalid auxiliary memory layer")
        mid=self.store.write_aux_memory(area_id=context.area_id,session_id=context.session_id,layer=layer,kind=kind,content=content,source_run_id=source_run_id,metadata=metadata or {})
        return AgentMemoryRecord(mid,layer,kind,content,source_run_id,metadata or {})
    def read(self,context:NativeRunContext,*,limit=30):
        context.permission_scope.require_read("agent_memory")
        rows=self.store.read_aux_memory(area_id=context.area_id,session_id=context.session_id,limit=limit)
        return tuple(AgentMemoryRecord(r["id"],r["layer"],r["kind"],r["content"],r["source_run_id"],self.store.loads(r["metadata_json"],{})) for r in rows)
    def audit_graph(self,context:NativeRunContext):
        nodes=[];edges=[];seen=set()
        for r in self.read(context,limit=500):
            mid=f"memory:{r.id}";nodes.append({"id":mid,"type":"agent_memory","layer":r.layer,"kind":r.kind,"content_preview":r.content[:160]})
            if r.source_run_id:
                rid=f"run:{r.source_run_id}"
                if rid not in seen:nodes.append({"id":rid,"type":"tutor_run"});seen.add(rid)
                edges.append({"from":rid,"to":mid,"relation":"produced_auxiliary_memory"})
        return {"nodes":nodes,"edges":edges,"authoritative_growth_memory":False}

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Protocol
from .llm import LLMClient,LLMStreamEvent

@dataclass(frozen=True,slots=True)
class UsageEvent:
    capability_id:str
    latency_ms:int
    input_tokens:int|None=None
    output_tokens:int|None=None
    total_tokens:int|None=None
    model:str=""
    estimated_cost:float|None=None

class UsageSink(Protocol):
    def record(self,event:UsageEvent)->None: ...

def _usage_fields(usage):
    usage=usage or {}
    return (
        usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"),int) else usage.get("input_tokens"),
        usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"),int) else usage.get("output_tokens"),
        usage.get("total_tokens"),
    )

class ObservedLLMClient:
    def __init__(self,inner:LLMClient,*,capability_id:str,sink:UsageSink|None=None,model=""):
        self.inner=inner;self.capability_id=capability_id;self.sink=sink;self.model=model
    @property
    def available(self):return bool(getattr(self.inner,"available",False))
    def _record(self,start,usage=None):
        if not self.sink:return
        inp,out,total=_usage_fields(usage)
        self.sink.record(UsageEvent(self.capability_id,int((time.perf_counter()-start)*1000),inp,out,total,self.model))
    def complete(self,**kwargs):
        start=time.perf_counter()
        try:
            response=self.inner.complete(**kwargs)
        except Exception:
            self._record(start,None);raise
        self._record(start,response.usage)
        return response
    def stream(self,**kwargs):
        start=time.perf_counter();usage=None
        if not hasattr(self.inner,"stream"):
            try:r=self.inner.complete(**kwargs)
            except Exception:
                self._record(start,None);raise
            if r.text:
                visible=r.text_visibility=="answer" or (r.text_visibility=="auto" and not r.tool_calls)
                yield LLMStreamEvent("answer_delta" if visible else "narration_delta",text=r.text)
            for c in r.tool_calls:yield LLMStreamEvent("tool_call",tool_call=c)
            usage=r.usage
            yield LLMStreamEvent("done",usage=r.usage,finish_reason=r.finish_reason)
            self._record(start,usage)
            return
        try:
            for event in self.inner.stream(**kwargs):
                if event.usage:usage=event.usage
                yield event
        except Exception:
            self._record(start,usage);raise
        self._record(start,usage)

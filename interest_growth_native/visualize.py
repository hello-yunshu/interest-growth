from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
from .capabilities import CAP_VISUALIZE
from .context import NativeRunContext
from .contracts import GroundingRefSnapshot
from .signals import LearningActivityCandidate

@dataclass(frozen=True,slots=True)
class VisualizationArtifact:
    kind:str
    title:str
    spec:dict[str,Any]
    fingerprint:str
    grounding_refs:tuple[GroundingRefSnapshot,...]
    activity:LearningActivityCandidate
    review_required:bool=True

class NativeVisualizationExecutor:
    def plan(self,context:NativeRunContext,*,title:str,content:str,kind="concept_map",grounding_refs=()):
        context.require_capability(CAP_VISUALIZE)
        spec={"schema_version":"interest-growth.visual.v1","kind":kind,"title":title,"nodes":[{"id":"root","label":title},{"id":"content","label":content[:500]}],"edges":[{"from":"root","to":"content"}],"status":"review_required"}
        fp=hashlib.sha256(json.dumps(spec,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        act=LearningActivityCandidate(context.area_id,context.session_id,CAP_VISUALIZE,"visualization_plan",f"Prepared reviewable visualization: {title}")
        return VisualizationArtifact(kind,title,spec,fp,tuple(grounding_refs),act,True)

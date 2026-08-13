from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True,slots=True)
class AnimationPlan:
    title:str;scenes:tuple[dict,...];render_backend:str="external_or_manual";review_required:bool=True
class NativeMathAnimator:
    def plan(self,*,title:str,steps:list[str]):
        return AnimationPlan(title,tuple({"scene":i+1,"caption":s,"visual":"diagram_or_equation","duration_hint_seconds":4} for i,s in enumerate(steps)))

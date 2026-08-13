from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pg_domain import CapabilityStatus, ResearchPlan, ResearchResult
from pg_engine_contracts import ResearchEngine

from .provider import DeepSeekProvider


class PlanPayload(BaseModel):
    brief: str
    subquestions: list[str] = Field(min_length=1, max_length=8)
    desired_sources: list[str] = Field(default_factory=list)


class DeepSeekResearchEngine(ResearchEngine):
    """Limited fallback. Model output never becomes verified evidence automatically."""

    def __init__(self, provider: DeepSeekProvider, domain_context: dict[str, Any] | None = None):
        self.provider = provider
        self.domain_context = domain_context or {}

    def _research_policy(self) -> dict[str, Any]:
        return dict(self.domain_context.get("research") or {})

    async def create_plan(self, question: str, depth: str = "normal") -> ResearchPlan:
        policy = self._research_policy()
        domain_name = str(self.domain_context.get("domain_name") or "current interest")
        planner_system = str(policy.get("planner_system") or (
            "You decompose a learning/research question without assuming a subject. "
            "Distinguish original sources, practical evidence, interpretation, uncertainty, and verification."
        ))
        prompt = (
            f"Domain: {domain_name}\nQuestion: {question}\nDepth: {depth}\n"
            "Create a compact research/learning plan appropriate to this domain."
        )
        payload = await self.provider.structured(prompt, PlanPayload, system=planner_system)
        return ResearchPlan(
            question=question,
            brief=payload.brief,
            subquestions=payload.subquestions,
            desired_sources=payload.desired_sources,
            depth=depth,
        )

    async def run(self, plan: ResearchPlan) -> ResearchResult:
        domain_name = str(self.domain_context.get("domain_name") or "current interest")
        policy = self._research_policy()
        prompt = (
            f"Domain: {domain_name}\nResearch question: {plan.question}\nBrief: {plan.brief}\n"
            f"Subquestions: {plan.subquestions}\n"
            "Create a limited learning/research draft. Explicitly mark what is only a lead that still needs verification. "
            "Do not claim you read a source unless it was actually retrieved, and do not label model knowledge as verified evidence."
        )
        report = await self.provider.text(prompt, system=str(policy.get("planner_system") or "Be careful, domain-appropriate, and explicit about uncertainty."))
        return ResearchResult(
            status=CapabilityStatus.DEGRADED,
            provider="deepseek-limited",
            report=report,
            limitations=[
                "Limited LLM fallback; no retrieved source is automatically verified.",
                "Model-generated citations or factual leads must not be promoted directly to verified Evidence.",
                "Original/source-level material still requires user review when verification matters.",
            ],
        )

    def normalize_result(self, raw: dict) -> ResearchResult:
        return ResearchResult(
            status=CapabilityStatus.DEGRADED,
            provider="deepseek-limited",
            report=str(raw.get("report") or raw.get("content") or ""),
            raw=raw,
            limitations=["Limited LLM result; verification policy is supplied by the active Domain Pack."],
        )

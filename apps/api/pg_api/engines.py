from __future__ import annotations

from typing import Any

from pg_deepseek import DeepSeekProvider, DeepSeekResearchEngine
from pg_domain import CapabilityStatus, ResearchPlan, ResearchResult
from pg_engine_contracts import ResearchEngine
from pg_shared import get_settings

from .domains import DomainContext, get_domain_context


def _context_payload(context: DomainContext) -> dict[str, Any]:
    return {
        "area_id": context.area_id,
        "area_name": context.area_name,
        "domain_pack_id": context.domain_pack_id,
        "domain_name": context.domain_name,
        "research": context.research,
        "quick_explore": context.quick_explore,
        "content": context.content,
        "skills": context.skills,
        "personas": context.personas,
        "mastery_profile_id": context.mastery_profile_id,
    }


class ManualResearchEngine(ResearchEngine):
    def __init__(self, domain_context: dict[str, Any] | None = None):
        self.domain_context = domain_context or {}

    async def create_plan(self, question: str, depth: str = "normal") -> ResearchPlan:
        policy = dict(self.domain_context.get("research") or {})
        template = str(policy.get("brief_template") or "为“{question}”建立手工学习/研究工作区。")
        return ResearchPlan(
            question=question,
            brief=template.format(question=question),
            subquestions=[str(x) for x in policy.get("subquestions", [])] or [
                "先澄清核心对象、概念或技能。",
                "寻找当前领域合适的权威/原始资料、实例或实践示范。",
                "记录相反观点、失败案例、边界条件和不确定性。",
                "选择一个最小下一步阅读、观察、实验或练习。",
            ],
            desired_sources=[str(x) for x in policy.get("desired_sources", [])] or [
                "authoritative overview", "primary/original material", "worked example"
            ],
            depth=depth,
        )

    async def run(self, plan: ResearchPlan) -> ResearchResult:
        return ResearchResult(
            status=CapabilityStatus.DEGRADED,
            provider="manual-workspace",
            report=(
                "当前未连接可用的外部研究 Provider。工作区已保留。\n\n"
                "建议按以下子问题逐项补充资料或实践记录：\n- " + "\n- ".join(plan.subquestions)
            ),
            limitations=[
                "未执行自动深度检索。",
                "不会把未核验模型知识伪装成 Evidence。",
                "你仍可手动添加 Source / Note / Practice / Evidence / Claim。",
            ],
        )

    def normalize_result(self, raw: dict[str, Any]) -> ResearchResult:
        return ResearchResult(
            status=CapabilityStatus.DEGRADED,
            provider="manual-workspace",
            report=str(raw.get("report") or ""),
            raw=raw,
        )


async def choose_research_engine(*, deep_research_allowed: bool = True,
                                 domain_context: DomainContext | None = None) -> tuple[ResearchEngine, dict[str, Any]]:
    settings = get_settings()
    context = domain_context or get_domain_context()
    payload = _context_payload(context)
    provider = DeepSeekProvider(
        settings.deepseek_api_key,
        settings.deepseek_base_url,
        settings.deepseek_model,
        settings.deepseek_timeout_seconds,
    )
    if provider.configured:
        return DeepSeekResearchEngine(provider, payload), {
            "engine": "deepseek-limited",
            "degraded": True,
            "reason": (
                "FEATURE_DEEP_RESEARCH disabled; using limited LLM workspace"
                if not deep_research_allowed
                else "Native LLM transport configured"
            ),
            "domain_pack_id": context.domain_pack_id,
            "area_id": context.area_id,
        }

    return ManualResearchEngine(payload), {
        "engine": "manual-workspace",
        "degraded": True,
        "reason": (
            "FEATURE_DEEP_RESEARCH disabled; using manual workspace"
            if not deep_research_allowed
            else "No external engine configured"
        ),
        "domain_pack_id": context.domain_pack_id,
        "area_id": context.area_id,
    }


async def integration_status() -> dict[str, Any]:
    settings = get_settings()
    from .native_execution import get_native_bundle
    native = get_native_bundle().health()
    return {
        "native_execution": native,
        "deepseek": {
            "configured": bool(settings.deepseek_api_key.strip()),
            "model": settings.deepseek_model,
        },
    }


async def quick_explore_question(question: str, focus: str = "", domain_context: DomainContext | None = None) -> dict[str, Any]:
    """Low-friction exploration. Never creates Source/Evidence/Claim automatically."""
    settings = get_settings()
    context = domain_context or get_domain_context()
    quick = context.quick_explore
    provider = DeepSeekProvider(
        settings.deepseek_api_key,
        settings.deepseek_base_url,
        settings.deepseek_model,
        min(settings.deepseek_timeout_seconds, 30),
    )
    focus_text = focus or "暂无"
    template = str(quick.get("template") or (
        "兴趣问题：{question}\n用户特别想看：{focus}\n"
        "用几个短要点做轻量探索，并给出一个最小下一步；明确这不是已核验证据。"
    ))
    prompt = template.format(question=question, focus=focus_text)
    if provider.configured:
        try:
            text = await provider.text(
                prompt,
                system=str(quick.get("system") or "帮助用户降低开始学习的门槛，简短、诚实、不虚构来源。"),
            )
            return {
                "provider": "deepseek-quick",
                "degraded": False,
                "content": text,
                "evidence_status": "not_evidence",
                "area_id": context.area_id,
                "domain_pack_id": context.domain_pack_id,
                "next_actions": ["现在结束", "暂停以后再回来", "转为 Topic", "进入 Research/Practice"],
            }
        except Exception as exc:
            reason = type(exc).__name__
    else:
        reason = "DeepSeek not configured"

    manual_template = str(quick.get("manual_template") or quick.get("template") or (
        "兴趣问题：{question}\n用几个短要点指出核心概念/技能、一个易错点和一个最小下一步；明确这不是已核验证据。"
    ))
    manual = manual_template.format(question=question, focus=focus_text)
    return {
        "provider": "manual-quick",
        "degraded": True,
        "reason": reason,
        "content": manual,
        "evidence_status": "not_evidence",
        "area_id": context.area_id,
        "domain_pack_id": context.domain_pack_id,
        "next_actions": ["现在结束", "暂停以后再回来", "转为 Topic", "进入 Practice/Research"],
    }

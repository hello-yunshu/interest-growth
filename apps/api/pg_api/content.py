from __future__ import annotations

import json
import re
from pathlib import Path
from textwrap import shorten
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from pg_artifacts import LocalFilesystemStorage
from pg_deepseek import DeepSeekProvider
from pg_shared import get_settings

from .db import (
    ArtifactModel,
    CareerExperimentModel,
    ClaimModel,
    ClaimVersionModel,
    EvidenceModel,
    LearningActivityModel,
    LearningNoteModel,
    LivingBookChapterModel,
    PracticeItemModel,
    SourceModel,
    TopicModel,
    get_session_factory,
)
from .domains import get_domain_context, require_entity_in_current_area

storage = LocalFilesystemStorage(get_settings().artifact_storage_root)


def get_storage():
    return storage


GENERIC_RISK_RULES = [
    (r"一定|必然|所有人|任何人|百分之百|100%", "high", "存在绝对化表述，需要检查适用边界。"),
    (r"导致|造成", "medium", "检查是否把相关性、观察或个人经验写成了确定因果。"),
]


class AIContentDraft(BaseModel):
    title_candidates: list[str] = Field(min_length=3, max_length=5)
    body: str = Field(min_length=30, max_length=5000)
    tag_suggestions: list[str] = Field(min_length=2, max_length=10)


def _domain_risk_rules() -> list[tuple[str, str, str]]:
    context = get_domain_context()
    content = context.content
    result = list(GENERIC_RISK_RULES)
    for item in list(content.get("risk_rules") or []):
        if not isinstance(item, dict) or not item.get("pattern"):
            continue
        result.append((
            str(item["pattern"]),
            str(item.get("severity") or "high"),
            str(item.get("message") or "当前 Domain Pack 标记了需要人工复核的表达。"),
        ))
    # Compatibility with simple forbidden_patterns in custom packs.
    for pattern in list(content.get("forbidden_patterns") or []):
        result.append((str(pattern), "high", f"当前 Domain Pack 不允许直接使用该表达：{pattern}"))
    return result


def publish_guard(
    text: str,
    *,
    has_verified_evidence: bool,
    has_counter_evidence: bool,
    claims: list[dict] | None = None,
    evidence_required: bool | None = None,
) -> list[dict]:
    context = get_domain_context()
    if evidence_required is None:
        evidence_required = bool(context.content.get("evidence_required", False))
    issues: list[dict] = []
    for pattern, severity, message in _domain_risk_rules():
        matches = list(re.finditer(pattern, text, re.I))
        if not matches:
            continue
        if "所有人" in pattern or "任何人" in pattern:
            risky = False
            for match in matches:
                prefix = text[max(0, match.start() - 14):match.start()]
                if not re.search(r"(?:不|非|未必|不能|不应|避免|不可|并不|并非).{0,8}$", prefix):
                    risky = True
                    break
            if not risky:
                continue
        issues.append({"severity": severity, "code": "language_risk", "message": message})

    if claims:
        for claim in claims:
            label = shorten(claim["statement"], width=36, placeholder="…")
            if claim["verification_state"] != "human_verified":
                issues.append({"severity": "high", "code": "claim_not_human_verified", "claim_id": claim["claim_id"], "message": f"Claim「{label}」尚未 human_verified。"})
            if not claim["support_all_verified"]:
                issues.append({"severity": "high", "code": "support_not_fully_verified", "claim_id": claim["claim_id"], "message": f"Claim「{label}」的支持证据尚未全部核验。"})
            if claim["contains_ai_summary_only"]:
                issues.append({"severity": "high", "code": "ai_summary_only_source", "claim_id": claim["claim_id"], "message": f"Claim「{label}」仍依赖 ai_summary_only 来源。"})
            if claim["publishability"] in {"internal_only", "not_publishable"}:
                issues.append({"severity": "high", "code": "claim_not_publishable", "claim_id": claim["claim_id"], "message": f"Claim「{label}」当前只能内部学习/暂缓发布。"})
            if not claim["contradicting_evidence"]:
                issues.append({"severity": "medium", "code": "claim_has_no_counter_evidence", "claim_id": claim["claim_id"], "message": f"Claim「{label}」尚未记录相反/边界证据。"})
    elif evidence_required:
        if not has_verified_evidence:
            issues.append({"severity": "high", "code": "no_human_verified_evidence", "message": "当前 Domain Pack 要求事实型公开表达必须建立人工核验的 Evidence/Claim 链。"})
        if not has_counter_evidence:
            issues.append({"severity": "medium", "code": "no_counter_evidence", "message": "当前没有记录相反/边界证据。"})
    return issues


def _claim_bundle(claim_ids: list[str]) -> tuple[list[dict], bool, bool]:
    bundles: list[dict] = []
    every_claim_verified = bool(claim_ids)
    has_counter = False
    with get_session_factory()() as db:
        for claim_id in claim_ids:
            try:
                require_entity_in_current_area(db, "claim", claim_id)
            except ValueError:
                every_claim_verified = False
                continue
            claim = db.get(ClaimModel, claim_id)
            if not claim or not claim.current_version_id:
                every_claim_verified = False
                continue
            version = db.get(ClaimVersionModel, claim.current_version_id)
            if version is None:
                every_claim_verified = False
                continue
            support: list[dict] = []
            counter: list[dict] = []
            contains_ai_summary_only = False
            support_all_verified = bool(version.supporting_evidence)
            for eid in version.supporting_evidence:
                ev = db.get(EvidenceModel, eid)
                if not ev:
                    support_all_verified = False
                    continue
                src = db.get(SourceModel, ev.source_id)
                source_verified = bool(src and src.verified)
                source_ai_summary_only = bool(src and src.ai_summary_only)
                contains_ai_summary_only = contains_ai_summary_only or source_ai_summary_only
                item_verified = bool(ev.verified and source_verified and not source_ai_summary_only)
                support_all_verified = support_all_verified and item_verified
                support.append({
                    "evidence_id": ev.id, "evidence": ev.excerpt_or_summary, "verified": ev.verified,
                    "source_verified": source_verified, "source_ai_summary_only": source_ai_summary_only,
                    "source": src.title if src else "unknown", "url": src.canonical_url if src else "",
                    "limitations": ev.limitations,
                })
            for eid in version.contradicting_evidence:
                ev = db.get(EvidenceModel, eid)
                if not ev:
                    continue
                src = db.get(SourceModel, ev.source_id)
                source_ai_summary_only = bool(src and src.ai_summary_only)
                contains_ai_summary_only = contains_ai_summary_only or source_ai_summary_only
                counter.append({
                    "evidence_id": ev.id, "evidence": ev.excerpt_or_summary, "verified": ev.verified,
                    "source_verified": bool(src and src.verified), "source_ai_summary_only": source_ai_summary_only,
                    "source": src.title if src else "unknown", "url": src.canonical_url if src else "",
                    "limitations": ev.limitations,
                })
                has_counter = True
            claim_ready = (
                claim.verification_state == "human_verified"
                and support_all_verified
                and claim.publishability not in {"internal_only", "not_publishable"}
                and not contains_ai_summary_only
            )
            every_claim_verified = every_claim_verified and claim_ready
            bundles.append({
                "claim_id": claim.id, "statement": version.statement, "limitations": version.limitations,
                "confidence": claim.confidence, "publishability": claim.publishability,
                "verification_state": claim.verification_state, "supporting_evidence": support,
                "contradicting_evidence": counter, "support_all_verified": support_all_verified,
                "contains_ai_summary_only": contains_ai_summary_only, "ready_for_expression": claim_ready,
            })
    return bundles, every_claim_verified and bool(bundles), has_counter


_GROUNDING_MODELS: dict[str, tuple[type, str]] = {
    "source": (SourceModel, "source"),
    "note": (LearningNoteModel, "learning_note"),
    "practice": (PracticeItemModel, "practice_item"),
    "activity": (LearningActivityModel, "learning_activity"),
    "book_chapter": (LivingBookChapterModel, "living_book_chapter"),
    "artifact": (ArtifactModel, "artifact"),
    "project": (CareerExperimentModel, "career_experiment"),
}


def _grounding_bundle(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    with get_session_factory()() as db:
        for ref in refs:
            ref_type = str(ref.get("ref_type") or "")
            ref_id = str(ref.get("ref_id") or "")
            role = str(ref.get("role") or "grounding")
            if ref_type == "claim":
                # Claim details are represented by the authoritative Claim bundle.
                continue
            spec = _GROUNDING_MODELS.get(ref_type)
            if spec is None:
                raise ValueError(f"unsupported grounding reference type: {ref_type}")
            model, entity_type = spec
            row = db.get(model, ref_id)
            if row is None:
                raise ValueError(f"grounding reference not found: {ref_type}:{ref_id}")
            if entity_type != "learning_activity":
                require_entity_in_current_area(db, entity_type, ref_id)
            else:
                context = get_domain_context()
                if row.area_id != context.area_id:
                    raise ValueError("learning activity does not belong to current interest area")
            summary = ""
            title = ""
            verified: bool | None = None
            if isinstance(row, SourceModel):
                title, summary, verified = row.title, (row.abstract or row.notes or ""), bool(row.verified)
            elif isinstance(row, LearningNoteModel):
                title, summary = row.title, row.body_markdown
            elif isinstance(row, PracticeItemModel):
                title, summary = "Practice", row.prompt
            elif isinstance(row, LearningActivityModel):
                title = row.objective or row.activity_type
                summary = row.observation or row.self_assessment or row.feedback
            elif isinstance(row, LivingBookChapterModel):
                title, summary = row.title, row.summary or row.content_markdown
            elif isinstance(row, ArtifactModel):
                title, summary = row.title, json.dumps(row.metadata_json or {}, ensure_ascii=False)
            elif isinstance(row, CareerExperimentModel):
                title, summary = row.direction, row.reflection or row.evidence or row.experiment
            output.append({
                "ref_type": ref_type, "ref_id": ref_id, "role": role, "title": title,
                "summary": shorten((summary or "").replace("\n", " "), width=500, placeholder="…"),
                "verified": verified,
                "grounding_status": "personal_or_practice_record" if ref_type not in {"source"} else ("verified_source" if verified else "unverified_source"),
            })
    return output


def publish_guard_for_claim_ids(text: str, claim_ids: list[str]) -> list[dict]:
    claims, all_verified, has_counter = _claim_bundle(claim_ids)
    combined_text = "\n".join([text, *[c["statement"] for c in claims]])
    return publish_guard(combined_text, has_verified_evidence=all_verified, has_counter_evidence=has_counter, claims=claims or None)


def build_publish_pack(
    topic_id: str,
    claim_ids: list[str],
    audience: str,
    platform: str,
    *,
    grounding_refs: list[dict[str, Any]] | None = None,
    include_media_prompts: bool = True,
) -> dict:
    context = get_domain_context()
    with get_session_factory()() as db:
        topic = db.get(TopicModel, topic_id)
        if not topic:
            raise ValueError("topic not found")
        require_entity_in_current_area(db, "topic", topic_id)
        title = topic.title

    grounding_refs = grounding_refs or []
    claims, _, _ = _claim_bundle(claim_ids)
    groundings = _grounding_bundle(grounding_refs)
    evidence_required = bool(context.content.get("evidence_required", False))
    if evidence_required and not claims:
        raise ValueError("current Domain Pack requires at least one local Claim/Evidence chain for public factual content")
    if not claims and not groundings:
        raise ValueError("select at least one Claim or GroundingRef")

    safe_claims = [c for c in claims if c["ready_for_expression"]]
    expression_claims = safe_claims or claims
    if claims:
        title_candidates = [
            f"关于「{title}」，我最近修正了一个过度简单的理解",
            f"学习 {title} 时，最值得先区分的 3 件事",
            f"{title}：目前可以说到哪里，还有哪些边界？",
        ]
        body_lines = [f"这是我目前对「{title}」的阶段性学习整理。", ""]
        for i, item in enumerate(expression_claims, 1):
            body_lines.append(f"{i}. {item['statement']}")
            if item["limitations"]:
                body_lines.append(f"   边界：{item['limitations']}")
    else:
        title_candidates = [
            f"学习「{title}」时，我最近留下的一个实践记录",
            f"{title}：这次练习/观察让我注意到什么？",
            f"关于 {title}，先记录过程，不急着得出结论",
        ]
        body_lines = [f"这是我对「{title}」的一次学习/实践记录，不把个人体验自动推广成普遍结论。", ""]
    if groundings:
        body_lines += ["", "这次记录主要基于："]
        for item in groundings[:8]:
            body_lines.append(f"- {item['title'] or item['ref_type']}：{item['summary'] or '（仅记录引用关系）'}")
    body_lines += ["", "后续如果出现更好的资料、实践反馈或反例，我会继续修正。"]
    body = "\n".join(body_lines)

    cards = [{"layout": "cover", "title": title_candidates[0], "purpose": "建立主题与边界"}]
    for item in expression_claims[:5]:
        cards.append({"layout": "evidence", "title": shorten(item["statement"], width=42, placeholder="…"), "purpose": "呈现 Claim、证据与限制", "claim_id": item["claim_id"]})
    for item in groundings[:5 if not expression_claims else 2]:
        cards.append({"layout": "three_points", "title": shorten(item["title"] or item["summary"], width=42, placeholder="…"), "purpose": "呈现学习/实践 Grounding", "grounding_ref": {"ref_type": item["ref_type"], "ref_id": item["ref_id"]}})
    cards.append({"layout": "closing", "title": "把结论留在当前材料允许的位置", "purpose": "收束并保留继续修正空间"})

    tags = list(context.content.get("tags") or ["兴趣学习", "学习记录"])
    image_prompts: list[dict[str, Any]] = []
    if include_media_prompts:
        for index, card in enumerate(cards, 1):
            image_prompts.append({
                "page": index, "purpose": card["purpose"],
                "composition": "竖版信息卡，标题区清晰，正文区留充足呼吸感，避免信息堆叠",
                "subject": card["title"],
                "style": "calm editorial learning note, domain-aware, minimal, no fake source screenshots",
                "palette": "warm neutral with one restrained accent",
                "text_safe_zone": "四周至少保留 8% 安全边距；顶部避免复杂背景",
                "forbidden_elements": ["伪造来源截图", "虚构权威背书"],
                "aspect_ratio": "3:4",
            })
        video = {
            "enabled": True,
            "hook": f"关于{title}，先记录这次我真正看见/理解/练习到的部分。",
            "timeline": ["0-5s 主题", "5-25s 核心记录", "25-45s Grounding/边界", "45-60s 下一步"],
            "narration": body,
            "shot_list": ["安静桌面/卡片开场", "关键概念或实践过程", "材料与限制", "收束页"],
            "visual_prompt": "editorial learning explainer, calm paced motion graphics, domain appropriate visuals",
            "transitions": "simple dissolve / card slide", "subtitle_keywords": [title, "学习", "实践", "修正"],
            "cover_prompt": image_prompts[0],
        }
    else:
        video = {"enabled": False, "reason": "media-prompt capability disabled", "outline": ["主题", "记录", "Grounding/边界", "下一步"]}

    combined = "\n".join([body, *[c["statement"] for c in claims]])
    issues = publish_guard(
        combined,
        has_verified_evidence=bool(claims) and all(c["ready_for_expression"] for c in claims),
        has_counter_evidence=any(c["contradicting_evidence"] for c in claims),
        claims=claims or None,
        evidence_required=evidence_required,
    )
    for g in groundings:
        if g["ref_type"] == "source" and not g["verified"]:
            issues.append({"severity": "medium", "code": "unverified_grounding_source", "message": f"Source「{g['title']}」尚未人工核验；不要把它写成已确认事实。"})
    ready = not any(x["severity"] == "high" for x in issues)
    if evidence_required:
        ready = ready and bool(claims) and all(c["ready_for_expression"] for c in claims)

    return {
        "area": {"id": context.area_id, "name": context.area_name, "domain_pack_id": context.domain_pack_id},
        "topic": {"id": topic_id, "title": title},
        "target_audience": audience.strip() or str(context.content.get("default_audience") or "对这个兴趣感兴趣的读者"),
        "platform": platform, "title_candidates": title_candidates, "body": body,
        "tag_suggestions": tags, "claims": claims, "grounding_refs": groundings,
        "card_outline": cards, "image_prompts": image_prompts, "video_pack": video,
        "risk_review": issues, "ready_for_publication": ready, "human_review_required": True,
        "approved": False, "media": {"enabled": include_media_prompts},
        "generation": {"provider": "deterministic-template", "enhanced": False},
    }


async def maybe_enhance_publish_pack(pack: dict) -> dict:
    settings = get_settings()
    provider = DeepSeekProvider(settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model, settings.deepseek_timeout_seconds)
    if not provider.configured:
        return pack
    context = get_domain_context()
    allowed_claims = [{"statement": c["statement"], "limitations": c["limitations"], "publishability": c["publishability"], "verification_state": c["verification_state"]} for c in pack["claims"]]
    allowed_grounding = [{"type": g["ref_type"], "title": g["title"], "summary": g["summary"], "status": g["grounding_status"]} for g in pack.get("grounding_refs", [])]
    prompt = (
        "请只基于下面提供的 Claim 与 Grounding 为学习/实践表达润色标题和正文。不得新增事实或虚构来源；"
        "个人笔记、练习和活动只能作为个人学习记录，不能自动推广成普遍结论。"
        f"\nDomain policy: {context.content.get('factual_claim_policy','')}"
        f"\nTopic: {pack['topic']['title']}\nAudience: {pack['target_audience']}"
        f"\nAllowed claims: {json.dumps(allowed_claims, ensure_ascii=False)}"
        f"\nAllowed grounding: {json.dumps(allowed_grounding, ensure_ascii=False)}"
        f"\nTemplate draft: {pack['body']}"
    )
    try:
        draft = await provider.structured(prompt, AIContentDraft, system="你是谨慎的学习内容编辑。只改善表达，不扩大 Grounding 支持的事实范围。")
    except Exception as exc:
        pack["generation"] = {"provider": "deterministic-template", "enhanced": False, "enhancement_attempted": True, "fallback_reason": type(exc).__name__}
        return pack
    pack["title_candidates"] = draft.title_candidates
    pack["body"] = draft.body
    pack["tag_suggestions"] = draft.tag_suggestions
    if pack["video_pack"].get("enabled"):
        pack["video_pack"]["narration"] = draft.body
    evidence_required = bool(context.content.get("evidence_required", False))
    pack["risk_review"] = publish_guard(
        "\n".join([draft.body, *[c["statement"] for c in pack["claims"]]]),
        has_verified_evidence=bool(pack["claims"]) and all(c["ready_for_expression"] for c in pack["claims"]),
        has_counter_evidence=any(c["contradicting_evidence"] for c in pack["claims"]),
        claims=pack["claims"] or None,
        evidence_required=evidence_required,
    )
    pack["ready_for_publication"] = not any(x["severity"] == "high" for x in pack["risk_review"])
    if evidence_required:
        pack["ready_for_publication"] = pack["ready_for_publication"] and bool(pack["claims"]) and all(c["ready_for_expression"] for c in pack["claims"])
    pack["generation"] = {"provider": "deepseek", "model": settings.deepseek_model, "enhanced": True, "fact_source": "selected-local-grounding-only"}
    return pack


def persist_publish_pack(pack: dict) -> tuple[str, str]:
    pack_id = str(uuid4())
    base = f"publish/{pack_id}"
    claims = list(pack.get("claims") or [])
    grounding = list(pack.get("grounding_refs") or [])
    files = {
        "01-title-candidates.md": "\n".join(f"- {x}" for x in pack["title_candidates"]),
        "02-post.md": pack["body"],
        "03-longform.md": pack["body"] + "\n\n## 当前边界\n" + ("\n".join(f"- {x['limitations']}" for x in claims if x["limitations"]) or "- 见 Grounding 与人工审核记录。"),
        "04-claims.md": "\n\n".join(f"### Claim\n{x['statement']}\n\n边界：{x['limitations'] or '待补充'}\n\nverification: {x['verification_state']} · publishability: {x['publishability']}" for x in claims) or "- 当前内容未使用 Claim。",
        "05-sources.md": "\n".join(f"- {e['source']} {e['url']}" for c in claims for e in c["supporting_evidence"] + c["contradicting_evidence"]) or "- 没有 Claim 来源导出；请查看 Grounding 记录。",
        "06-risk-review.md": "\n".join(f"- [{x['severity']}] {x['message']}" for x in pack["risk_review"]) or "- 未检测到规则级风险；仍需人工审核。",
        "07-card-plan.md": "\n".join(f"- {x['layout']}: {x['title']}" for x in pack["card_outline"]),
        "08-image-prompts.md": "\n\n".join(json.dumps(x, ensure_ascii=False, indent=2) for x in pack["image_prompts"]),
        "09-video-prompts.md": json.dumps(pack["video_pack"], ensure_ascii=False, indent=2),
        "10-grounding.md": "\n".join(f"- [{x['ref_type']}] {x['title']} · {x['grounding_status']}" for x in grounding) or "- 当前只使用 Claim/Evidence Grounding。",
        "publish.json": json.dumps(pack, ensure_ascii=False, indent=2),
    }
    for name, content in files.items():
        get_storage().put_text(f"{base}/{name}", content)
    return pack_id, base


def render_svg_card(title: str, points: list[str], footer: str, layout: str) -> str:
    def esc(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    y = 360
    nodes: list[str] = []
    for idx, point in enumerate(points[:6], 1):
        wrapped = shorten(point, width=34, placeholder="…")
        nodes.append(f'<text x="120" y="{y}" font-size="38" font-family="sans-serif">{idx}. {esc(wrapped)}</text>')
        y += 90
    domain_label = get_domain_context().area_name.upper()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">'
        '<rect width="1080" height="1440" rx="48" fill="#F7F3EA"/>'
        '<rect x="72" y="72" width="936" height="1296" rx="40" fill="#FFFDF8" stroke="#D7D0C4" stroke-width="2"/>'
        f'<text x="110" y="155" font-size="28" font-family="sans-serif" fill="#7A746A">{esc(domain_label)} · {esc(layout.upper())}</text>'
        f'<foreignObject x="110" y="205" width="860" height="180"><div xmlns="http://www.w3.org/1999/xhtml" style="font:700 58px sans-serif;line-height:1.25;color:#222;">{esc(title)}</div></foreignObject>'
        f'{"".join(nodes)}<line x1="110" y1="1260" x2="970" y2="1260" stroke="#D7D0C4"/>'
        f'<text x="110" y="1325" font-size="26" font-family="sans-serif" fill="#7A746A">{esc(footer)}</text></svg>'
    )

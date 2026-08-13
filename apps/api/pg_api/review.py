from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from .db import ClaimModel, ClaimVersionModel, EvidenceModel, SourceModel

_ABSOLUTE_PATTERNS = (
    (re.compile(r"\b(always|never|proves?|guarantees?|everyone|nobody)\b", re.I), "absolute_language"),
    (re.compile(r"(一定|必然|从不|永远|证明了|百分之百|所有人|任何人)"), "absolute_language"),
)
_DIAGNOSTIC_PATTERNS = (
    re.compile(r"\b(you|they|he|she)\s+(have|has|are)\s+(adhd|depression|anxiety|autism|ptsd)\b", re.I),
    re.compile(r"(你|他|她|这个人).{0,6}(就是|患有|得了).{0,10}(抑郁|焦虑|ADHD|自闭|创伤后应激)", re.I),
)
_CAUSAL_PATTERNS = (
    re.compile(r"\b(causes?|leads? to|results? in)\b", re.I),
    re.compile(r"(导致|造成|使得|必然引起)"),
)


def _issue(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def review_claim(db: Session, claim: ClaimModel, version: ClaimVersionModel) -> dict[str, Any]:
    """Run an auditable deterministic skeptic pass over the current Claim version.

    This is deliberately not an approval engine. It surfaces structural and
    evidence-boundary problems before the human verification step. It never
    mutates Claim.verification_state.
    """

    issues: list[dict[str, str]] = []
    support_ids = list(version.supporting_evidence or [])
    counter_ids = list(version.contradicting_evidence or [])

    if not support_ids:
        issues.append(_issue("high", "no_supporting_evidence", "Claim 还没有支持 Evidence，不能进入人工核验。"))

    support_rows = [db.get(EvidenceModel, evidence_id) for evidence_id in support_ids]
    missing_support = [evidence_id for evidence_id, row in zip(support_ids, support_rows, strict=False) if row is None]
    if missing_support:
        issues.append(_issue("high", "missing_supporting_evidence", "Claim 引用的部分支持 Evidence 已不存在。"))

    source_rows: list[SourceModel] = []
    for evidence in [row for row in support_rows if row is not None]:
        source = db.get(SourceModel, evidence.source_id)
        if source is not None:
            source_rows.append(source)
        if not evidence.verified or evidence.verification_state != "human_verified":
            issues.append(_issue("high", "support_not_human_verified", "至少一条支持 Evidence 尚未经过人工核验。"))
        if source is None or not source.verified:
            issues.append(_issue("high", "source_not_human_verified", "至少一条支持 Evidence 未指向已人工核验的 Source。"))
        elif source.ai_summary_only:
            issues.append(_issue("high", "ai_summary_only_source", "支持 Evidence 仍依赖 AI-only 摘要，不能作为已核验证据链。"))

    if not counter_ids:
        issues.append(_issue("medium", "no_counter_or_boundary_evidence", "尚未记录相反证据或边界证据；请确认是否存在条件、例外或争议。"))
    else:
        counter_rows = [db.get(EvidenceModel, evidence_id) for evidence_id in counter_ids]
        if any(row is None for row in counter_rows):
            issues.append(_issue("medium", "missing_counter_evidence", "部分相反/边界 Evidence 已不存在，需要重新核对。"))

    if not (version.limitations or "").strip():
        issues.append(_issue("medium", "missing_limitations", "Claim 没有写明限制或适用边界。"))

    distinct_sources = {row.id for row in source_rows}
    if claim.confidence > 0.85 and len(distinct_sources) < 2:
        issues.append(_issue("medium", "confidence_exceeds_evidence_base", "高置信度 Claim 只有不足两个独立已核验来源，请降低置信度或补充证据。"))

    statement = version.statement or ""
    for pattern, code in _ABSOLUTE_PATTERNS:
        if pattern.search(statement):
            issues.append(_issue("medium", code, "表述包含绝对化语言，请确认研究是否真的支持这种强度。"))
            break
    if any(pattern.search(statement) for pattern in _DIAGNOSTIC_PATTERNS):
        issues.append(_issue("high", "diagnostic_language", "Claim 含个体诊断式语言；本系统不把群体研究直接转为个体诊断。"))
    if any(pattern.search(statement) for pattern in _CAUSAL_PATTERNS):
        issues.append(_issue("medium", "causal_language", "Claim 使用因果语言；请确认研究设计足以支持因果推断。"))

    if claim.publishability in {"internal_only", "not_publishable"}:
        issues.append(_issue("medium", "learning_only_boundary", "当前 Claim 的公开边界是内部学习/不可公开；Skeptic Pass 不会改变这一边界。"))

    severities = {item["severity"] for item in issues}
    status = "block" if "high" in severities else "caution" if "medium" in severities else "pass"
    return {
        "claim_id": claim.id,
        "version_id": version.id,
        "version": version.version,
        "status": status,
        "issues": issues,
        "checked_at": datetime.now(UTC).isoformat(),
        "human_review_required": True,
        "verification_changed": False,
    }

def _topic(client):
    q = client.post("/api/questions", json={"question": "自主性支持为何影响内在动机？"}).json()
    return client.post(f"/api/questions/{q['id']}/promote").json()


def test_research_degrades_to_manual_workspace(client):
    topic = _topic(client)
    response = client.post(
        "/api/research/run",
        json={"topic_id": topic["id"], "question": topic["title"], "depth": "normal"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_status"]["degraded"] is True
    assert payload["result"]["provider"] == "manual-workspace"
    assert payload["run"]["status"] == "degraded"


def test_claim_verification_requires_verified_source_and_evidence(client):
    topic = _topic(client)
    source = client.post(
        "/api/sources",
        json={
            "topic_id": topic["id"],
            "title": "Self-Determination Theory source",
            "source_type": "paper",
            "verified": True,  # must not bypass the dedicated human verification action
        },
    ).json()
    assert source["verified"] is False
    assert source["verified_at"] is None

    blocked = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "Autonomy support is associated with more self-determined motivation.",
            "verification_state": "human_verified",
        },
    )
    assert blocked.status_code == 409

    assert client.post(f"/api/sources/{source['id']}/verify").status_code == 200
    evidence = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "Autonomy support is associated with more self-determined motivation.",
            "verification_state": "human_verified",
            "limitations": "Context and design matter.",
        },
    ).json()
    claim_payload = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "Autonomy-supportive contexts can support more self-determined motivation.",
            "supporting_evidence": [evidence["id"]],
            "limitations": "Do not infer a universal individual causal effect.",
            "publishability": "supported_with_caution",
        },
    ).json()
    claim_id = claim_payload["claim"]["id"]
    assert client.post(f"/api/claims/{claim_id}/verify").status_code == 200

    revised = client.post(
        f"/api/claims/{claim_id}/revisions",
        json={
            "statement": "Autonomy-supportive contexts are often linked to more self-determined motivation, with effects depending on context and study design.",
            "supporting_evidence": [evidence["id"]],
            "limitations": "Evidence should be interpreted by population, context, and design.",
            "reason_for_revision": "Reduced causal overstatement",
            "publishability": "supported_with_caution",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["claim"]["verification_state"] == "unverified"
    assert revised.json()["claim"]["last_verified_at"] is None
    # A revised version needs a new human verification even if v1 was verified.
    assert client.post(f"/api/claims/{claim_id}/verify").status_code == 200
    versions = client.get(f"/api/claims/{claim_id}/versions").json()["versions"]
    assert [v["version"] for v in versions] == [1, 2]


def test_publish_pack_blocks_mixed_unverified_claims(client):
    topic = _topic(client)
    source = client.post(
        "/api/sources",
        json={"topic_id": topic["id"], "title": "Reviewed source", "source_type": "paper"},
    ).json()
    client.post(f"/api/sources/{source['id']}/verify")
    evidence = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "A bounded piece of evidence.",
            "verification_state": "human_verified",
            "limitations": "Limited fixture evidence.",
        },
    ).json()
    counter = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "A counter/boundary observation.",
            "supports_claim": False,
            "verification_state": "human_verified",
            "limitations": "Boundary fixture.",
        },
    ).json()
    verified = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "A cautious verified statement.",
            "supporting_evidence": [evidence["id"]],
            "contradicting_evidence": [counter["id"]],
            "limitations": "Stay within this fixture.",
            "publishability": "supported_with_caution",
        },
    ).json()["claim"]
    assert client.post(f"/api/claims/{verified['id']}/verify").status_code == 200

    internal = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "An internal-only unverified statement.",
            "supporting_evidence": [],
            "limitations": "Insufficient evidence.",
            "publishability": "internal_only",
        },
    ).json()["claim"]

    pack = client.post(
        "/api/content/packs",
        json={
            "topic_id": topic["id"],
            "claim_ids": [verified["id"], internal["id"]],
            "target_audience": "ordinary readers",
            "platform": "xhs",
        },
    )
    assert pack.status_code == 200
    data = pack.json()["pack"]
    assert data["ready_for_publication"] is False
    codes = {issue["code"] for issue in data["risk_review"] if issue["severity"] == "high"}
    assert "claim_not_human_verified" in codes
    assert "support_not_fully_verified" in codes
    assert "claim_not_publishable" in codes

    standalone = client.post(
        "/api/content/guard",
        json={"text": "internal draft", "claim_ids": [verified["id"], internal["id"]]},
    )
    assert standalone.status_code == 200
    standalone_codes = {x["code"] for x in standalone.json()["issues"] if x["severity"] == "high"}
    assert "claim_not_publishable" in standalone_codes
    # A blocked pack cannot be human-approved merely by clicking the approval route.
    artifact_id = pack.json()["artifact"]["id"]
    assert client.post(f"/api/artifacts/{artifact_id}/approve").status_code == 409


def test_skeptic_pass_blocks_structurally_unsupported_claim_without_verifying_it(client):
    topic = _topic(client)
    claim = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "心理学证明了所有奖励一定会导致内在动机下降。",
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "limitations": "",
            "confidence": 0.95,
            "publishability": "internal_only",
        },
    ).json()["claim"]

    review = client.post(f"/api/claims/{claim['id']}/skeptic-pass")
    assert review.status_code == 200
    payload = review.json()
    assert payload["review"]["status"] == "block"
    assert payload["review"]["verification_changed"] is False
    codes = {issue["code"] for issue in payload["review"]["issues"]}
    assert "no_supporting_evidence" in codes
    assert "no_counter_or_boundary_evidence" in codes
    assert "missing_limitations" in codes
    assert "absolute_language" in codes
    assert "causal_language" in codes
    assert payload["run"]["capability"] == "skeptic-review"
    assert payload["run"]["engine"] == "local-rules"

    current = client.get(f"/api/claims?topic_id={topic['id']}").json()["claims"][0]["claim"]
    assert current["verification_state"] == "unverified"


def test_persist_sources_keeps_verified_false(client):
    """Research citations are candidate grounding, never automatically verified Evidence."""
    topic = _topic(client)
    response = client.post(
        "/api/research/run",
        json={"topic_id": topic["id"], "question": topic["title"], "depth": "normal", "persist_sources": True},
    )
    assert response.status_code == 200
    source_ids = response.json()["result"]["source_ids"]
    if not source_ids:
        return
    sources = client.get(f"/api/sources?topic_id={topic['id']}").json()
    by_id = {s["id"]: s for s in sources["sources"]}
    for sid in source_ids:
        assert by_id[sid]["verified"] is False
        assert by_id[sid]["verified_at"] is None


def test_provider_failure_uses_the_approved_plan_snapshot(client, monkeypatch):
    """A provider outage may degrade execution, but may not replace Plan A."""
    from interest_growth_native.errors import ProviderUnavailable
    from pg_api.routes import research as research_routes

    captured = {}

    class FailingResearch:
        def run_confirmed(self, _context, *, question, subtopics, **kwargs):
            captured["question"] = question
            captured["subquestions"] = [item.title for item in subtopics]
            captured["outline_status"] = kwargs["outline_status"]
            raise ProviderUnavailable("fixture provider unavailable")

    class FailingBundle:
        research = FailingResearch()

    monkeypatch.setattr(research_routes, "get_native_bundle", lambda: FailingBundle())
    topic = _topic(client)
    approved = {
        "question": "Plan A 的研究问题",
        "brief": "用户确认的研究范围",
        "subquestions": ["先看定义", "再看反例"],
        "desired_sources": ["原始资料", "反方资料"],
        "depth": "normal",
        "approved": True,
    }
    response = client.post("/api/research/run", json={
        "topic_id": topic["id"],
        "question": "不要执行的原始问题",
        "depth": "normal",
        "approved_plan": approved,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["status"] == "degraded"
    assert captured == {
        "question": "Plan A 的研究问题",
        "subquestions": ["先看定义", "再看反例"],
        "outline_status": "approved_by_user",
    }
    assert body["result"]["plan"]["question"] == approved["question"]
    assert body["result"]["plan"]["subquestions"] == approved["subquestions"]

def test_personal_alpha_core_journey(client):
    # P1: capture -> pause -> return -> topic
    q = client.post(
        "/api/questions",
        json={
            "question": "外部奖励什么时候会削弱内在动机？",
            "interest_level": 5,
            "energy_mode": "normal",
            "source_context": "真实工作与学习兴趣",
        },
    ).json()
    quick = client.post(f"/api/questions/{q['id']}/quick-explore", json={}).json()
    assert quick["state"] == "exploring"
    assert quick["exploration"]["evidence_status"] == "not_evidence"
    assert quick["exploration"]["provider"] == "manual-quick"
    assert client.post(f"/api/questions/{q['id']}/pause").json()["state"] == "paused"
    returned = client.post(f"/api/questions/{q['id']}/return").json()
    assert returned["returned_count"] == 1
    topic = client.post(f"/api/questions/{q['id']}/promote").json()

    # P2: research remains usable in degraded mode.
    research = client.post(
        "/api/research/run",
        json={"topic_id": topic["id"], "question": q["question"], "depth": "normal"},
    )
    assert research.status_code == 200

    # Human creates and verifies a source/evidence before verifying the Claim.
    source = client.post(
        "/api/sources",
        json={
            "topic_id": topic["id"],
            "source_type": "paper",
            "title": "Human-reviewed motivation paper",
            "canonical_url": "https://example.org/paper",
        },
    ).json()
    client.post(f"/api/sources/{source['id']}/verify")
    evidence = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "The effect of rewards depends on reward type, contingency, and context.",
            "strength": "moderate",
            "limitations": "This test fixture is a human-reviewed placeholder, not a real citation.",
            "verification_state": "human_verified",
        },
    ).json()
    counter = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "Some reward conditions do not show the same undermining pattern.",
            "supports_claim": False,
            "strength": "moderate",
            "limitations": "Conditions vary.",
            "verification_state": "human_verified",
        },
    ).json()
    claim_payload = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "Rewards do not have one uniform effect on intrinsic motivation; context matters.",
            "supporting_evidence": [evidence["id"]],
            "contradicting_evidence": [counter["id"]],
            "limitations": "Avoid universal claims about all rewards or people.",
            "confidence": 0.7,
            "publishability": "supported_with_caution",
        },
    ).json()
    claim_id = claim_payload["claim"]["id"]
    client.post(
        f"/api/claims/{claim_id}/revisions",
        json={
            "statement": "The relationship between rewards and intrinsic motivation varies by reward type, contingency, meaning, and context.",
            "supporting_evidence": [evidence["id"]],
            "contradicting_evidence": [counter["id"]],
            "limitations": "Population and study design still constrain generalization.",
            "reason_for_revision": "Added conditions and reduced absoluteness",
            "confidence": 0.72,
            "publishability": "supported_with_caution",
        },
    )
    skeptic = client.post(f"/api/claims/{claim_id}/skeptic-pass")
    assert skeptic.status_code == 200
    assert skeptic.json()["review"]["status"] == "pass"
    assert skeptic.json()["review"]["verification_changed"] is False
    assert skeptic.json()["run"]["capability"] == "skeptic-review"
    assert client.post(f"/api/claims/{claim_id}/verify").status_code == 200

    # P3: concept -> mastery evidence -> reflection/growth narrative.
    concept_payload = client.post(
        "/api/concepts",
        json={
            "topic_id": topic["id"],
            "name": "内在动机与奖励效应",
            "definition": "奖励效应需要按类型、情境和心理意义区分。",
            "related_claims": [claim_id],
            "related_sources": [source["id"]],
        },
    ).json()
    concept_id = concept_payload["concept"]["id"]
    mastery = client.put(
        f"/api/concepts/{concept_id}/mastery",
        json={"state": "evidence_boundary", "evidence_note": "能说明为什么不能把奖励效应写成单一因果结论。"},
    )
    assert mastery.status_code == 200
    client.post(
        "/api/reflections",
        json={
            "attracted_question": q["question"],
            "interest_drain": "一次看太多文献会消耗兴趣",
            "understanding_change": "从‘奖励有害’改成按条件判断",
            "continue_topic": topic["title"],
            "next_energy_mode": "light",
        },
    )
    narrative = client.get("/api/growth/narrative").json()
    assert narrative["signals"]["returns"] >= 1
    assert narrative["signals"]["claim_revisions"] >= 1
    memory = client.get("/api/growth/memory").json()["memory"]
    assert {m["layer"] for m in memory} == {"g1_raw", "g2_structured", "g3_long_term"}
    mastery_memories = [m for m in memory if m["memory_type"] == "concept_mastery"]
    assert any(m["value_json"]["state"] == "evidence_boundary" for m in mastery_memories)

    # P4: content pack -> guard -> local card -> human approval; no publishing.
    pack = client.post(
        "/api/content/packs",
        json={
            "topic_id": topic["id"],
            "claim_ids": [claim_id],
            "target_audience": "对心理学感兴趣的普通读者",
            "platform": "xhs",
        },
    )
    assert pack.status_code == 200
    assert pack.json()["pack"]["human_review_required"] is True
    assert pack.json()["pack"]["ready_for_publication"] is True
    assert pack.json()["pack"]["generation"]["provider"] == "deterministic-template"
    artifact_id = pack.json()["artifact"]["id"]
    approved = client.post(f"/api/artifacts/{artifact_id}/approve").json()
    assert approved["external_publish_performed"] is False
    exported = client.get(f"/api/artifacts/{artifact_id}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"

    card = client.post(
        "/api/content/cards/render",
        json={
            "topic_id": topic["id"],
            "layout": "evidence",
            "title": "奖励效应不能脱离情境",
            "points": ["先区分奖励类型", "再看控制感/信息意义", "最后说明研究边界"],
        },
    )
    assert card.status_code == 200
    assert card.json()["artifact"]["human_review_required"] is True

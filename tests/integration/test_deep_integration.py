from __future__ import annotations

import io
import zipfile


def _topic(client, question="如何理解自主性支持？"):
    q = client.post("/api/questions", json={"question": question}).json()
    return client.post(f"/api/questions/{q['id']}/promote").json()


def test_invalid_knowledge_reference_never_leaves_running_research_row(client):
    topic = _topic(client, "无效知识库引用应该怎样失败？")
    response = client.post(
        "/api/research/run",
        json={
            "topic_id": topic["id"],
            "question": topic["title"],
            "knowledge_base_ids": ["does-not-exist"],
        },
    )
    assert response.status_code == 400
    runs = client.get(f"/api/research/runs?topic_id={topic['id']}").json()["runs"]
    assert runs == []

def test_career_experiments_use_observed_change_not_imagined_fit(client):
    created = client.post(
        "/api/career/experiments",
        json={
            "direction": "心理科普",
            "hypothesis": "证据型写作可能比纯阅读更能维持兴趣",
            "experiment": "完成一篇带 Claim/Evidence 的短文并记录体验",
            "interest_before": 3,
            "competence_boundary": "cautious_expression",
        },
    )
    assert created.status_code == 200
    row = created.json()
    completed = client.put(
        f"/api/career/experiments/{row['id']}",
        json={
            "evidence": "完成后主动延伸出两个新问题",
            "interest_after": 4,
            "status": "completed",
            "reflection": "表达能反向暴露证据边界。",
        },
    )
    assert completed.status_code == 200
    summary = client.get("/api/career/summary").json()
    assert summary["completed_experiments"] == 1
    assert summary["directions"]["心理科普"]["interest_change"] == 1


def _verified_publishable_claim(client):
    topic = _topic(client, "奖励效应为什么不能一概而论？")
    source = client.post(
        "/api/sources", json={"topic_id": topic["id"], "title": "reviewed source", "source_type": "paper"}
    ).json()
    client.post(f"/api/sources/{source['id']}/verify")
    support = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "Reward effects vary by contingency and context.",
            "verification_state": "human_verified",
            "limitations": "Fixture evidence only.",
        },
    ).json()
    counter = client.post(
        "/api/evidence",
        json={
            "source_id": source["id"],
            "excerpt_or_summary": "Some reward conditions do not show undermining.",
            "supports_claim": False,
            "verification_state": "human_verified",
            "limitations": "Boundary fixture.",
        },
    ).json()
    claim = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "奖励对内在动机的关系取决于奖励类型、意义与情境。",
            "supporting_evidence": [support["id"]],
            "contradicting_evidence": [counter["id"]],
            "limitations": "不能推广为所有人、所有奖励的单一因果规则。",
            "publishability": "supported_with_caution",
        },
    ).json()["claim"]
    assert client.post(f"/api/claims/{claim['id']}/verify").status_code == 200
    return topic, claim


def test_human_review_then_export_is_a_real_product_path(client):
    topic, claim = _verified_publishable_claim(client)
    pack = client.post(
        "/api/content/packs",
        json={"topic_id": topic["id"], "claim_ids": [claim["id"]], "platform": "xhs"},
    )
    assert pack.status_code == 200
    artifact = pack.json()["artifact"]
    before = client.get(f"/api/artifacts/{artifact['id']}/export")
    assert before.status_code == 409

    approved = client.post(f"/api/artifacts/{artifact['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["external_publish_performed"] is False
    exported = client.get(f"/api/artifacts/{artifact['id']}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(exported.content)) as zf:
        names = set(zf.namelist())
    assert {"publish.json", "01-title-candidates.md", "02-post.md", "04-claims.md", "05-sources.md", "06-risk-review.md"} <= names


def test_claim_revision_invalidates_previously_approved_content(client):
    topic, claim = _verified_publishable_claim(client)
    pack = client.post(
        "/api/content/packs",
        json={"topic_id": topic["id"], "claim_ids": [claim["id"]], "platform": "xhs"},
    ).json()
    artifact_id = pack["artifact"]["id"]
    assert client.post(f"/api/artifacts/{artifact_id}/approve").status_code == 200
    assert client.get(f"/api/artifacts/{artifact_id}/export").status_code == 200

    current = client.get(f"/api/claims?topic_id={topic['id']}").json()["claims"][0]
    revised = client.post(
        f"/api/claims/{claim['id']}/revisions",
        json={
            "statement": current["current_version"]["statement"] + " 新版本。",
            "supporting_evidence": current["current_version"]["supporting_evidence"],
            "contradicting_evidence": current["current_version"]["contradicting_evidence"],
            "limitations": current["current_version"]["limitations"],
            "reason_for_revision": "new evidence wording",
            "publishability": "supported_with_caution",
        },
    )
    assert revised.status_code == 200
    artifacts = client.get(f"/api/artifacts?topic_id={topic['id']}").json()["artifacts"]
    stale = next(x for x in artifacts if x["id"] == artifact_id)
    assert stale["metadata_json"]["review_needed"] is True
    assert stale["approved_at"] is None
    assert client.post(f"/api/artifacts/{artifact_id}/approve").status_code == 409
    assert client.get(f"/api/artifacts/{artifact_id}/export").status_code == 409


def test_source_invalidation_revokes_evidence_claim_and_content_approval(client):
    topic, claim = _verified_publishable_claim(client)
    claim_bundle = client.get(f"/api/claims?topic_id={topic['id']}").json()["claims"][0]
    support_id = claim_bundle["current_version"]["supporting_evidence"][0]
    evidence = client.get("/api/evidence").json()["evidence"]
    source_id = next(row["source_id"] for row in evidence if row["id"] == support_id)

    pack = client.post(
        "/api/content/packs",
        json={"topic_id": topic["id"], "claim_ids": [claim["id"]], "platform": "xhs"},
    ).json()
    artifact_id = pack["artifact"]["id"]
    assert client.post(f"/api/artifacts/{artifact_id}/approve").status_code == 200

    revoked = client.post(
        f"/api/sources/{source_id}/invalidate",
        json={"reason": "source was superseded and requires renewed original-text review"},
    )
    assert revoked.status_code == 200
    assert claim["id"] in revoked.json()["affected_claim_ids"]

    claims = client.get(f"/api/claims?topic_id={topic['id']}").json()["claims"]
    current = next(x for x in claims if x["claim"]["id"] == claim["id"])
    assert current["claim"]["verification_state"] == "unverified"
    queue = client.get("/api/claims/reverification?stale_days=180")
    assert queue.status_code == 200
    queued = next(x for x in queue.json()["claims"] if x["claim"]["id"] == claim["id"])
    assert "source_verification_missing_or_revoked" in queued["reasons"]

    artifacts = client.get(f"/api/artifacts?topic_id={topic['id']}").json()["artifacts"]
    stale = next(x for x in artifacts if x["id"] == artifact_id)
    assert stale["metadata_json"]["review_reason"] == "linked_claim_reverification_required"
    assert stale["approved_at"] is None
    assert client.get(f"/api/artifacts/{artifact_id}/export").status_code == 409


def test_tutor_session_is_local_durable_context(client):
    topic = client.post('/api/topics', json={'title': 'Motivation', 'description': ''}).json()
    concept = client.post('/api/concepts', json={
        'topic_id': topic['id'], 'name': 'Intrinsic motivation', 'definition': 'Doing an activity for its inherent satisfaction',
        'examples': [], 'counterexamples': [], 'confused_with': [], 'related_claims': [], 'related_sources': []
    }).json()['concept']
    created = client.post('/api/tutor/sessions', json={
        'title': 'Motivation tutor', 'topic_id': topic['id'], 'concept_id': concept['id'],
        'knowledge_base_ids': [], 'skill_names': ['psychology-evidence-review'], 'persona_name': 'psychology-peer'
    })
    assert created.status_code == 200
    body = created.json()
    assert body['upstream_session_id'] == ''
    assert body['concept_id'] == concept['id']
    detail = client.get(f"/api/tutor/sessions/{body['id']}").json()
    assert detail['session']['skill_names'] == ['psychology-evidence-review']
    assert detail['turns'] == []


def test_same_named_sources_keep_distinct_upstream_identities(client):
    topic = _topic(client, "同名论文文件如何保持来源身份？")
    kb = client.post(
        "/api/knowledge/bases",
        json={"name": "same-name-fixture", "rag_provider": "native-lexical"},
    ).json()
    source_a = client.post(
        "/api/knowledge/sources/upload",
        data={"topic_id": topic["id"], "title": "paper A", "source_type": "paper"},
        files={"file": ("paper.pdf", b"%PDF-1.4 A", "application/pdf")},
    ).json()
    source_b = client.post(
        "/api/knowledge/sources/upload",
        data={"topic_id": topic["id"], "title": "paper B", "source_type": "paper"},
        files={"file": ("paper.pdf", b"%PDF-1.4 B", "application/pdf")},
    ).json()
    client.post(f"/api/knowledge/bases/{kb['id']}/sources/{source_a['id']}/link")
    client.post(f"/api/knowledge/bases/{kb['id']}/sources/{source_b['id']}/link")

    rows = client.get(f"/api/knowledge/bases/{kb['id']}/indexes").json()["indexes"]
    by_source = {row["source"]["id"]: row["index"]["upstream_file_name"] for row in rows}
    assert by_source[source_a["id"]] != by_source[source_b["id"]]
    assert by_source[source_a["id"]].startswith(f"pg_{source_a['id'][:8]}__")
    assert by_source[source_b["id"]].startswith(f"pg_{source_b['id'][:8]}__")
    assert by_source[source_a["id"]].endswith("paper.pdf")
    assert by_source[source_b["id"]].endswith("paper.pdf")

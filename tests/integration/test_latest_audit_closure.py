from __future__ import annotations

from pg_api.db import EntityAreaBindingModel, TutorPersonaModel, TutorSessionModel, TutorTurnModel, get_session_factory
from pg_api.domains import resolve_area


def _topic(client):
    return client.post("/api/topics", json={"title": "审计收口主题", "description": "可修订主题"}).json()


def test_source_delete_propagates_through_claim_artifact_and_living_book(client):
    topic = _topic(client)
    uploaded = client.post(
        "/api/knowledge/sources/upload",
        data={"topic_id": topic["id"], "title": "本地来源", "source_type": "paper"},
        files={"file": ("source.txt", b"source material for propagation")},
    )
    assert uploaded.status_code == 200, uploaded.text
    source = uploaded.json()
    assert client.post(f"/api/sources/{source['id']}/verify").status_code == 200
    evidence = client.post("/api/evidence", json={
        "source_id": source["id"], "excerpt_or_summary": "Human verified excerpt",
        "verification_state": "human_verified",
    }).json()
    claim = client.post("/api/claims", json={
        "topic_id": topic["id"], "statement": "A cautious claim.",
        "supporting_evidence": [evidence["id"]], "publishability": "supported_with_caution",
    }).json()["claim"]
    assert client.post(f"/api/claims/{claim['id']}/verify").status_code == 200
    book = client.post("/api/living-books", json={"topic_id": topic["id"], "title": "审计书"}).json()
    compiled = client.post(f"/api/living-books/{book['id']}/compile")
    assert compiled.status_code == 200
    artifact = client.post("/api/content/packs", json={
        "topic_id": topic["id"], "claim_ids": [claim["id"]], "platform": "xhs",
    })
    assert artifact.status_code == 200, artifact.text
    artifact_id = artifact.json()["artifact"]["id"]
    assert client.post(f"/api/artifacts/{artifact_id}/approve").status_code == 200
    assert client.get(f"/api/artifacts/{artifact_id}/export").status_code == 200

    deleted = client.delete(f"/api/sources/{source['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["file_removed"] is True
    assert source["id"] not in {row["id"] for row in client.get("/api/sources").json()["sources"]}
    assert client.get(f"/api/evidence?source_id={source['id']}").json()["evidence"] == []
    claim_after = client.get(f"/api/claims?topic_id={topic['id']}").json()["claims"][0]["claim"]
    assert claim_after["verification_state"] == "unverified"
    assert claim_after["last_verified_at"] is None
    artifact_after = client.get(f"/api/artifacts/{artifact_id}").json()["artifact"]
    assert artifact_after["metadata_json"]["review_needed"] is True
    assert artifact_after["approved_at"] is None
    assert client.get(f"/api/artifacts/{artifact_id}/export").status_code == 409
    chapter = client.get(f"/api/living-books/{book['id']}").json()["chapters"][0]
    assert chapter["status"] == "stale"
    assert client.get("/api/knowledge/retrieval-candidates").status_code in {200, 404}


def test_topic_archive_restore_and_area_archive_restore(client):
    topic = _topic(client)
    assert client.patch(f"/api/topics/{topic['id']}", json={"title": "已编辑主题"}).status_code == 200
    assert client.post(f"/api/topics/{topic['id']}/archive").status_code == 200
    assert topic["id"] not in {row["id"] for row in client.get("/api/topics").json()["topics"]}
    assert topic["id"] in {row["id"] for row in client.get("/api/topics?include_archived=true").json()["topics"]}
    assert client.post(f"/api/topics/{topic['id']}/restore").status_code == 200

    area = client.post("/api/areas", json={"name": "可恢复领域", "slug": "restorable-area"}).json()
    assert client.patch(f"/api/areas/{area['id']}", json={"archived": True}).status_code == 200
    assert area["id"] not in {row["id"] for row in client.get("/api/areas").json()["areas"]}
    assert area["id"] in {row["id"] for row in client.get("/api/areas?include_archived=true").json()["areas"]}
    assert client.post(f"/api/areas/{area['id']}/restore").status_code == 200


def test_growth_memory_reset_preserves_canonical_question(client):
    question = client.post("/api/questions", json={"question": "保留这条原始问题"}).json()
    assert client.post("/api/growth/memory/refresh").status_code == 200
    reset = client.post("/api/growth/memory/reset")
    assert reset.status_code == 200
    assert reset.json()["canonical_data_preserved"] is True
    assert client.get(f"/api/questions/{question['id']}").status_code == 200
    assert client.post("/api/growth/memory/rebuild").status_code == 200


def test_knowledge_base_names_are_area_scoped(client):
    first = client.post("/api/areas", json={"name": "资料领域一", "slug": "knowledge-area-one"}).json()
    second = client.post("/api/areas", json={"name": "资料领域二", "slug": "knowledge-area-two"}).json()
    first_kb = client.post("/api/knowledge/bases", headers={"X-PG-Interest-Area": first["id"]}, json={"name": "我的资料库"})
    second_kb = client.post("/api/knowledge/bases", headers={"X-PG-Interest-Area": second["id"]}, json={"name": "我的资料库"})
    assert first_kb.status_code == 200, first_kb.text
    assert second_kb.status_code == 200, second_kb.text
    assert first_kb.json()["id"] != second_kb.json()["id"]


def test_tutor_delete_blocks_active_native_turn(client):
    session = client.post("/api/tutor/sessions", json={"title": "活动回合"}).json()
    with get_session_factory()() as db:
        turn = TutorTurnModel(
            tutor_session_id=session["id"], upstream_turn_id="native-run-active",
            status="awaiting_input", input_json={"content": "等待输入"},
        )
        db.add(turn)
        db.commit()
        turn_id = turn.id
    blocked = client.delete(f"/api/tutor/sessions/{session['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "active_turn_exists"
    with get_session_factory()() as db:
        db.get(TutorTurnModel, turn_id).status = "cancelled"
        db.commit()
    assert client.delete(f"/api/tutor/sessions/{session['id']}").status_code == 200

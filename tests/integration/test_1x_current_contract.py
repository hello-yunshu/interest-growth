from __future__ import annotations


def test_current_area_exposes_domain_owned_mastery_profile(client):
    psychology = client.get("/api/areas/current").json()
    profile = psychology["mastery_profile"]
    assert profile["id"] == "psychology:conceptual-evidence"
    assert [item["id"] for item in profile["states"]][-2:] == ["evidence_boundary", "stable_expression"]

    area = client.post("/api/areas", json={"name": "摄影", "slug": "photography-1x"}).json()
    general = client.get("/api/areas/current", headers={"X-PG-Interest-Area": area["id"]}).json()
    states = [item["id"] for item in general["mastery_profile"]["states"]]
    assert general["mastery_profile"]["id"] == "general:adaptive"
    assert states[-2:] == ["transfer", "self_directed"]
    assert "evidence_boundary" not in states


def test_learning_gate_fails_closed_before_provider_degradation(client):
    topic = client.post("/api/topics", json={"title": "学习边界"}).json()
    concept = client.post("/api/concepts", json={"topic_id": topic["id"], "name": "边界"}).json()["concept"]
    assert client.put("/api/features/FEATURE_FLEXIBLE_MASTERY", json={"enabled": False}).status_code == 200
    response = client.post(f"/api/concepts/{concept['id']}/guided-path", json={})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "feature_disabled"
    assert client.put("/api/features/FEATURE_FLEXIBLE_MASTERY", json={"enabled": True}).status_code == 200


def test_concept_card_update_validates_scoped_relations(client):
    topic = client.post("/api/topics", json={"title": "完整概念卡"}).json()
    source = client.post("/api/sources", json={"topic_id": topic["id"], "title": "可核对来源"}).json()
    concept = client.post("/api/concepts", json={"topic_id": topic["id"], "name": "原始名称"}).json()["concept"]
    response = client.put(f"/api/concepts/{concept['id']}", json={
        "name": "更新后的名称",
        "examples": ["例子"],
        "counterexamples": ["边界"],
        "related_sources": [source["id"]],
    })
    assert response.status_code == 200
    assert response.json()["related_sources"] == [source["id"]]
    bad = client.put(f"/api/concepts/{concept['id']}", json={"related_sources": ["not-in-area"]})
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "area_scope_mismatch"


def test_career_summary_returns_cautious_signal_contract(client):
    row = client.post("/api/career/experiments", json={"direction": "教学", "experiment": "做一次小分享"}).json()
    client.put(f"/api/career/experiments/{row['id']}", json={"status": "completed", "evidence": "完成分享", "interest_after": 4})
    summary = client.get("/api/career/summary").json()
    assert summary["most_promising_direction"] == "教学"
    assert summary["signal"]["direction"] == "教学"
    assert summary["signal"]["confidence"] == "low"
    assert summary["signal"]["sample_size"] == 1

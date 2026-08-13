def test_core_independent_without_external_engines(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    integrations = client.get("/api/system/integrations")
    assert integrations.status_code == 200
    data = integrations.json()
    assert set(data) == {"native_execution", "deepseek"}

    created = client.post(
        "/api/questions",
        json={"question": "为什么奖励有时会削弱兴趣？", "energy_mode": "light"},
    )
    assert created.status_code == 200
    assert created.json()["state"] == "captured"


def test_plugin_disable_enable_preserves_data(client):
    reflection = client.post(
        "/api/reflections",
        json={
            "attracted_question": "奖励与内在动机",
            "understanding_change": "开始区分奖励类型",
            "next_energy_mode": "normal",
        },
    )
    assert reflection.status_code == 200
    reflection_id = reflection.json()["id"]

    disabled = client.post("/api/plugins/capability.reflection/disable")
    assert disabled.status_code == 200
    assert disabled.json()["data_preserved"] is True
    assert client.get("/api/reflections").status_code == 503

    enabled = client.post("/api/plugins/capability.reflection/enable")
    assert enabled.status_code == 200
    rows = client.get("/api/reflections").json()["reflections"]
    assert any(row["id"] == reflection_id for row in rows)


def test_question_can_quick_explore_and_close_without_research(client):
    q = client.post("/api/questions", json={"question": "旁观者效应是什么？"}).json()
    quick = client.post(f"/api/questions/{q['id']}/quick-explore", json={})
    assert quick.status_code == 200
    assert quick.json()["exploration"]["evidence_status"] == "not_evidence"
    assert quick.json()["exploration"]["provider"] == "manual-quick"
    closed = client.post(f"/api/questions/{q['id']}/close")
    assert closed.status_code == 200
    assert closed.json()["state"] == "closed"
    assert closed.json()["active"] is False


def test_media_plugin_disable_degrades_content_to_text_pack(client):
    q = client.post("/api/questions", json={"question": "认知失调如何理解？"}).json()
    topic = client.post(f"/api/questions/{q['id']}/promote").json()
    claim = client.post(
        "/api/claims",
        json={
            "topic_id": topic["id"],
            "statement": "这是一个仍待核验的内部学习 Claim。",
            "publishability": "internal_only",
        },
    ).json()["claim"]

    disabled = client.post("/api/plugins/capability.media-prompt/disable")
    assert disabled.status_code == 200
    pack = client.post(
        "/api/content/packs",
        json={
            "topic_id": topic["id"],
            "claim_ids": [claim["id"]],
            "target_audience": "self",
            "platform": "xhs",
        },
    )
    assert pack.status_code == 200
    data = pack.json()["pack"]
    assert data["media"]["enabled"] is False
    assert data["image_prompts"] == []
    assert data["video_pack"]["enabled"] is False
    assert data["body"]
    assert client.post("/api/content/cards/render", json={"title": "x", "points": []}).status_code == 503


def test_feature_flags_isolate_deep_research_and_growth_feedback(client):
    assert client.put("/api/features/FEATURE_DEEP_RESEARCH", json={"enabled": False}).status_code == 200
    q = client.post("/api/questions", json={"question": "为什么人会有确认偏误？"}).json()
    topic = client.post(f"/api/questions/{q['id']}/promote").json()
    run = client.post(
        "/api/research/run",
        json={"topic_id": topic["id"], "question": q["question"], "depth": "deep"},
    ).json()
    assert run["engine_status"]["degraded"] is True
    assert "FEATURE_DEEP_RESEARCH disabled" in run["engine_status"]["reason"]

    assert client.put("/api/features/FEATURE_GROWTH_FEEDBACK", json={"enabled": False}).status_code == 200
    paused = client.post(f"/api/questions/{q['id']}/pause")
    assert paused.status_code == 200
    returned = client.post(f"/api/questions/{q['id']}/return")
    assert returned.status_code == 200
    assert client.get("/api/growth/events").status_code == 503

    # Re-enable and inspect: the return performed while feedback was disabled was not
    # secretly processed by the disabled plugin.
    assert client.put("/api/features/FEATURE_GROWTH_FEEDBACK", json={"enabled": True}).status_code == 200
    events = client.get("/api/growth/events").json()["events"]
    assert not any(e["event_type"] == "question.returned" for e in events)

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, select


def test_native_migration_health_and_provider_catalog(client):
    from pg_api.db import SchemaMigration, get_engine, get_session_factory

    tables = set(inspect(get_engine()).get_table_names())
    assert {
        "native_tutor_checkpoint", "native_run_event", "native_aux_memory",
    } <= tables
    with get_session_factory()() as db:
        assert set(db.scalars(select(SchemaMigration.version)).all()) == set(range(1, 14))

    health = client.get("/api/native-execution/health")
    assert health.status_code == 200, health.text
    assert health.json()["provider"] == "native.interest-growth"
    assert health.json()["provider"] == "native.interest-growth"
    assert "runtime_required" not in " ".join(health.json())

    providers = client.get("/api/knowledge/providers").json()
    assert providers["native_default"] == "native-lexical"
    native = {x["id"] for x in providers["providers"] if x.get("native")}
    assert native == {
        "native-lexical", "native-lightgraph", "native-concept-graph", "native-heading",
    }


def test_native_owned_source_sync_retrieve_and_area_isolation(client):
    kb = client.post("/api/knowledge/bases", json={
        "name": "Native product KB",
        "description": "Host-owned retrieval fixture",
    })
    assert kb.status_code == 200, kb.text
    assert kb.json()["rag_provider"] == "native-lexical"
    kb_id = kb.json()["id"]

    uploaded = client.post(
        "/api/knowledge/sources/upload",
        files={"file": ("learning.md", "# Spaced learning\nRetrieval practice improves durable recall.", "text/markdown")},
        data={"title": "Learning notes", "source_type": "document"},
    )
    assert uploaded.status_code == 200, uploaded.text
    source_id = uploaded.json()["id"]

    synced = client.post(f"/api/knowledge/bases/{kb_id}/sources/{source_id}/sync")
    assert synced.status_code == 200, synced.text
    assert synced.json()["mode"] == "native"
    assert synced.json()["status"] == "completed"

    result = client.post(
        f"/api/knowledge/bases/{kb_id}/retrieve",
        json={"query": "durable recall", "use_evidence_skill": False},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["run"]["engine"] == "native.interest-growth"
    assert payload["result"]["evidence_status"] == "candidate_not_evidence"
    candidates = payload["result"]["provenance_candidates"]
    assert candidates and candidates[0]["source_id"] == source_id
    assert candidates[0]["status"] == "candidate_not_evidence"

    other = client.post("/api/areas", json={
        "name": "Music", "slug": "music", "domain_pack_id": "general",
    }).json()
    denied = client.post(
        f"/api/knowledge/bases/{kb_id}/retrieve",
        headers={"X-PG-Interest-Area": other["id"]},
        json={"query": "durable recall"},
    )
    assert denied.status_code == 404


def test_native_tutor_persists_host_session_turn_and_replay(client, monkeypatch):
    from interest_growth_native import NativeEngineBundle, SQLiteExecutionStore
    from interest_growth_native.llm import DeterministicLLM
    from pg_api import native_execution
    from pg_api.native_execution import HostKnowledgeResolver
    from pg_api.db import TutorTurnModel, get_session_factory
    from pg_shared import get_settings
    from sqlalchemy.engine import make_url

    database = Path(make_url(get_settings().database_url).database)
    bundle = NativeEngineBundle(
        knowledge_resolver=HostKnowledgeResolver(),
        store=SQLiteExecutionStore(database),
        llm=DeterministicLLM("NATIVE"),
    )
    monkeypatch.setattr(native_execution, "_bundle", bundle)
    monkeypatch.setattr(native_execution, "_bundle_database_url", get_settings().database_url)

    session = client.post("/api/tutor/sessions", json={"title": "Native tutor"})
    assert session.status_code == 200, session.text
    session_id = session.json()["id"]
    started = client.post(
        f"/api/tutor/sessions/{session_id}/native-turns",
        headers={"X-PG-Native-Session": session_id},
        json={"content": "Explain retrieval practice", "capability": "chat"},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["run"]["state"] == "completed"
    assert any(x["category"] == "answer_delta" for x in body["events"])
    turn_id = body["turn"]["id"]
    assert body["turn"]["answer_text"] == "NATIVE:Explain retrieval practice"
    assert body["turn"]["status"] == "completed"

    replay = client.get(
        f"/api/tutor/sessions/{session_id}/native-turns/{turn_id}/events",
        headers={"X-PG-Native-Session": session_id},
    )
    assert replay.status_code == 200, replay.text
    assert [x["seq"] for x in replay.json()["events"]] == sorted(
        x["seq"] for x in replay.json()["events"]
    )
    with get_session_factory()() as db:
        persisted = db.get(TutorTurnModel, turn_id)
        assert persisted.upstream_turn_id == body["run"]["id"]
        assert persisted.input_json["provider"] == "native.interest-growth"

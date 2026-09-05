from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from pg_api.db import (
    CURRENT_SCHEMA_VERSION,
    TutorPersonaModel,
    TutorSessionModel,
    get_session_factory,
    init_db,
    reset_engine_for_tests,
)


def _set_database(monkeypatch, path) -> str:
    url = f"sqlite:///{path}"
    monkeypatch.setenv("APP_DATABASE_URL", url)
    reset_engine_for_tests()
    return url


def _make_marked_database(path, version: int, *, include_persona_id: bool) -> str:
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    persona_column = ", persona_id TEXT" if include_persona_id else ""
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
        ))
        connection.execute(text(
            f"CREATE TABLE tutor_sessions (id TEXT PRIMARY KEY, title TEXT{persona_column})"
        ))
        connection.execute(
            text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
            {"version": version},
        )
    engine.dispose()
    return url


def test_fresh_current_schema_persists_tutor_session_persona_id(tmp_path, monkeypatch):
    url = _set_database(monkeypatch, tmp_path / "fresh.db")
    init_db()

    engine = create_engine(url)
    assert {column["name"] for column in inspect(engine).get_columns("tutor_sessions")} >= {
        "persona_id"
    }
    with engine.connect() as connection:
        version = connection.execute(text("SELECT MAX(version) FROM schema_migrations")).scalar_one()
    assert version == CURRENT_SCHEMA_VERSION

    with get_session_factory()() as db:
        persona = TutorPersonaModel(name="Schema 回归导师", content="持久化身份")
        db.add(persona)
        db.flush()
        session = TutorSessionModel(title="Schema 回归会话", persona_id=persona.id)
        db.add(session)
        db.commit()
        session_id = session.id
        persona_id = persona.id

    with get_session_factory()() as db:
        persisted = db.get(TutorSessionModel, session_id)
        assert persisted is not None
        assert persisted.persona_id == persona_id

    engine.dispose()
    reset_engine_for_tests()


def test_old_schema_version_fails_closed(tmp_path, monkeypatch):
    url = _make_marked_database(tmp_path / "old.db", CURRENT_SCHEMA_VERSION - 1, include_persona_id=False)
    monkeypatch.setenv("APP_DATABASE_URL", url)
    reset_engine_for_tests()

    with pytest.raises(RuntimeError, match="unsupported"):
        init_db()

    reset_engine_for_tests()


def test_current_marker_with_malformed_shape_fails_closed(tmp_path, monkeypatch):
    url = _make_marked_database(tmp_path / "malformed.db", CURRENT_SCHEMA_VERSION, include_persona_id=False)
    monkeypatch.setenv("APP_DATABASE_URL", url)
    reset_engine_for_tests()

    with pytest.raises(RuntimeError, match=r"current schema shape is incomplete.*tutor_sessions\.persona_id"):
        init_db()

    reset_engine_for_tests()

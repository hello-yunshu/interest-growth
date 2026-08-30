from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, inspect, select, text

from pg_api.db import (
    ServerMetadataModel,
    get_engine,
    get_session_factory,
    init_db,
    reset_engine_for_tests,
)


def _identity() -> dict[str, str] | None:
    with get_session_factory()() as db:
        row = db.scalar(select(ServerMetadataModel).limit(1))
        if row is None:
            return None
        return {
            "server_instance_id": row.server_instance_id,
            "server_display_name": row.server_display_name,
        }


def _instance_ids() -> list[str]:
    with get_session_factory()() as db:
        return [
            row.server_instance_id
            for row in db.scalars(
                select(ServerMetadataModel).order_by(ServerMetadataModel.created_at)
            )
        ]


# ------------------------------------------------------------- fresh database


def test_fresh_database_generates_single_identity(client):
    """Gate C 21.6: a fresh server initializes its identity exactly once."""
    identity = _identity()
    assert identity is not None
    UUID(identity["server_instance_id"])  # must be a valid UUID
    assert identity["server_display_name"] == "Interest Growth Server"
    assert len(_instance_ids()) == 1


# ------------------------------------------------------------- restart


def test_restart_preserves_identity(client):
    """Gate C 21.6: re-initializing the same database never changes identity."""
    before = _identity()
    reset_engine_for_tests()
    init_db()
    assert _identity() == before
    assert len(_instance_ids()) == 1


# ------------------------------------------------------------- different servers


def test_second_independent_server_has_different_identity(client, tmp_path):
    """Gate C 21.6: two fresh servers never share an identity."""
    first = _identity()
    other_url = f"sqlite:///{tmp_path / 'other.db'}"
    reset_engine_for_tests()
    init_db(database_url=other_url)
    with get_session_factory(other_url)() as db:
        row = db.scalar(select(ServerMetadataModel).limit(1))
    assert row is not None
    assert row.server_instance_id != first["server_instance_id"]
    reset_engine_for_tests()


def test_singleton_index_rejects_second_identity_row(client):
    """The unique singleton index enforces exactly one server identity row."""
    from sqlalchemy.exc import IntegrityError

    with get_session_factory()() as db:
        db.add(ServerMetadataModel(server_instance_id="second-instance-id"))
        try:
            db.commit()
            assert False, "a second identity row must be rejected"
        except IntegrityError:
            db.rollback()
        count = db.execute(text("SELECT COUNT(*) FROM server_metadata")).scalar()
    assert count == 1


# ------------------------------------------------------------- display name


def test_server_display_name_env_applied_on_fresh_init(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PG_SERVER_DISPLAY_NAME", "Home Lab")
    fresh_url = f"sqlite:///{tmp_path / 'named.db'}"
    reset_engine_for_tests()
    init_db(database_url=fresh_url)
    with get_session_factory(fresh_url)() as db:
        row = db.scalar(select(ServerMetadataModel).limit(1))
    assert row is not None
    assert row.server_display_name == "Home Lab"
    reset_engine_for_tests()

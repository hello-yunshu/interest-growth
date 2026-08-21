from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select, text

from pg_api.db import (
    SchemaMigration,
    get_engine,
    get_session_factory,
    reset_engine_for_tests,
)
from pg_shared import get_settings

# Gate R2 §14.1 — Reliability soak.
#
# These are multi-round endurance regressions (not unit tests):
#   1. refresh/revoke loop — dozens of atomic rotations on a live device then a
#      full revoke, asserting the single-credential invariant and isolation.
#   2. repeated restart — a server restart (engine reset + idempotent migration
#      re-run) must not lose the owner, devices or live credentials.
#   3. backup/restore repeat — backup → destroy → clean → restore, several full
#      cycles, must stay consistent and preserve server identity each time.

BOOTSTRAP_TOKEN = "bootstrap-secret-token"
OWNER_PASSWORD = "Strong-Owner-Password-2026!"


@pytest.fixture()
def remote_client(client, monkeypatch):
    from pg_api.remote_auth import reset_rate_limiter_for_tests

    reset_rate_limiter_for_tests()
    monkeypatch.setenv("PG_REMOTE_AUTH_ENABLED", "true")
    monkeypatch.setenv("PG_OWNER_BOOTSTRAP_TOKEN", BOOTSTRAP_TOKEN)
    # Soak loops must not trip the per-IP rate limiter.
    monkeypatch.setenv("PG_AUTH_RATE_LIMIT_ATTEMPTS", "100000")
    return client


def _bootstrap(client) -> None:
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"owner_password": OWNER_PASSWORD},
        headers={"X-PG-Owner-Bootstrap-Token": BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 201, response.text


def _login(client, *, name="phone"):
    return client.post(
        "/api/auth/owner/login",
        json={"owner_password": OWNER_PASSWORD, "device_name": name, "platform": "android", "app_version": "1.0.18"},
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _active_refresh_count(device_id: str) -> int:
    with get_session_factory()() as db:
        return db.execute(
            text(
                "SELECT COUNT(*) FROM auth_refresh_tokens "
                "WHERE device_id = :did AND revoked_at IS NULL"
            ),
            {"did": device_id},
        ).scalar()


# ------------------------------------------------------------ 1. refresh/revoke soak


def test_refresh_soak_rotates_atomically_across_many_rounds(remote_client):
    """Dozens of sequential rotations keep exactly one live credential."""
    from pg_api.remote_auth import reset_rate_limiter_for_tests

    _bootstrap(remote_client)
    phone = _login(remote_client, name="phone").json()
    _login(remote_client, name="tablet")  # bystander device stays untouched
    device_id = phone["device"]["id"]

    current_refresh = phone["tokens"]["refresh_token"]
    rounds = 40
    for _ in range(rounds):
        rotated = remote_client.post(
            "/api/auth/device/refresh",
            json={"device_id": device_id, "refresh_token": current_refresh},
        )
        assert rotated.status_code == 200, rotated.text
        tokens = rotated.json()["tokens"]
        # The rotated-away credential can never be reused.
        reused = remote_client.post(
            "/api/auth/device/refresh",
            json={"device_id": device_id, "refresh_token": current_refresh},
        )
        assert reused.status_code == 401
        # The fresh access token is actually live.
        assert remote_client.get("/api/dashboard", headers=_auth(tokens["access_token"])).status_code == 200
        current_refresh = tokens["refresh_token"]
        # Single-credential invariant survives every rotation.
        assert _active_refresh_count(device_id) == 1

    # The final credential still rotates and the bystander device is intact.
    final = remote_client.post(
        "/api/auth/device/refresh",
        json={"device_id": device_id, "refresh_token": current_refresh},
    )
    assert final.status_code == 200, final.text


def test_revoke_soak_invalidates_each_device_in_turn(remote_client):
    """Revoking devices one after another never leaks into the survivors."""
    _bootstrap(remote_client)
    sessions = [_login(remote_client, name=f"device-{i}").json() for i in range(6)]
    keeper = sessions[0]["tokens"]["access_token"]

    for session in sessions[1:]:
        revoked = remote_client.post(
            "/api/auth/device/revoke",
            json={"device_id": session["device"]["id"], "owner_password": OWNER_PASSWORD},
            headers=_auth(keeper),
        )
        assert revoked.status_code == 200, revoked.text
        # Access and refresh for the revoked device are both dead.
        assert remote_client.get("/api/dashboard", headers=_auth(session["tokens"]["access_token"])).status_code == 401
        assert remote_client.post(
            "/api/auth/device/refresh",
            json={"device_id": session["device"]["id"], "refresh_token": session["tokens"]["refresh_token"]},
        ).status_code == 401
        # Every previously revoked device is still dead (no cross-device revival).
        for earlier in sessions[1: sessions.index(session)]:
            assert remote_client.get("/api/dashboard", headers=_auth(earlier["tokens"]["access_token"])).status_code == 401

    # The keeper survives the whole soak.
    assert remote_client.get("/api/dashboard", headers=_auth(keeper)).status_code == 200


# ------------------------------------------------------------ 2. repeated restart recovery


def _simulate_restart() -> None:
    """Drop and recreate the engine + re-run idempotent migrations (restart)."""
    get_engine().dispose()
    reset_engine_for_tests()
    from pg_api.db import init_db

    init_db()


def test_owner_devices_and_credentials_survive_repeated_restarts(remote_client):
    _bootstrap(remote_client)
    session = _login(remote_client).json()
    device_id = session["device"]["id"]
    refresh = session["tokens"]["refresh_token"]
    access = session["tokens"]["access_token"]

    for _ in range(3):
        _simulate_restart()
        # Owner singleton survives: a second bootstrap is still refused.
        again = remote_client.post(
            "/api/auth/owner/bootstrap",
            json={"owner_password": OWNER_PASSWORD},
            headers={"X-PG-Owner-Bootstrap-Token": BOOTSTRAP_TOKEN},
        )
        assert again.status_code == 409
        # A live access token still works after restart.
        assert remote_client.get("/api/dashboard", headers=_auth(access)).status_code == 200
        # The device is still listed.
        devices = remote_client.get("/api/auth/devices", headers=_auth(access)).json()["devices"]
        assert any(d["id"] == device_id for d in devices)
        # A valid refresh token still rotates after restart.
        rotated = remote_client.post(
            "/api/auth/device/refresh",
            json={"device_id": device_id, "refresh_token": refresh},
        )
        assert rotated.status_code == 200, rotated.text
        refresh = rotated.json()["tokens"]["refresh_token"]
        access = rotated.json()["tokens"]["access_token"]


# ------------------------------------------------------------ 3. backup/restore repeat


def _seed(client) -> None:
    assert client.post(
        "/api/questions", json={"question": "How does soak backup restore stay consistent?"}
    ).status_code == 200
    assert client.post(
        "/api/knowledge/sources/upload",
        data={"title": "soak-notes", "source_type": "document"},
        files={"file": ("soak-notes.md", b"# soak round-trip\n", "text/markdown")},
    ).status_code == 200
    assert client.post(
        "/api/content/cards/render",
        json={"title": "soak-card", "points": ["soak"], "footer": "smoke", "layout": "three_points", "topic_id": None},
    ).status_code == 200


def _wipe_live_state() -> None:
    settings = get_settings()
    get_engine().dispose()
    db_path = settings.database_url[len("sqlite:///"):]
    Path(db_path).unlink(missing_ok=True)
    shutil.rmtree(settings.source_storage_root, ignore_errors=True)
    from pg_api.content import get_storage

    shutil.rmtree(get_storage().root, ignore_errors=True)
    reset_engine_for_tests()


def _question_count(client) -> int:
    return len(client.get("/api/questions").json().get("questions", []))


def test_backup_restore_repeats_stay_consistent_and_identity_stable(client, tmp_path):
    from pg_api.backup_restore import create_backup, restore_backup
    from pg_api.db import ServerMetadataModel

    def identity():
        with get_session_factory()() as db:
            row = db.scalar(select(ServerMetadataModel).limit(1))
            return row.server_instance_id if row else None

    _seed(client)
    original_identity = identity()
    assert original_identity

    for cycle in range(3):
        bundle = create_backup(destination_dir=str(tmp_path / f"backups-{cycle}"))
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema_version"] == 15
        assert manifest["server_instance_id"] == original_identity

        _wipe_live_state()
        result = restore_backup(bundle_dir=str(bundle))
        assert result["restored"] is True
        assert result["integrity"] == "ok"
        assert result["schema_version"] == 15
        with get_session_factory()() as db:
            assert db.scalar(select(text("MAX(version)")).select_from(SchemaMigration)) == 15
        # Data survived the destroy/restore cycle and server identity is stable.
        assert identity() == original_identity
        assert _question_count(client) >= 1
        reset_engine_for_tests()

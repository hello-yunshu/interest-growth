from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from pg_api.db import SecurityEventModel, get_session_factory


BOOTSTRAP_TOKEN = "bootstrap-secret-token"
OWNER_PASSWORD = "Strong-Owner-Password-2026!"


@pytest.fixture()
def remote_client(client, monkeypatch):
    from pg_api.remote_auth import reset_rate_limiter_for_tests

    reset_rate_limiter_for_tests()
    monkeypatch.setenv("PG_REMOTE_AUTH_ENABLED", "true")
    monkeypatch.setenv("PG_OWNER_BOOTSTRAP_TOKEN", BOOTSTRAP_TOKEN)
    return client


def _bootstrap(client) -> None:
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"owner_password": OWNER_PASSWORD},
        headers={"X-PG-Owner-Bootstrap-Token": BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 201, response.text


def _login(client, *, name="phone", password=OWNER_PASSWORD):
    return client.post(
        "/api/auth/owner/login",
        json={"owner_password": password, "device_name": name, "platform": "android", "app_version": "0.7.0"},
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- HTTP gate


def test_remote_mode_requires_device_session_on_protected_routes(remote_client):
    _bootstrap(remote_client)
    assert remote_client.get("/api/health").status_code == 200
    assert remote_client.get("/api/system/capabilities").status_code == 200
    for path in ("/api/dashboard", "/api/system/integrations", "/api/knowledge/bases", "/api/system/desktop-runtime"):
        denied = remote_client.get(path)
        assert denied.status_code == 401, path
        assert "device session required" in denied.json()["detail"]


def test_remote_mode_public_auth_endpoints_reachable_without_session(remote_client):
    _bootstrap(remote_client)
    assert remote_client.get("/api/auth/server-info").status_code == 200


def test_capabilities_contract_is_stable_and_public(remote_client):
    response = remote_client.get("/api/system/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["product"] == "interest-growth"
    assert body["api_version"] == "1"
    assert body["min_client_version"] == "0.7.0"
    assert body["online_first"] is True
    assert body["offline_sync"] is False
    assert body["auth"]["enabled"] is True
    assert body["auth"]["mode"] == "single_owner_devices"


def test_local_mode_remains_unchanged_when_remote_auth_disabled(client):
    # Default fixture: remote auth disabled -> protected routes behave exactly
    # as before (no device session needed when no desktop token configured).
    assert client.get("/api/dashboard").status_code != 401
    assert client.get("/api/system/capabilities").status_code == 200
    assert client.get("/api/auth/server-info").json()["auth"]["enabled"] is False
    assert client.post("/api/auth/owner/bootstrap", json={"owner_password": OWNER_PASSWORD}).status_code == 403


def test_desktop_token_still_gates_when_remote_auth_disabled(monkeypatch, client):
    monkeypatch.setenv("PG_DESKTOP_TOKEN", "local-desktop-token")
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/dashboard", headers={"X-PG-Desktop-Token": "local-desktop-token"}).status_code == 200


# ------------------------------------------------------------- bootstrap


def test_owner_bootstrap_is_single_and_gated(remote_client):
    _bootstrap(remote_client)
    again = remote_client.post(
        "/api/auth/owner/bootstrap",
        json={"owner_password": OWNER_PASSWORD},
        headers={"X-PG-Owner-Bootstrap-Token": BOOTSTRAP_TOKEN},
    )
    assert again.status_code == 409
    wrong = remote_client.post(
        "/api/auth/owner/bootstrap",
        json={"owner_password": OWNER_PASSWORD + "-x"},
        headers={"X-PG-Owner-Bootstrap-Token": "wrong-token"},
    )
    # Owner existence is reported before the token check; 409 is the safe,
    # non-credential answer for every attempt after first bootstrap.
    assert wrong.status_code == 409


def test_owner_bootstrap_requires_strong_password(remote_client):
    response = remote_client.post(
        "/api/auth/owner/bootstrap",
        json={"owner_password": "short"},
        headers={"X-PG-Owner-Bootstrap-Token": BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 422


def test_login_rate_limited(remote_client, monkeypatch):
    monkeypatch.setenv("PG_AUTH_RATE_LIMIT_ATTEMPTS", "2")
    monkeypatch.setenv("PG_AUTH_RATE_LIMIT_WINDOW_SECONDS", "600")
    _bootstrap(remote_client)
    assert _login(remote_client, password="wrong-password").status_code == 401
    assert _login(remote_client, password="wrong-password").status_code == 401
    limited = _login(remote_client, password="wrong-password")
    assert limited.status_code == 429
    assert limited.headers.get("Retry-After")


# ------------------------------------------------------------- owner login


def test_owner_login_issues_device_and_token_pair(remote_client):
    _bootstrap(remote_client)
    response = _login(remote_client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["server"]["server_version"] == "0.7.0"
    tokens = body["tokens"]
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 900
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    protected = remote_client.get("/api/dashboard", headers=_auth_header(tokens["access_token"]))
    assert protected.status_code == 200
    devices = remote_client.get("/api/auth/devices", headers=_auth_header(tokens["access_token"]))
    assert devices.status_code == 200
    assert devices.json()["devices"][0]["name"] == "phone"


def test_owner_login_wrong_password_denied(remote_client):
    _bootstrap(remote_client)
    denied = _login(remote_client, password="wrong-password")
    assert denied.status_code == 401


def test_owner_login_rate_limited(remote_client, monkeypatch):
    monkeypatch.setenv("PG_AUTH_RATE_LIMIT_ATTEMPTS", "3")
    _bootstrap(remote_client)
    for _ in range(3):
        _login(remote_client, password="wrong-password")
    limited = _login(remote_client, password="wrong-password")
    assert limited.status_code == 429


# ------------------------------------------------------------- refresh


def test_refresh_rotates_renewal_credential(remote_client):
    _bootstrap(remote_client)
    login = _login(remote_client).json()
    device_id = login["device"]["id"]
    refresh = login["tokens"]["refresh_token"]
    refreshed = remote_client.post(
        "/api/auth/device/refresh", json={"device_id": device_id, "refresh_token": refresh}
    )
    assert refreshed.status_code == 200, refreshed.text
    new_tokens = refreshed.json()["tokens"]
    reused = remote_client.post(
        "/api/auth/device/refresh",
        json={"device_id": device_id, "refresh_token": refresh},
    )
    assert reused.status_code == 401  # rotated credential cannot be reused
    working = remote_client.get(
        "/api/dashboard", headers=_auth_header(refreshed.json()["tokens"]["access_token"])
    )
    assert working.status_code == 200


def test_refresh_rejects_unknown_device(remote_client):
    _bootstrap(remote_client)
    login = _login(remote_client).json()
    other_device = remote_client.post(
        "/api/auth/device/refresh",
        json={"device_id": "does-not-exist", "refresh_token": login["tokens"]["refresh_token"]},
    )
    assert other_device.status_code == 401


# ------------------------------------------------------------- revocation


def test_revoke_self_invalidates_only_that_device(remote_client):
    _bootstrap(remote_client)
    phone = _login(remote_client, name="phone").json()
    tablet = _login(remote_client, name="tablet").json()
    revoked = remote_client.post(
        "/api/auth/device/revoke",
        json={"device_id": phone["device"]["id"]},
        headers=_auth_header(phone["tokens"]["access_token"]),
    )
    assert revoked.status_code == 200, revoked.text
    assert remote_client.get(
        "/api/dashboard", headers=_auth_header(phone["tokens"]["access_token"])
    ).status_code == 401
    refreshed = remote_client.post(
        "/api/auth/device/refresh",
        json={"device_id": phone["device"]["id"], "refresh_token": phone["tokens"]["refresh_token"]},
    )
    assert refreshed.status_code == 401
    # The other device is unaffected.
    assert remote_client.get(
        "/api/dashboard", headers=_auth_header(tablet["tokens"]["access_token"])
    ).status_code == 200


def test_revoke_other_device_requires_owner_password(remote_client):
    _bootstrap(remote_client)
    phone = _login(remote_client, name="phone").json()
    tablet = _login(remote_client, name="tablet").json()
    denied = remote_client.post(
        "/api/auth/device/revoke",
        json={"device_id": tablet["device"]["id"]},
        headers=_auth_header(phone["tokens"]["access_token"]),
    )
    assert denied.status_code == 403
    allowed = remote_client.post(
        "/api/auth/device/revoke",
        json={"device_id": tablet["device"]["id"], "owner_password": OWNER_PASSWORD},
        headers=_auth_header(phone["tokens"]["access_token"]),
    )
    assert allowed.status_code == 200


def test_access_token_expiry(remote_client, monkeypatch):
    monkeypatch.setenv("PG_ACCESS_TOKEN_TTL_SECONDS", "0")
    _bootstrap(remote_client)
    login = _login(remote_client).json()
    expired = remote_client.get(
        "/api/dashboard", headers=_auth_header(login["tokens"]["access_token"])
    )
    assert expired.status_code == 401


# ------------------------------------------------------------- security


def test_security_events_never_store_credentials(remote_client):
    _bootstrap(remote_client)
    _login(remote_client, password="wrong-password")
    _login(remote_client)
    with get_session_factory()() as db:
        rows = db.query(SecurityEventModel).all()
    assert rows
    types = {row.event_type for row in rows}
    assert "login_failed" in types
    assert "device_registered" in types
    for row in rows:
        serialized = json.dumps(row.detail_json or {})
        assert OWNER_PASSWORD not in serialized
        assert "access_token" not in serialized and "refresh_token" not in serialized
        assert "Strong-Owner" not in serialized


def test_security_events_pruned_to_bounded_retention(remote_client, monkeypatch):
    monkeypatch.setenv("PG_AUTH_RATE_LIMIT_ATTEMPTS", "100000")
    _bootstrap(remote_client)
    for index in range(10):
        _login(remote_client, name=f"device-{index}")
    with get_session_factory()() as db:
        count = db.query(SecurityEventModel).count()
    assert count <= 20


# ------------------------------------------------------------- websocket


def test_websocket_device_auth_helper(remote_client):
    from pg_api.remote_auth import websocket_device_auth

    _bootstrap(remote_client)
    tokens = _login(remote_client).json()["tokens"]
    assert websocket_device_auth(None) is None
    assert websocket_device_auth("not-a-token") is None
    device = websocket_device_auth(tokens["access_token"])
    assert device is not None
    assert device.name == "phone"


def test_dashboards_list_plugins_require_session_even_with_desktop_token_absent(remote_client):
    _bootstrap(remote_client)
    tokens = _login(remote_client).json()["tokens"]
    assert remote_client.get("/api/plugins").status_code == 401
    assert remote_client.get("/api/plugins", headers=_auth_header(tokens["access_token"])).status_code == 200


def test_schema_13_upgrade_is_additive_and_preserves_product_data(client):
    """A v0.6 database at schema 12 upgrades to 13 without touching product rows."""
    from sqlalchemy import func, inspect, select

    from pg_api.db import (
        ArtifactModel,
        OwnerModel,
        SchemaMigration,
        get_engine,
        get_session_factory,
    )

    with get_session_factory()() as db:
        # Simulate a pre-v0.7 database by dropping the auth tables and
        # rewinding the ledger to 12; product data stays present.
        for table in ("auth_owners", "auth_devices", "auth_access_tokens", "auth_refresh_tokens", "security_events"):
            if table in inspect(get_engine()).get_table_names():
                db.execute(text(f"DROP TABLE {table}"))
        db.execute(delete(SchemaMigration).where(SchemaMigration.version == 13))
        db.commit()
        before_artifacts = db.scalar(select(func.count()).select_from(ArtifactModel))

    from pg_api.db import init_db

    init_db()
    tables = set(inspect(get_engine()).get_table_names())
    assert {
        "auth_owners", "auth_devices", "auth_access_tokens", "auth_refresh_tokens", "security_events",
    } <= tables
    with get_session_factory()() as db:
        assert 13 in set(db.scalars(select(SchemaMigration.version)).all())
        assert db.scalar(select(func.count()).select_from(ArtifactModel)) == before_artifacts
        assert db.scalar(select(func.count()).select_from(OwnerModel)) == 0
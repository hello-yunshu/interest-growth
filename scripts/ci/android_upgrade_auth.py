#!/usr/bin/env python3
"""Fail-closed authentication and redacted evidence helpers for Android upgrade CI."""

import hashlib
import json


class AuthPreflightError(RuntimeError):
    """The native authenticated preflight did not prove a usable session."""


SUPPORTED_AUTH_MODES = {"password_exchange", "refresh_exchange", "legacy_session"}


def token_fingerprint(token):
    if not token:
        return None
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def redact_secrets(value, secrets):
    """Redact exact secret strings recursively without exposing credentials."""
    if isinstance(value, dict):
        return {str(k): redact_secrets(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v, secrets) for v in value]
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    return text


def canonical_auth_evidence(auth_mode, *, owner_password=None, bearer_token=None,
                            refresh_token=None, device_id=None,
                            server_instance_id=None, source_schema="v1",
                            source_version=None, session_present=False):
    if auth_mode not in SUPPORTED_AUTH_MODES:
        raise AuthPreflightError(f"unsupported auth_mode={auth_mode!r}")
    if not (owner_password or bearer_token or refresh_token or session_present):
        raise AuthPreflightError("authenticated upgrade flow has no credential material")
    return {
        "schema": "android-upgrade-auth-v1",
        "auth_mode": auth_mode,
        "owner_password_present": bool(owner_password),
        "owner_password_length": len(owner_password) if owner_password else 0,
        "bearer_token_present": bool(bearer_token),
        "bearer_token_length": len(bearer_token) if bearer_token else 0,
        "bearer_token_sha256_prefix": token_fingerprint(bearer_token),
        "refresh_token_present": bool(refresh_token),
        "refresh_token_length": len(refresh_token) if refresh_token else 0,
        "refresh_token_sha256_prefix": token_fingerprint(refresh_token),
        "session_present": bool(session_present),
        "device_id_present": bool(device_id),
        "server_instance_id_present": bool(server_instance_id),
        "source_schema": source_schema,
        "source_version": source_version,
    }


def classify_preflight_status(status):
    try:
        code = int(status)
    except (TypeError, ValueError) as exc:
        raise AuthPreflightError(f"authenticated preflight returned invalid status={status!r}") from exc
    if 200 <= code < 300:
        return {"result": "PASS", "status": code}
    if code in (401, 403):
        raise AuthPreflightError(f"authenticated preflight rejected credential with HTTP {code}")
    raise AuthPreflightError(f"authenticated preflight did not prove success: HTTP {code}")


def sanitize_session_status(status):
    """Keep only non-secret continuity fields from remote_session_status."""
    if not isinstance(status, dict):
        raise AuthPreflightError("remote_session_status returned no object")
    allowed = ("enrolled", "connected", "authExpired", "identityChanged",
               "refreshTokenStored", "runtimeId", "serverInstanceId", "deviceId")
    return {key: status[key] for key in allowed if key in status}


def write_json(path, payload):
    with open(path, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)

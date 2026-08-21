from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from pg_shared import get_settings

from .db import (
    DeviceAccessTokenModel,
    DeviceModel,
    DeviceRefreshTokenModel,
    OwnerModel,
    SecurityEventModel,
    get_server_identity,
    get_session_factory,
    now_utc,
)

router = APIRouter(prefix="/auth", tags=["remote-auth"])

SERVER_VERSION = "1.0.2"
API_VERSION = "1"
# Patch release: no protocol/API break, so existing v1.0.0 clients remain
# compatible. Raised only when a compatibility-breaking client change lands.
MIN_CLIENT_VERSION = "1.0.0"
PRODUCT_NAME = "interest-growth"

# Public by contract: health, capability metadata, and the authentication
# endpoints themselves. Everything else authenticates in remote mode.
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/api/health",
        "/api/system/capabilities",
        "/api/auth/server-info",
        "/api/auth/owner/bootstrap",
        "/api/auth/owner/login",
        "/api/auth/device/refresh",
    }
)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_PASSWORD_MIN_LENGTH = 10
_DEVICE_NAME_MAX = 120
_RATE_LIMITER: dict[str, tuple[int, float]] = {}
_RATE_LOCK = threading.Lock()
_SECURITY_EVENT_RETENTION = 5000


# ---------------------------------------------------------------- password


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; normalize for safe comparisons."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return "$".join(
        (
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    try:
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# ----------------------------------------------------------------- tokens


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_token_pair(db, device_id: str) -> dict[str, Any]:
    """Stage a new access/refresh pair in the caller's transaction.

    Deliberately does NOT commit: callers own the transaction so that
    rotation and issuance are atomic with the consume of the old token.
    """
    settings = get_settings()
    now = now_utc()
    access = _new_token()
    refresh = _new_token()
    db.add(
        DeviceAccessTokenModel(
            device_id=device_id,
            token_hash=_token_hash(access),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.access_token_ttl_seconds),
        )
    )
    refresh_row = DeviceRefreshTokenModel(
        device_id=device_id,
        token_hash=_token_hash(refresh),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    db.add(refresh_row)
    db.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": settings.access_token_ttl_seconds,
        "token_type": "Bearer",
        "refresh_id": refresh_row.id,
    }


def _device_for_access_token(token: str | None) -> DeviceModel | None:
    if not token:
        return None
    digest = _token_hash(token)
    now = now_utc()
    with get_session_factory()() as db:
        row = db.scalar(
            select(DeviceAccessTokenModel).where(
                DeviceAccessTokenModel.token_hash == digest,
                DeviceAccessTokenModel.revoked_at.is_(None),
            )
        )
        if row is None or _as_utc(row.expires_at) is None or _as_utc(row.expires_at) <= now:
            return None
        device = db.get(DeviceModel, row.device_id)
        if device is None or device.revoked_at is not None:
            return None
        device.last_seen_at = now
        db.commit()
        return device


def authenticate_request(request: Request) -> DeviceModel | None:
    """Resolve the authenticated device from Authorization: Bearer …"""
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return _device_for_access_token(header.split(" ", 1)[1].strip())


def websocket_device_auth(value: str | None) -> DeviceModel | None:
    """Authenticate a WebSocket handshake the same way HTTP requests are.

    Accepts a `Bearer` token from either the query parameter (`access_token`)
    or a `Sec-WebSocket-Protocol` style token; WebSocket clients commonly
    cannot set arbitrary headers.
    """
    return _device_for_access_token(value)


# -------------------------------------------------------------- rate limit


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit_exceeded(scope: str, ip: str) -> bool:
    settings = get_settings()
    key = f"{scope}:{ip}"
    now = time.monotonic()
    with _RATE_LOCK:
        count, window_start = _RATE_LIMITER.get(key, (0, now))
        if now - window_start > settings.auth_rate_limit_window_seconds:
            count = 0
            window_start = now
        if count >= settings.auth_rate_limit_attempts:
            _RATE_LIMITER[key] = (count, window_start)
            return True
        _RATE_LIMITER[key] = (count + 1, window_start)
    return False


def _rate_limited_response() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "too many authentication attempts; try again later"},
        headers={"Retry-After": str(get_settings().auth_rate_limit_window_seconds)},
    )


def reset_rate_limiter_for_tests() -> None:
    """Clear in-memory rate-limit state between tests."""
    with _RATE_LOCK:
        _RATE_LIMITER.clear()


# ---------------------------------------------------------- security events


def record_security_event(
    event_type: str,
    *,
    device_id: str | None = None,
    ip_address: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """Persist bounded audit metadata. Never passwords, tokens or bodies."""
    try:
        with get_session_factory()() as db:
            db.add(
                SecurityEventModel(
                    event_type=event_type,
                    device_id=device_id,
                    ip_address=ip_address[:64],
                    detail_json=dict(detail or {}),
                )
            )
            over = db.scalar(select(func.count()).select_from(SecurityEventModel))
            if (over or 0) > _SECURITY_EVENT_RETENTION:
                excess = db.scalars(
                    select(SecurityEventModel.id)
                    .order_by(SecurityEventModel.created_at.desc())
                    .offset(_SECURITY_EVENT_RETENTION)
                    .limit(1000)
                ).all()
                if excess:
                    db.execute(delete(SecurityEventModel).where(SecurityEventModel.id.in_(excess)))
            db.commit()
    except Exception:
        # Security auditing must never take the API down.
        pass


# --------------------------------------------------------------- ownership


def owner_configured() -> bool:
    with get_session_factory()() as db:
        return db.scalar(select(func.count()).select_from(OwnerModel)) > 0


def _require_remote_mode() -> None:
    if not get_settings().remote_auth_enabled:
        raise HTTPException(403, "remote device authentication is not enabled on this server")


# ------------------------------------------------------------- API schemas


class OwnerBootstrapRequest(BaseModel):
    owner_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=1024)


class OwnerLoginRequest(BaseModel):
    owner_password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(min_length=1, max_length=_DEVICE_NAME_MAX)
    platform: str = Field(default="", max_length=40)
    app_version: str = Field(default="", max_length=32)


class DeviceRefreshRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    refresh_token: str = Field(min_length=1, max_length=512)


class DeviceRevokeRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    owner_password: str | None = Field(default=None, max_length=1024)


# ----------------------------------------------------------------- routes


@router.get("/server-info")
def server_info(request: Request):
    identity = get_server_identity()
    return {
        "product": PRODUCT_NAME,
        "server_version": SERVER_VERSION,
        "api_version": API_VERSION,
        "min_client_version": MIN_CLIENT_VERSION,
        "server_instance_id": identity["server_instance_id"],
        "server_display_name": identity["server_display_name"],
        "auth": {
            "mode": "single_owner_devices",
            "enabled": get_settings().remote_auth_enabled,
            "owner_configured": owner_configured() if get_settings().remote_auth_enabled else False,
        },
        "tls": request.url.scheme == "https",
        "online_first": True,
        "offline_sync": False,
    }


@router.post("/owner/bootstrap", status_code=201)
def owner_bootstrap(body: OwnerBootstrapRequest, request: Request):
    _require_remote_mode()
    if owner_configured():
        raise HTTPException(409, "owner is already configured")
    provided = request.headers.get("X-PG-Owner-Bootstrap-Token", "")
    expected = get_settings().owner_bootstrap_token
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        record_security_event("owner_bootstrap_failed", ip_address=_client_ip(request))
        raise HTTPException(403, "owner bootstrap token missing or invalid")
    ip = _client_ip(request)
    if _rate_limit_exceeded("bootstrap", ip):
        return _rate_limited_response()
    try:
        with get_session_factory()() as db:
            db.add(OwnerModel(password_hash=hash_password(body.owner_password)))
            db.commit()
    except IntegrityError:
        # The unique singleton index is the authority: a concurrent bootstrap
        # that won the race surfaces here as the already-configured answer.
        record_security_event("owner_bootstrap_failed", ip_address=ip)
        raise HTTPException(409, "owner is already configured")
    record_security_event("owner_bootstrapped", ip_address=ip)
    return {"status": "owner_configured", "device_registration_required": True}


@router.post("/owner/login", status_code=201)
def owner_login(body: OwnerLoginRequest, request: Request):
    _require_remote_mode()
    ip = _client_ip(request)
    if _rate_limit_exceeded("login", ip):
        record_security_event("login_rate_limited", ip_address=ip)
        return _rate_limited_response()
    with get_session_factory()() as db:
        owner = db.scalar(select(OwnerModel).order_by(OwnerModel.created_at).limit(1))
        if owner is None or not verify_password(body.owner_password, owner.password_hash):
            record_security_event("login_failed", ip_address=ip)
            raise HTTPException(401, "owner password invalid")
        name = body.device_name.strip()[:_DEVICE_NAME_MAX]
        device = db.scalar(
            select(DeviceModel).where(
                DeviceModel.name == name,
                DeviceModel.platform == body.platform.strip(),
                DeviceModel.revoked_at.is_(None),
            )
        )
        if device is None:
            device = DeviceModel(
                name=name,
                platform=body.platform.strip(),
                app_version=body.app_version.strip(),
            )
            db.add(device)
            db.flush()
        tokens = _issue_token_pair(db, device.id)
        db.commit()
        device_id = device.id
        device_name = device.name
    record_security_event("device_registered", device_id=device_id, ip_address=ip)
    identity = get_server_identity()
    return {
        "device": {"id": device_id, "name": device_name},
        "tokens": tokens,
        "server": {
            "product": PRODUCT_NAME,
            "server_version": SERVER_VERSION,
            "api_version": API_VERSION,
            "min_client_version": MIN_CLIENT_VERSION,
            "server_instance_id": identity["server_instance_id"],
            "server_display_name": identity["server_display_name"],
        },
    }


@router.post("/device/refresh")
def device_refresh(body: DeviceRefreshRequest, request: Request):
    ip = _client_ip(request)
    if _rate_limit_exceeded("refresh", ip):
        return _rate_limited_response()
    now = now_utc()
    digest = _token_hash(body.refresh_token)
    with get_session_factory()() as db:
        row = db.scalar(
            select(DeviceRefreshTokenModel).where(DeviceRefreshTokenModel.token_hash == digest)
        )
        if (
            row is None
            or row.device_id != body.device_id
            or row.revoked_at is not None
            or _as_utc(row.expires_at) is None
            or _as_utc(row.expires_at) <= now
        ):
            record_security_event("refresh_failed", ip_address=ip)
            raise HTTPException(401, "refresh token invalid or already rotated")
        device = db.get(DeviceModel, body.device_id)
        if device is None or device.revoked_at is not None:
            record_security_event("refresh_failed", ip_address=ip)
            raise HTTPException(401, "device revoked")
        # Atomic conditional consume: a single UPDATE revokes the credential
        # only if it is still unconsumed and unexpired. A concurrent winner
        # makes this statement match zero rows, so overlapping rotations can
        # never issue two replacements for the same credential.
        consumed = db.execute(
            update(DeviceRefreshTokenModel)
            .where(
                DeviceRefreshTokenModel.token_hash == digest,
                DeviceRefreshTokenModel.revoked_at.is_(None),
                DeviceRefreshTokenModel.expires_at > now,
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            db.rollback()  # release the write lock; nothing was consumed
            record_security_event("refresh_failed", ip_address=ip)
            raise HTTPException(401, "refresh token invalid or already rotated")
        device.last_seen_at = now
        tokens = _issue_token_pair(db, device.id)
        row.replaced_by = tokens["refresh_id"]
        db.commit()
        device_id = device.id
        device_name = device.name
    record_security_event("refresh_succeeded", device_id=device_id, ip_address=ip)
    return {"device": {"id": device_id, "name": device_name}, "tokens": tokens}


@router.post("/device/revoke")
def device_revoke(body: DeviceRevokeRequest, request: Request):
    _require_remote_mode()
    current: DeviceModel = request.state.device
    now = now_utc()
    with get_session_factory()() as db:
        target = db.get(DeviceModel, body.device_id)
        if target is None:
            raise HTTPException(404, "device not found")
        if target.id != current.id:
            owner = db.scalar(select(OwnerModel).order_by(OwnerModel.created_at).limit(1))
            if owner is None or not body.owner_password or not verify_password(body.owner_password, owner.password_hash):
                raise HTTPException(403, "owner password required to revoke another device")
        target.revoked_at = now
        db.execute(
            delete(DeviceRefreshTokenModel).where(
                DeviceRefreshTokenModel.device_id == target.id,
                DeviceRefreshTokenModel.revoked_at.is_(None),
            )
        )
        db.execute(
            delete(DeviceAccessTokenModel).where(
                DeviceAccessTokenModel.device_id == target.id,
                DeviceAccessTokenModel.revoked_at.is_(None),
            )
        )
        db.commit()
    record_security_event(
        "device_revoked", device_id=target.id, ip_address=_client_ip(request)
    )
    return {"device_id": target.id, "revoked": True}


@router.get("/devices")
def list_devices(request: Request):
    device: DeviceModel = request.state.device
    with get_session_factory()() as db:
        rows = db.scalars(select(DeviceModel).order_by(DeviceModel.created_at)).all()
        return {
            "devices": [
                {
                    "id": row.id,
                    "name": row.name,
                    "platform": row.platform,
                    "app_version": row.app_version,
                    "created_at": row.created_at.isoformat(),
                    "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                    "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                    "current": row.id == device.id,
                }
                for row in rows
            ]
        }


# --------------------------------------------------------------- middleware


async def remote_device_auth_middleware(request: Request, call_next):
    if not get_settings().remote_auth_enabled:
        return await call_next(request)
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    device = authenticate_request(request)
    if device is None:
        record_security_event("auth_failed", ip_address=_client_ip(request))
        return JSONResponse(status_code=401, content={"detail": "device session required"})
    request.state.device = device
    return await call_next(request)

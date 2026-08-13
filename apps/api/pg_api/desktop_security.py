from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from pg_shared import get_settings


SAFE_UNAUTHENTICATED_PATHS = {"/", "/api/health"}


async def desktop_token_middleware(request: Request, call_next):
    expected = get_settings().desktop_token
    if not expected or request.method == "OPTIONS" or request.url.path in SAFE_UNAUTHENTICATED_PATHS:
        return await call_next(request)
    provided = request.headers.get("X-PG-Desktop-Token", "")
    if not provided or not hmac.compare_digest(provided, expected):
        return JSONResponse(status_code=401, content={"detail": "desktop runtime token required"})
    return await call_next(request)


def websocket_token_valid(value: str | None) -> bool:
    expected = get_settings().desktop_token
    if not expected:
        return True
    return bool(value) and hmac.compare_digest(value or "", expected)

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from fastapi import Request

_area_selector: ContextVar[str] = ContextVar("pg_interest_area_selector", default="")


def set_area_selector(value: str):
    return _area_selector.set((value or "").strip())


def reset_area_selector(token) -> None:
    _area_selector.reset(token)


def current_area_selector() -> str:
    return _area_selector.get()


async def interest_area_context_middleware(request: Request, call_next):
    selector = request.headers.get("X-PG-Interest-Area", "")
    token = set_area_selector(selector)
    try:
        response = await call_next(request)
        return response
    finally:
        reset_area_selector(token)

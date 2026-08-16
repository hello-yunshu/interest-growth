from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .desktop_security import desktop_token_middleware
from .area_context import interest_area_context_middleware
from pg_shared.settings import get_settings, validate_settings
from .remote_auth import (
    API_VERSION,
    MIN_CLIENT_VERSION,
    PRODUCT_NAME,
    SERVER_VERSION,
    remote_device_auth_middleware,
    router as remote_auth_router,
)
from .scoping import install_area_scoping_hooks
from .features import seed_feature_flags
from .plugins import get_plugin_runtime
from .domains import seed_domain_packs_and_default_area, seed_domain_personas
from .native_execution import router as native_execution_router
from .routes import areas, career, content, cowriter, growth, knowledge, learning, learning_assets, living_book, questions, research, system, tutor


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Gate C/D §4.2 — fail-closed: a `remote` environment must not start with
    # its remote API unauthenticated. Refuse to boot on a dangerous config.
    validate_settings(get_settings())
    install_area_scoping_hooks()
    init_db()
    seed_domain_packs_and_default_area()
    seed_domain_personas()
    seed_feature_flags()
    get_plugin_runtime(refresh=True)
    yield


app = FastAPI(
    title="Interest Growth API",
    version=SERVER_VERSION,
    description=(
        "General interest learning, research, practice, growth and expression system with Psychology as the default Domain Pack. "
        "Domain Packs shape policy; capability providers never own product data."
    ),
    lifespan=lifespan,
)

app.middleware("http")(interest_area_context_middleware)
app.middleware("http")(desktop_token_middleware)
app.middleware("http")(remote_device_auth_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    system.router,
    areas.router,
    questions.router,
    research.router,
    knowledge.router,
    learning.router,
    learning_assets.router,
    cowriter.router,
    living_book.router,
    tutor.router,
    growth.router,
    content.router,
    career.router,
    remote_auth_router,
):
    app.include_router(router, prefix="/api")

app.include_router(native_execution_router)


@app.get("/")
def root():
    return {
        "name": "Interest Growth",
        "version": SERVER_VERSION,
        "status": "native-execution-product",
        "docs": "/docs",
        "principles": [
            "interest-area-first",
            "psychology-default-domain-pack",
            "own-data-first",
            "human-review-gated",
            "fallback-ready",
            "versioned-knowledge",
        ],
    }

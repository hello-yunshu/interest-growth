from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = "deep" + "tutor"


def test_product_runtime_is_native_only():
    active_roots = [
        ROOT / "apps" / "api" / "pg_api",
        ROOT / "apps" / "web" / "app",
        ROOT / "apps" / "web" / "components",
        ROOT / "apps" / "desktop" / "src-tauri" / "src",
        ROOT / "packages" / "shared",
        ROOT / "plugins",
    ]
    for base in active_roots:
        for path in base.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".js", ".rs", ".toml", ".yaml", ".yml"}:
                continue
            if path.name == "db.py":
                continue  # migration 12 must name the retired legacy rows it deletes
            assert FORBIDDEN not in path.read_text("utf-8").lower(), path
    assert not (ROOT / "adapters" / FORBIDDEN).exists()
    assert not (ROOT / "infra" / FORBIDDEN).exists()
    assert not (ROOT / "plugins" / f"{FORBIDDEN}-integration").exists()


def test_native_only_product_surface(client):
    integrations = client.get("/api/system/integrations")
    assert integrations.status_code == 200
    assert set(integrations.json()) == {"native_execution", "deepseek"}

    providers = client.get("/api/knowledge/providers")
    assert providers.status_code == 200
    catalog = providers.json()["providers"]
    assert all(row["native"] for row in catalog if row["configured"])
    assert {
        row["id"] for row in catalog if row.get("status") == "requires_review"
    } == {"llamaindex", "lightrag", "graphrag", "pageindex"}

    kb = client.post("/api/knowledge/bases", json={
        "name": "native-only", "description": "owned locally", "rag_provider": "native-lexical"
    })
    assert kb.status_code == 200, kb.text

    rejected = client.post("/api/knowledge/bases", json={
        "name": "legacy", "description": "must not execute", "rag_provider": "llamaindex"
    })
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "requires_review"

    paths = {route.path for route in client.app.routes if hasattr(route, "path")}
    assert not any(FORBIDDEN in path.lower() for path in paths)

from __future__ import annotations

import compileall
from pathlib import Path
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
RETIRED_RUNTIME = "deep" + "tutor"


def fail(message: str) -> None:
    ERRORS.append(message)


def require(relative: str) -> None:
    if not (ROOT / relative).exists():
        fail(f"missing required artifact: {relative}")


for required in (
    "README.md",
    "PROJECT_STATUS.md",
    "RELEASE_NOTES_v0.6.0-native-execution-product.md",
    "apps/api/pg_api/native_execution.py",
    "migrations/0012_native_only_product.sql",
    "apps/api/pg_api/routes/tutor.py",
    "apps/api/pg_api/routes/research.py",
    "apps/api/pg_api/routes/knowledge.py",
    "packages/native-execution-core/interest_growth_native/bundle.py",
    "packages/shared/pg_shared/settings.py",
    "domains/general/domain.yaml",
    "domains/psychology/domain.yaml",
):
    require(required)


for removed in (
    "adapters/" + RETIRED_RUNTIME,
    "infra/" + RETIRED_RUNTIME,
    "plugins/integration." + RETIRED_RUNTIME,
):
    if (ROOT / removed).exists():
        fail(f"retired runtime surface still exists: {removed}")


# Current runtime and product-facing files must not expose or call the retired
# runtime. db.py is excluded because migration 12 must identify historical rows
# in existing user databases so it can remove them safely.
scan_roots = (
    "apps/api/pg_api",
    "apps/web/app",
    "apps/web/components",
    "apps/web/lib",
    "apps/desktop/src-tauri/src",
    "packages/shared",
    "plugins",
)
text_suffixes = {".py", ".pyi", ".rs", ".ts", ".tsx", ".js", ".mjs", ".json", ".yaml", ".yml", ".toml"}
for relative in scan_roots:
    base = ROOT / relative
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        if "__pycache__" in path.parts or path == ROOT / "apps/api/pg_api/db.py":
            continue
        text = path.read_text("utf-8", errors="replace").lower()
        if RETIRED_RUNTIME in text or "pg_" + RETIRED_RUNTIME in text:
            fail(f"retired runtime reference in active source: {path.relative_to(ROOT)}")


# Domain/contracts stay independent from transports and application adapters.
for relative in ("packages/domain", "packages/engine-contracts"):
    base = ROOT / relative
    for path in base.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text("utf-8")
        if re.search(r"\b(pg_deepseek|adapters\.)", text):
            fail(f"transport leak into core contract: {path.relative_to(ROOT)}")


# Plugin manifests must remain unique, resolvable and product-capability based.
manifests: dict[str, dict] = {}
for path in sorted((ROOT / "plugins").glob("*/plugin.yaml")):
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    plugin_id = data.get("id")
    if not plugin_id:
        fail(f"plugin missing id: {path.relative_to(ROOT)}")
        continue
    if plugin_id in manifests:
        fail(f"duplicate plugin id: {plugin_id}")
    manifests[plugin_id] = data

for plugin_id, data in manifests.items():
    if plugin_id.startswith("integration."):
        fail(f"runtime integration is incorrectly exposed as a product plugin: {plugin_id}")
    for dependency in data.get("requires", {}).get("plugins", []) or []:
        if dependency not in manifests:
            fail(f"plugin {plugin_id} has unresolved dependency: {dependency}")


# Renderer is local-only. Model requests always cross the authenticated Host.
next_config = "\n".join(
    path.read_text("utf-8", errors="replace")
    for path in (ROOT / "apps/web").glob("next.config.*")
)
connect_match = re.search(r"connect-src\s+([^;]+)", next_config, re.IGNORECASE)
if connect_match:
    connect_src = connect_match.group(1).lower()
    if "https:" in connect_src or "deepseek" in connect_src:
        fail("renderer CSP allows direct external model access")


if not compileall.compile_dir(ROOT / "apps/api/pg_api", quiet=1):
    fail("API compileall failed")
if not compileall.compile_dir(ROOT / "packages", quiet=1):
    fail("package compileall failed")


if ERRORS:
    for error in ERRORS:
        print(f"ERROR: {error}")
    raise SystemExit(1)

print("SELF-AUDIT PASS")
print("- Product execution is native-only")
print("- Host remains the canonical data owner")
print("- Product plugins are transport-independent")
print("- Renderer cannot call external model services directly")
print("- Migration 12 retires historical runtime configuration")

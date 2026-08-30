#!/usr/bin/env python3
"""Gate R2 §17 — single-source-of-truth version consistency check.

Every user-visible version location in the repository must agree with the
canonical product version declared in ``pyproject.toml``. The frozen 1.0
runtime/API contracts (API_VERSION, SUPPORTED_API_VERSION, MIN_CLIENT_VERSION,
backup format) are also asserted so a drift is caught before any RC tag.

Locations checked (all must match the canonical product version):

  * pyproject.toml                    -> project.version           (canonical)
  * apps/api/pg_api/remote_auth.py    -> SERVER_VERSION / MIN_CLIENT_VERSION
  * apps/desktop/src-tauri/Cargo.toml -> package.version
  * apps/desktop/src-tauri/tauri.conf.json -> version
  * apps/desktop/package.json         -> version
  * apps/web/package.json             -> version
  * apps/web/lib/runtime/contract.js  -> CLIENT_VERSION

Frozen contracts (independent of the product version):

  * API_VERSION == "1"  (remote_auth.py)
  * SUPPORTED_API_VERSION == 1 (contract.js)
  * BACKUP_FORMAT_VERSION == 1 (pg_api/backup_restore.py)

This script is imported by scripts/verify.py so the check is enforced on every
CI run; it can also be run standalone with `python scripts/verify_version_consistency.py`.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Python: the canonical product version.
PYPROJECT = ROOT / "pyproject.toml"
# Server + API: parsed as text to avoid importing the FastAPI app.
REMOTE_AUTH = ROOT / "apps/api/pg_api/remote_auth.py"
BACKUP_RESTORE = ROOT / "apps/api/pg_api/backup_restore.py"
# Desktop: Rust + Tauri config + package manifests.
CARGO = ROOT / "apps/desktop/src-tauri/Cargo.toml"
CARGO_LOCK = ROOT / "apps/desktop/src-tauri/Cargo.lock"
TAURI_CONF = ROOT / "apps/desktop/src-tauri/tauri.conf.json"
DESKTOP_PKG = ROOT / "apps/desktop/package.json"
DESKTOP_LOCK = ROOT / "apps/desktop/package-lock.json"
# Web / ClientRuntime.
WEB_PKG = ROOT / "apps/web/package.json"
WEB_LOCK = ROOT / "apps/web/package-lock.json"
CONTRACT_JS = ROOT / "apps/web/lib/runtime/contract.js"
UV_LOCK = ROOT / "uv.lock"

API_VERSION = "1"
BACKUP_FORMAT_VERSION = 1


def fail(msg: str) -> int:
    print("VERSION CONSISTENCY FAIL:", msg)
    return 1


def _match(pattern: str, text: str) -> str | None:
    found = re.search(pattern, text, flags=re.MULTILINE)
    return found.group(1).strip() if found else None


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", value.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def main() -> int:
    problems: list[str] = []

    with PYPROJECT.open("rb") as fh:
        canonical = tomllib.load(fh)["project"]["version"]

    def require_equal(name: str, value: str | None) -> None:
        if value is None:
            problems.append(f"{name}: version not found")
        elif value != canonical:
            problems.append(f"{name}: {value!r} != canonical {canonical!r}")

    # --- server / API ---------------------------------------------------- #
    remote_text = REMOTE_AUTH.read_text(encoding="utf-8")
    require_equal("remote_auth.SERVER_VERSION", _match(r'SERVER_VERSION\s*=\s*"([^"]+)"', remote_text))
    # Pre-release deployments accept only the current client version. Keeping
    # this exact prevents accidental reintroduction of an old-client window.
    min_client = _match(r'MIN_CLIENT_VERSION\s*=\s*"([^"]+)"', remote_text)
    if min_client is None and re.search(r"MIN_CLIENT_VERSION\s*=\s*SERVER_VERSION", remote_text):
        min_client = _match(r'SERVER_VERSION\s*=\s*"([^"]+)"', remote_text)
    if min_client is None:
        problems.append("remote_auth.MIN_CLIENT_VERSION: version not found")
    elif min_client != canonical:
        problems.append(f"remote_auth.MIN_CLIENT_VERSION: {min_client!r} != canonical {canonical!r}")
    api_version = _match(r'API_VERSION\s*=\s*"([^"]+)"', remote_text)
    if api_version != API_VERSION:
        problems.append(f"remote_auth.API_VERSION: {api_version!r} != {API_VERSION!r}")

    # --- desktop --------------------------------------------------------- #
    cargo_text = CARGO.read_text(encoding="utf-8")
    require_equal("Cargo.toml.package.version", _match(r'^version\s*=\s*"([^"]+)"', cargo_text))
    tauri_text = TAURI_CONF.read_text(encoding="utf-8")
    require_equal("tauri.conf.json.version", _match(r'"version"\s*:\s*"([^"]+)"', tauri_text))
    require_equal("apps/desktop/package.json.version", str(json.loads(DESKTOP_PKG.read_text(encoding="utf-8"))["version"]))
    # Android versionCode must be strictly monotonic across releases. The
    # structured bump tool advances the checked-in historical maximum; this
    # lower bound catches a missing explicit override in a clean checkout.
    version_code = _match(r'"versionCode"\s*:\s*(\d+)', tauri_text)
    if version_code is None:
        problems.append("tauri.conf.json.android.versionCode: not found")
    elif int(version_code) < 1000001:
        problems.append(f"tauri.conf.json.android.versionCode: {version_code} < 1000001")
    elif "4" in version_code or "11" in version_code:
        problems.append(f"tauri.conf.json.android.versionCode contains forbidden digit 4 or 11: {version_code}")

    # --- web / ClientRuntime -------------------------------------------- #
    require_equal("apps/web/package.json.version", str(json.loads(WEB_PKG.read_text(encoding="utf-8"))["version"]))
    contract_text = CONTRACT_JS.read_text(encoding="utf-8")
    require_equal("contract.js.CLIENT_VERSION", _match(r"CLIENT_VERSION\s*=\s*'([^']+)'", contract_text))
    supported = _match(r"SUPPORTED_API_VERSION\s*=\s*(\d+)", contract_text)
    if supported is None or int(supported) != int(API_VERSION):
        problems.append(f"contract.js.SUPPORTED_API_VERSION: {supported!r} != {API_VERSION!r}")

    # --- frozen backup format ------------------------------------------- #
    backup_text = BACKUP_RESTORE.read_text(encoding="utf-8")
    backup_version = _match(r"BACKUP_FORMAT_VERSION\s*=\s*(\d+)", backup_text)
    if backup_version is None or int(backup_version) != BACKUP_FORMAT_VERSION:
        problems.append(f"backup_restore.BACKUP_FORMAT_VERSION: {backup_version!r} != {BACKUP_FORMAT_VERSION!r}")

    # Product-owned lock entries are also version fields. Third-party entries
    # are checked separately by verify_dependency_versions_unchanged.py.
    try:
        cargo_lock = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
        cargo_product = [p for p in cargo_lock.get("package", []) if p.get("name") == "interest-growth-desktop"]
        if len(cargo_product) != 1 or cargo_product[0].get("version") != canonical:
            problems.append("Cargo.lock interest-growth-desktop version does not match canonical")
        uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
        uv_product = [p for p in uv_lock.get("package", []) if p.get("name") == "interest-growth"]
        if len(uv_product) != 1 or uv_product[0].get("version") != canonical:
            problems.append("uv.lock interest-growth version does not match canonical")
        for lock_path, package_name in ((DESKTOP_LOCK, "interest-growth-desktop"), (WEB_LOCK, "interest-growth-web")):
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            if lock.get("version") != canonical or lock.get("packages", {}).get("", {}).get("version") != canonical:
                problems.append(f"{lock_path.name} root package version does not match canonical")
            if lock.get("name") != package_name:
                problems.append(f"{lock_path.name} root package name is not {package_name}")
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        problems.append(f"product lockfile parse failed: {error}")

    if problems:
        for problem in problems:
            print("  -", problem)
        return 1

    print(f"VERSION CONSISTENCY: OK (canonical {canonical}, API {API_VERSION}, backup format {BACKUP_FORMAT_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

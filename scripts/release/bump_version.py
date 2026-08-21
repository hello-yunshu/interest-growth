#!/usr/bin/env python3
"""Safely update Interest Growth product-owned version fields.

This tool deliberately edits parsed/anchored product metadata only. It never
performs a repository-wide string replacement, because dependency versions
such as ``webpki-roots`` are not product versions.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parse_semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError(f"invalid product version: {value!r}")
    if "4" in value or "11" in value:
        raise ValueError(f"version strings containing digit 4 or 11 are forbidden: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def replace_once(path: Path, pattern: str, replacement: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"{label}: expected exactly one anchored product field in {path}")
    path.write_text(updated, encoding="utf-8")


def update_package_json(path: Path, new: str, *, expected_name: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") is None or data.get("name") != expected_name:
        raise ValueError(f"{path}: unexpected package root")
    data["version"] = new
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_package_lock(path: Path, new: str, *, expected_name: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") is None or data.get("name") != expected_name:
        raise ValueError(f"{path}: unexpected lockfile root")
    root_package = data.get("packages", {}).get("")
    if root_package is None or root_package.get("name") != expected_name:
        raise ValueError(f"{path}: missing structured root package entry")
    data["version"] = new
    root_package["version"] = new
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_cargo_lock(path: Path, new: str) -> None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    matches = [pkg for pkg in data.get("package", []) if pkg.get("name") == "interest-growth-desktop"]
    if len(matches) != 1:
        raise ValueError(f"{path}: expected one interest-growth-desktop package entry")
    old = matches[0]["version"]
    replace_once(
        path,
        rf'(^name = "interest-growth-desktop"\nversion = "){re.escape(old)}("$)',
        rf"\g<1>{new}\g<2>",
        label="Cargo.lock product package version",
    )


def update_uv_lock(path: Path, new: str) -> None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    matches = [pkg for pkg in data.get("package", []) if pkg.get("name") == "interest-growth"]
    if len(matches) != 1:
        raise ValueError(f"{path}: expected one interest-growth package entry")
    old = matches[0]["version"]
    replace_once(
        path,
        rf'(^name = "interest-growth"\nversion = "){re.escape(old)}("$)',
        rf"\g<1>{new}\g<2>",
        label="uv.lock product package version",
    )


def update_changelog(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if re.search(rf"^## {re.escape(new)}\b", text, flags=re.MULTILINE):
        raise ValueError(f"{path}: version {new} already has a changelog entry")
    entry = (
        f"## {new} — v{new} Stable Candidate ({date.today().isoformat()})\n\n"
        "**Status**: pending Stable Candidate Actions verification.\n\n"
        f"This candidate supersedes the immutable v{old} tag after release-engineering closure.\n\n"
    )
    marker = "# Changelog\n\n"
    if marker not in text:
        raise ValueError(f"{path}: changelog header not found")
    path.write_text(text.replace(marker, marker + entry, 1), encoding="utf-8")


def historical_version_code_max() -> int:
    """Read every locally available release tag as a monotonicity check."""
    try:
        tags = subprocess.check_output(["git", "tag", "--list", "v*"], cwd=ROOT, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        return 0
    maximum = 0
    for tag in tags:
        try:
            text = subprocess.check_output(
                ["git", "show", f"{tag}:apps/desktop/src-tauri/tauri.conf.json"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            continue
        match = re.search(r'"versionCode"\s*:\s*(\d+)', text)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="new product version, e.g. 1.0.20")
    parser.add_argument("--android-version-code", type=int)
    args = parser.parse_args()

    new = args.version
    parse_semver(new)
    pyproject = ROOT / "pyproject.toml"
    with pyproject.open("rb") as handle:
        old = str(tomllib.load(handle)["project"]["version"])
    parse_semver(old)
    if new == old:
        raise SystemExit(f"version is already {new}")

    new_code = args.android_version_code
    tauri = ROOT / "apps/desktop/src-tauri/tauri.conf.json"
    tauri_data = json.loads(tauri.read_text(encoding="utf-8"))
    old_code = int(tauri_data["bundle"]["android"]["versionCode"])
    if new_code is None:
        new_code = old_code + 1
    if new_code <= old_code:
        raise SystemExit(f"android versionCode must increase: {old_code} -> {new_code}")
    historical_max = historical_version_code_max()
    if new_code <= historical_max:
        raise SystemExit(
            f"android versionCode must exceed every available release tag: {new_code} <= {historical_max}"
        )
    if "4" in str(new_code) or "11" in str(new_code):
        raise SystemExit(f"android versionCode containing digit 4 or 11 is forbidden: {new_code}")

    replace_once(pyproject, r'(^version\s*=\s*")[^"]+("$)', rf"\g<1>{new}\g<2>", label="pyproject project.version")
    replace_once(ROOT / "apps/api/pg_api/remote_auth.py", r'(^SERVER_VERSION\s*=\s*")[^"]+("$)', rf"\g<1>{new}\g<2>", label="SERVER_VERSION")
    replace_once(ROOT / "apps/desktop/src-tauri/Cargo.toml", r'(^version\s*=\s*")[^"]+("$)', rf"\g<1>{new}\g<2>", label="Cargo.toml package.version")
    replace_once(ROOT / "apps/desktop/src-tauri/tauri.conf.json", r'("version"\s*:\s*")[^"]+("\s*,)', rf"\g<1>{new}\g<2>", label="tauri version")
    replace_once(ROOT / "apps/desktop/src-tauri/tauri.conf.json", r'("versionCode"\s*:\s*)\d+', rf"\g<1>{new_code}", label="tauri android.versionCode")

    update_package_json(ROOT / "apps/desktop/package.json", new, expected_name="interest-growth-desktop")
    update_package_lock(ROOT / "apps/desktop/package-lock.json", new, expected_name="interest-growth-desktop")
    update_package_json(ROOT / "apps/web/package.json", new, expected_name="interest-growth-web")
    update_package_lock(ROOT / "apps/web/package-lock.json", new, expected_name="interest-growth-web")
    replace_once(ROOT / "apps/web/lib/runtime/contract.js", r"(CLIENT_VERSION\s*=\s*')[^']+(')", rf"\g<1>{new}\g<2>", label="CLIENT_VERSION")
    update_cargo_lock(ROOT / "apps/desktop/src-tauri/Cargo.lock", new)
    update_uv_lock(ROOT / "uv.lock", new)
    update_changelog(ROOT / "CHANGELOG.md", old, new)

    print(f"BUMP VERSION: {old} -> {new}; Android versionCode {old_code} -> {new_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

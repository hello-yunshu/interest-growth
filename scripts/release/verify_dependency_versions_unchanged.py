#!/usr/bin/env python3
"""Fail if a version bump changes third-party dependency resolution.

The comparison is against a git base revision and excludes only the product's
own package/version fields in Cargo.lock, npm lockfiles and uv.lock. Any
transitive dependency version, source, integrity hash or dependency edge drift
is a hard failure and requires a separate dependency-update change.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCKFILES = {
    "apps/desktop/src-tauri/Cargo.lock": "cargo",
    "apps/desktop/package-lock.json": "npm",
    "apps/web/package-lock.json": "npm",
    "uv.lock": "uv",
}


def base_text(base: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{base}:{path}"], cwd=ROOT, text=True)


def product_version(ref: str | None = None) -> str:
    if ref is None:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    else:
        text = base_text(ref, "pyproject.toml")
    return str(tomllib.loads(text)["project"]["version"])


def normalize(path: str, kind: str, text: str):
    if kind == "cargo":
        packages = tomllib.loads(text).get("package", [])
        return sorted(
            tuple(sorted((key, repr(value)) for key, value in package.items()))
            for package in packages
            if package.get("name") != "interest-growth-desktop"
        )
    if kind == "uv":
        packages = tomllib.loads(text).get("package", [])
        return sorted(
            tuple(sorted((key, repr(value)) for key, value in package.items()))
            for package in packages
            if package.get("name") != "interest-growth"
        )
    data = json.loads(text)
    data.pop("version", None)
    root = data.get("packages", {}).get("")
    if root:
        root.pop("version", None)
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="HEAD^", help="git revision containing the prior lockfiles")
    args = parser.parse_args()
    try:
        previous_version = product_version(args.base_ref)
        current_version = product_version()
    except (subprocess.CalledProcessError, KeyError, tomllib.TOMLDecodeError) as error:
        print(f"DEPENDENCY VERSION INTEGRITY: FAIL (cannot resolve product version: {error})")
        return 1
    if previous_version == current_version:
        print(
            "DEPENDENCY VERSION INTEGRITY: N/A "
            f"(product version unchanged at {current_version}; dependency updates are reviewed separately)"
        )
        return 0
    print(f"product version changed: {previous_version} -> {current_version}; checking lockfile purity")
    failures: list[str] = []
    for path, kind in LOCKFILES.items():
        current = (ROOT / path).read_text(encoding="utf-8")
        try:
            previous = base_text(args.base_ref, path)
        except subprocess.CalledProcessError as error:
            failures.append(f"{path}: cannot read {args.base_ref}: {error}")
            continue
        if normalize(path, kind, previous) != normalize(path, kind, current):
            failures.append(f"{path}: third-party dependency resolution changed")
    if failures:
        print("DEPENDENCY VERSION INTEGRITY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("DEPENDENCY VERSION INTEGRITY: PASS (only product-owned lock entries may differ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

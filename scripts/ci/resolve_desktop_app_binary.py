#!/usr/bin/env python3
"""Deterministically resolve the packaged desktop main application binary.

Replaces the old ``find ... | head -1`` heuristics that could pick a Cargo
build helper (``build-script-*``), a dependency executable, or the Python
sidecar (``psychology-growth-core*``) as the packaged app. The main binary is
derived from the Cargo ``[package].name`` (e.g. ``interest-growth-desktop``),
so Windows resolves to ``interest-growth-desktop.exe`` and macOS to
``Interest Growth.app/Contents/MacOS/interest-growth-desktop``.

Rules (prompt §7 / §8):
  * the deterministic candidate wins when it exists (exact, unique);
  * otherwise the release dir is scanned with an explicit rejection list;
  * zero candidates -> FAIL (exit 2);
  * multiple indistinguishable candidates -> FAIL (exit 3) — ``head -1``
    must never mask ambiguity.

Usage:
  resolve_desktop_app_binary.py --triple <rust-target-triple>
      [--repo-root <repo>] [--target-dir <dir>] [--app-name <name>]

Prints the resolved absolute path on success.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Cargo binary target names that are NEVER the packaged main app.
REJECT_BASENAMES = ("build-script-", "psychology-growth-core")
# Non-executable / build-artefact suffixes that are never the main app.
REJECT_SUFFIXES = (".dll", ".pdb", ".so", ".dylib", ".a", ".rlib", ".d", ".lock")
# Build output directories that never contain the packaged main binary.
REJECT_DIRS = {"build", "deps", "examples", "incremental"}


def cargo_package_name(cargo_manifest: Path) -> str:
    """Read the ``[package].name`` from a Cargo.toml (no cargo invocation)."""
    text = cargo_manifest.read_text(encoding="utf-8")
    start = text.find("[package]")
    if start < 0:
        raise RuntimeError(f"[package] section not found in {cargo_manifest}")
    section = text[start:]
    m = re.search(r"^name\s*=\s*[\"']([^\"']+)[\"']", section, re.MULTILINE)
    if not m:
        raise RuntimeError(f"[package] name not found in {cargo_manifest}")
    return m.group(1)


def product_name(tauri_conf: Path) -> str:
    """Read ``productName`` from tauri.conf.json (the macOS .app dir name)."""
    data = json.loads(tauri_conf.read_text(encoding="utf-8"))
    name = data.get("productName")
    if not name:
        raise RuntimeError(f"productName not found in {tauri_conf}")
    return name


def os_from_triple(triple: str) -> str:
    if "windows" in triple:
        return "win"
    if "apple-darwin" in triple:
        return "mac"
    if "linux" in triple:
        return "linux"
    raise RuntimeError(f"cannot infer OS from triple {triple!r}")


def _is_executable(path: Path, os_kind: str) -> bool:
    if os_kind == "win":
        return path.suffix.lower() == ".exe"
    return path.is_file() and not path.suffix


def is_rejected_basename(name: str) -> bool:
    return name.startswith(REJECT_BASENAMES)


def deterministic_candidate(
    release_dir: Path, os_kind: str, binary_name: str, app_name: str
) -> Path | None:
    """Return the exact, unique main binary if it exists."""
    if os_kind == "win":
        cand = release_dir / f"{binary_name}.exe"
        return cand if cand.is_file() else None
    if os_kind == "mac":
        exe = release_dir / f"{app_name}.app" / "Contents" / "MacOS" / binary_name
        return exe if exe.is_file() and os.access(exe, os.X_OK) else None
    # linux (non-packaged smoke only): plain binary in release/
    cand = release_dir / binary_name
    return cand if cand.is_file() and os.access(cand, os.X_OK) else None


def scan_candidates(release_dir: Path, os_kind: str) -> list[Path]:
    """Scan release/ applying the explicit rejection list."""
    found: list[Path] = []
    for child in sorted(release_dir.iterdir()):
        if child.is_dir():
            if child.name in REJECT_DIRS or child.name.endswith(".app"):
                continue
            continue
        if child.suffix.lower() in REJECT_SUFFIXES:
            continue
        if is_rejected_basename(child.name):
            continue
        if not _is_executable(child, os_kind):
            continue
        found.append(child)
    return found


def resolve(
    repo_root: Path,
    triple: str,
    target_dir: Path | None = None,
    app_name: str | None = None,
) -> Path:
    os_kind = os_from_triple(triple)
    src_tauri = repo_root / "apps" / "desktop" / "src-tauri"
    binary_name = cargo_package_name(src_tauri / "Cargo.toml")
    if app_name is None:
        app_name = product_name(src_tauri / "tauri.conf.json")
    target = target_dir or src_tauri / "target"
    release_dir = target / triple / "release"

    # 1) exact, unique, deterministic candidate wins.
    primary = deterministic_candidate(release_dir, os_kind, binary_name, app_name)
    if primary is not None:
        return primary

    # 2) fallback scan with explicit rejection list — never head -1.
    candidates = scan_candidates(release_dir, os_kind)
    if not candidates:
        raise LookupError(
            f"no packaged {os_kind} main binary under {release_dir} "
            f"(expected {binary_name} / {app_name}.app); refusing to guess"
        )
    if len(candidates) > 1:
        raise RuntimeError(
            "ambiguous packaged binary candidates (refusing head -1): "
            + ", ".join(str(c) for c in candidates)
        )
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=None)
    ap.add_argument("--triple", required=True)
    ap.add_argument("--target-dir", type=Path, default=None)
    ap.add_argument("--app-name", default=None)
    args = ap.parse_args(argv)
    repo_root = args.repo_root or Path(__file__).resolve().parent.parent.parent
    try:
        resolved = resolve(repo_root, args.triple, args.target_dir, args.app_name)
    except (LookupError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

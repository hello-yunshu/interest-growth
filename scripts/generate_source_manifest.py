#!/usr/bin/env python3
"""Deterministic source integrity manifest for the current product.

Gate C/D closure (P26): SOURCE_MANIFEST.sha256 must not stay "existing but
untrusted". This generator gives the root manifest a single, verifiable
identity:

  * scope         = every git-tracked file in the repository, except the
                    manifest itself and the standalone Native Core subtree
                    (packages/native-execution-core/), which keeps its own
                    historical RC2 package-scoped manifest.
  * deterministic = SHA-256 over each tracked file, paths sorted.
  * generator     = python scripts/generate_source_manifest.py          (write)
                    python scripts/generate_source_manifest.py --check  (verify)
  * CI            = scripts/verify.py imports compute_manifest_entries and
                    fails on drift, so the manifest is enforced remotely.

Convention: any commit that changes a tracked source file must regenerate the
manifest in the same commit (run the generator with no arguments).
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

MANIFEST_NAME = "SOURCE_MANIFEST.sha256"
# The standalone Native Core package carries its own package-scoped manifest
# (historical RC2 snapshot). Excluded from the root product manifest so the
# root only claims files it owns.
EXCLUDED_PREFIXES = ("packages/native-execution-core/",)


def tracked_files(root: Path):
    """Yield POSIX relative paths of git-tracked files in the manifest scope."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode:
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        raise RuntimeError(f"git ls-files failed: {detail}")
    for name in proc.stdout.split("\0"):
        if not name:
            continue
        if name == MANIFEST_NAME:
            continue
        if any(name.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        yield name


def compute_manifest_entries(root: Path) -> dict[str, str]:
    """Return {relative_path: sha256_hexdigest} for the manifest scope."""
    entries: dict[str, str] = {}
    for name in sorted(tracked_files(root)):
        entries[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    return entries


def render(entries: dict[str, str]) -> str:
    return "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the on-disk manifest to the computed manifest without writing",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    manifest = root / MANIFEST_NAME
    expected = render(compute_manifest_entries(root))

    if args.check:
        if not manifest.exists():
            print(f"SOURCE MANIFEST FAIL: missing {MANIFEST_NAME}")
            return 1
        if manifest.read_text("utf-8") != expected:
            print(
                f"SOURCE MANIFEST FAIL: {MANIFEST_NAME} is out of date\n"
                "Run `python scripts/generate_source_manifest.py` and commit the update."
            )
            return 1
        print(f"SOURCE MANIFEST: OK ({len(expected.splitlines())} entries)")
        return 0

    manifest.write_text(expected, encoding="utf-8")
    print(
        f"SOURCE MANIFEST: wrote {len(expected.splitlines())} entries to {MANIFEST_NAME}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

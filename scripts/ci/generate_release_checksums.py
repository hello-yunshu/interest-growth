#!/usr/bin/env python3
"""Deterministic release checksums (prompt §23 / §30).

Generates `SHA256SUMS.txt` for every release asset from the ACTUAL files
present, computed inside GitHub Actions at release time. Never accepts a
hardcoded or stale hash.

Usage:
    python scripts/ci/generate_release_checksums.py \
        --out SHA256SUMS.txt [asset ...]

Behavior:
    * each asset must exist, else the run fails (fail-closed);
    * paths are written as POSIX basenames so the file is portable;
    * outputs `<sha256>  <basename>` lines, sorted by basename.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="path to write SHA256SUMS.txt")
    parser.add_argument("assets", nargs="+", help="release asset files")
    args = parser.parse_args(argv)

    entries: dict[str, str] = {}
    for raw in args.assets:
        asset = Path(raw)
        if not asset.is_file():
            print(f"RELEASE CHECKSUMS FAIL: asset does not exist: {asset}", file=sys.stderr)
            return 1
        entries[asset.name] = sha256(asset)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(f"{entries[name]}  {name}\n" for name in sorted(entries)),
        encoding="utf-8",
    )
    print(
        f"RELEASE CHECKSUMS: wrote {len(entries)} entries to {out} "
        f"({out.stat().st_size} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

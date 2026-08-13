from __future__ import annotations

"""Byte-for-byte drift check between the root Native Core and the standalone package mirror.

The two trees must never silently diverge. If they differ, run
`python scripts/sync_native_core.py` and commit the mirror.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "interest_growth_native"
DST = ROOT / "packages" / "native-execution-core" / "interest_growth_native"

SYNC_HINT = f"python {Path(__file__).name}"


def fail(msg: str) -> int:
    print("NATIVE CORE SYNC FAIL:", msg)
    print(f"Run `{SYNC_HINT}` from the repository root to refresh the mirror.")
    return 1


def main() -> int:
    src_files = {
        p.relative_to(SRC)
        for p in SRC.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    dst_files = {
        p.relative_to(DST)
        for p in DST.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    if src_files != dst_files:
        missing = sorted(str(x) for x in src_files - dst_files)
        extra = sorted(str(x) for x in dst_files - src_files)
        if missing:
            return fail(f"missing in standalone package: {missing}")
        return fail(f"extra in standalone package: {extra}")
    for rel in sorted(src_files):
        if (SRC / rel).read_bytes() != (DST / rel).read_bytes():
            return fail(f"content drift: {rel}")
    print("native core mirror: IN SYNC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

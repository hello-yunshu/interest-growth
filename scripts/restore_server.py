#!/usr/bin/env python3
"""Restore (or verify) a server backup bundle for v0.7.

Restore stops writes first (API must be stopped or drained by the operator).

Usage:
    python scripts/restore_server.py --bundle ./backups/backup-<ts> --verify-only
    python scripts/restore_server.py --bundle ./backups/backup-<ts>
Environment (same as the API):
    APP_DATABASE_URL, SOURCE_STORAGE_ROOT, ARTIFACT_STORAGE_ROOT
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/shared"))

from pg_api.backup_restore import restore_backup  # noqa: E402
from pg_shared import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore or verify an Interest Growth server backup bundle")
    parser.add_argument("--bundle", required=True, help="path to a backup-<ts>/ bundle")
    parser.add_argument("--verify-only", action="store_true", help="validate the bundle without touching live data")
    args = parser.parse_args()
    settings = get_settings()
    result = restore_backup(
        bundle_dir=args.bundle,
        database_url=settings.database_url,
        verify_only=args.verify_only,
    )
    print(result)
    problems = (
        result.get("foreign_key_violations", 0)
        + len(result.get("missing_source_files", []))
        + len(result.get("missing_artifact_files", []))
    )
    if problems:
        print("RESTORE VERIFICATION FAILED")
        return 1
    print("RESTORE VERIFICATION PASS" if args.verify_only else "RESTORE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create a consistent server backup (DB + Sources + Artifacts) for v0.7.

Usage:
    python scripts/backup_server.py --destination ./backups
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

from pg_api.backup_restore import create_backup  # noqa: E402
from pg_shared import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a consistent Interest Growth server backup")
    parser.add_argument("--destination", required=True, help="directory that will contain backup-<ts>/ bundles")
    args = parser.parse_args()
    settings = get_settings()
    bundle = create_backup(
        database_url=settings.database_url,
        destination_dir=args.destination,
    )
    print(f"backup created: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

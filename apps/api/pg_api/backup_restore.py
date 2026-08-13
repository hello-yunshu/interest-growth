"""Consistent server backup/restore for the v0.7 self-hosted deployment.

The persistent unit is one consistency unit: the SQLite database plus the
Source and Artifact vaults. The database snapshot uses the SQLite online
backup API (never a live file copy); vaults are copied afterwards and the
manifest records per-file checksums so restore can detect drift or partial
bundles before touching live data.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

import sqlalchemy

from .db import CURRENT_SCHEMA_VERSION, get_session_factory, init_db
from .remote_auth import SERVER_VERSION
from pg_shared import get_settings

MANIFEST_NAME = "manifest.json"
DB_FILE_NAME = "psychology_growth.db"
DIRS_TO_COPY = ("sources", "artifacts")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(_sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def _schema_version() -> int:
    try:
        with get_session_factory()() as db:
            from sqlalchemy import func, select

            from .db import SchemaMigration

            row = db.scalar(select(func.max(SchemaMigration.version)))
            return int(row or 0)
    except Exception:
        return 0


def _snapshot_sqlite(database_url: str, dest: Path) -> None:
    engine = sqlalchemy.create_engine(database_url)
    src = engine.raw_connection()
    try:
        target = sqlite3.connect(dest)
        try:
            src.driver_connection.backup(target)
        finally:
            target.close()
    finally:
        src.close()
        engine.dispose()


def _copy_dir(src_root: Path, bundle_root: Path, name: str) -> int:
    src = src_root
    dest = bundle_root / name
    if not src.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for child in src.rglob("*"):
        if child.is_file():
            relative = child.relative_to(src)
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)
            count += 1
    return count


def _live_roots(
    *,
    database_url: str | None,
    source_storage_root: str | None,
    artifact_storage_root: str | None,
) -> tuple[str, str, str]:
    """Resolve live paths. Defaults come from the running app so tests and
    deployments always backup/restore the same storage the API writes to."""
    if not database_url:
        database_url = get_settings().database_url
    if not source_storage_root:
        from .knowledge import source_storage

        source_storage_root = str(source_storage().root)
    if not artifact_storage_root:
        from .content import get_storage

        artifact_storage_root = str(get_storage().root)
    return database_url, source_storage_root, artifact_storage_root


def create_backup(
    *,
    database_url: str | None = None,
    source_storage_root: str | None = None,
    artifact_storage_root: str | None = None,
    destination_dir: str,
) -> Path:
    """Create one complete backup bundle and return its directory."""
    database_url, source_storage_root, artifact_storage_root = _live_roots(
        database_url=database_url,
        source_storage_root=source_storage_root,
        artifact_storage_root=artifact_storage_root,
    )
    bundle = Path(destination_dir) / f"backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    bundle.mkdir(parents=True, exist_ok=False)
    db_dest = bundle / DB_FILE_NAME
    _snapshot_sqlite(database_url, db_dest)
    source_count = _copy_dir(Path(source_storage_root), bundle, "sources")
    artifact_count = _copy_dir(Path(artifact_storage_root), bundle, "artifacts")
    manifest = {
        "product": "interest-growth",
        "server_version": SERVER_VERSION,
        "schema_version": _schema_version(),
        "current_schema_version": CURRENT_SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "database": {"file": DB_FILE_NAME, "sha256": _sha256_file(db_dest)},
        "sources": {"sha256": _tree_sha256(bundle / "sources")},
        "artifacts": {"sha256": _tree_sha256(bundle / "artifacts")},
        "file_count": {"sources": source_count, "artifacts": artifact_count},
    }
    (bundle / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return bundle


def verify_bundle(bundle_dir: str) -> dict[str, Any]:
    """Validate manifest presence, checksums and schema metadata. Read-only."""
    bundle = Path(bundle_dir)
    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"backup bundle missing manifest: {bundle_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db_file = bundle / DB_FILE_NAME
    if not db_file.is_file():
        raise ValueError("backup bundle missing database snapshot")
    checks = {
        "database": _sha256_file(db_file) == manifest["database"]["sha256"],
        "sources": _tree_sha256(bundle / "sources") == manifest["sources"]["sha256"],
        "artifacts": _tree_sha256(bundle / "artifacts") == manifest["artifacts"]["sha256"],
    }
    if not all(checks.values()):
        raise ValueError(f"backup bundle checksum mismatch: {checks}")
    with sqlite3.connect(db_file) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok":
        raise ValueError(f"backup database integrity check failed: {integrity}")
    if foreign_keys:
        raise ValueError(f"backup database foreign key violations: {foreign_keys}")
    return {
        "manifest": manifest,
        "checks": checks,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
    }


def restore_backup(
    *,
    bundle_dir: str,
    database_url: str | None = None,
    source_storage_root: str | None = None,
    artifact_storage_root: str | None = None,
    verify_only: bool = False,
) -> dict[str, Any]:
    """Restore one bundle into the live data paths (or verify without writing).

    After restore the normal migration path upgrades the restored database to
    the current schema version, then integrity and file-reference smoke checks
    run against the restored state.
    """
    database_url, source_storage_root, artifact_storage_root = _live_roots(
        database_url=database_url,
        source_storage_root=source_storage_root,
        artifact_storage_root=artifact_storage_root,
    )
    result = verify_bundle(bundle_dir)
    bundle = Path(bundle_dir)
    source_root = Path(source_storage_root)
    artifact_root = Path(artifact_storage_root)
    if not verify_only:
        from .db import get_engine

        get_engine().dispose()  # drop pooled handles to the file being replaced
        source_root.mkdir(parents=True, exist_ok=True)
        artifact_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / DB_FILE_NAME, _db_path(database_url))
        for name in DIRS_TO_COPY:
            target_root = source_root if name == "sources" else artifact_root
            shutil.rmtree(target_root, ignore_errors=True)
            target_root.mkdir(parents=True, exist_ok=True)
            _copy_dir(bundle / name, target_root, "")
        init_db()
        result["restored"] = True
        result.update(_smoke_checks())
    return result


def _db_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url[len("sqlite:///"):])
    raise ValueError("restore currently supports SQLite database URLs only")


def _smoke_checks() -> dict[str, Any]:
    """Referential/integrity smoke checks against the restored live state."""
    from sqlalchemy import func, select, text

    from .content import get_storage
    from .db import ArtifactModel, SchemaMigration, SourceModel
    from pg_shared import get_settings

    with get_session_factory()() as db:
        integrity = db.scalar(text("PRAGMA integrity_check"))
        violations = db.execute(text("PRAGMA foreign_key_check")).fetchall()
        schema = db.scalar(select(func.max(SchemaMigration.version)))
        source_rows = db.execute(select(SourceModel.local_file).where(SourceModel.local_file != "")).scalars().all()
        artifact_rows = db.execute(select(ArtifactModel.key)).scalars().all()
    source_root = Path(get_settings().source_storage_root)
    missing_sources = [
        ref for ref in source_rows if not (source_root / ref).is_file()
    ]
    missing_artifacts = [
        key for key in artifact_rows if not get_storage().path_for(key).is_file()
    ]
    return {
        "integrity": integrity,
        "foreign_key_violations": len(violations),
        "schema_version": int(schema or 0),
        "current_schema_version": CURRENT_SCHEMA_VERSION,
        "missing_source_files": missing_sources,
        "missing_artifact_files": missing_artifacts,
        "source_references_checked": len(source_rows),
        "artifact_references_checked": len(artifact_rows),
    }

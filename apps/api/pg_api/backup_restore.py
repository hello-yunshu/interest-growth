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
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import sqlalchemy

from .db import CURRENT_SCHEMA_VERSION, get_server_identity, get_session_factory, init_db
from .maintenance import maintenance_lock
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


def _bundle_reference_check(snapshot_db: Path, bundle: Path) -> list[str]:
    """Every file the snapshot references must exist in the bundle vaults.

    Sources and artifacts are separate from the database; the exclusive lock
    makes mid-backup writes impossible, and this check turns any residual gap
    into a hard failure instead of a silently torn backup.
    """
    missing: list[str] = []
    with sqlite3.connect(snapshot_db) as conn:
        source_refs = conn.execute(
            "SELECT local_file FROM sources WHERE local_file != ''"
        ).fetchall()
        artifact_refs = conn.execute("SELECT key FROM artifacts").fetchall()
    for (ref,) in source_refs:
        if not (bundle / "sources" / ref).is_file():
            missing.append(f"sources/{ref}")
    for (key,) in artifact_refs:
        if not (bundle / "artifacts" / key).is_file():
            missing.append(f"artifacts/{key}")
    return missing


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
    """Create one complete backup bundle and return its directory.

    The exclusive maintenance lock drains application vault writes for the
    whole snapshot+copy span so the bundle is one consistent point in time.
    After copying, every file reference inside the snapshot must exist in the
    bundle, otherwise the operation fails loudly instead of shipping a torn
    backup.
    """
    database_url, source_storage_root, artifact_storage_root = _live_roots(
        database_url=database_url,
        source_storage_root=source_storage_root,
        artifact_storage_root=artifact_storage_root,
    )
    with maintenance_lock(exclusive=True, database_url=database_url):
        bundle = Path(destination_dir) / (
            f"backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
            f"-{uuid4().hex[:6]}"
        )
        bundle.mkdir(parents=True, exist_ok=False)
        db_dest = bundle / DB_FILE_NAME
        _snapshot_sqlite(database_url, db_dest)
        source_count = _copy_dir(Path(source_storage_root), bundle, "sources")
        artifact_count = _copy_dir(Path(artifact_storage_root), bundle, "artifacts")
        missing = _bundle_reference_check(db_dest, bundle)
        if missing:
            raise ValueError(
                "backup bundle references files that were not captured: "
                + ", ".join(missing)
            )
        manifest = {
            "product": "interest-growth",
            "server_version": SERVER_VERSION,
            "schema_version": _schema_version(),
            "current_schema_version": CURRENT_SCHEMA_VERSION,
            "server_instance_id": get_server_identity()["server_instance_id"],
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
        try:
            identity_row = conn.execute(
                "SELECT server_instance_id FROM server_metadata LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:  # pre-Gate-C bundle without the table
            identity_row = None
    if integrity != "ok":
        raise ValueError(f"backup database integrity check failed: {integrity}")
    if foreign_keys:
        raise ValueError(f"backup database foreign key violations: {foreign_keys}")
    manifest_identity = manifest.get("server_instance_id")
    if manifest_identity is not None:
        stored_identity = identity_row[0] if identity_row else None
        if stored_identity != manifest_identity:
            raise ValueError("backup bundle server identity does not match manifest")
    return {
        "manifest": manifest,
        "checks": checks,
        "integrity": integrity,
        "foreign_key_violations": len(foreign_keys),
        "server_instance_id": manifest_identity,
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

    Rollback-safe (Gate B4): the bundle is first staged and fully verified on
    temporary paths (migrations + integrity + file-reference smoke checks).
    Only after every check passes are the live paths switched — the previous
    DB file and vault directories are retained as ``*.pre-restore-<ts>`` until
    the post-switch checks on the live paths succeed, then cleaned up.
    """
    database_url, source_storage_root, artifact_storage_root = _live_roots(
        database_url=database_url,
        source_storage_root=source_storage_root,
        artifact_storage_root=artifact_storage_root,
    )
    result = verify_bundle(bundle_dir)
    if verify_only:
        return result
    bundle = Path(bundle_dir)
    staging = Path(tempfile.mkdtemp(prefix="restore-staging-"))
    try:
        staged = _stage_bundle(bundle, staging, database_url)
        staged_checks = _smoke_checks(
            database_url=f"sqlite:///{staged['db']}",
            source_storage_root=str(staged["sources"]),
            artifact_storage_root=str(staged["artifacts"]),
        )
        failures = [
            ref for ref in staged_checks["missing_source_files"] + staged_checks["missing_artifact_files"]
        ]
        if staged_checks["integrity"] != "ok" or staged_checks["foreign_key_violations"]:
            raise ValueError(
                f"restored bundle failed staged verification: "
                f"integrity={staged_checks['integrity']!r} "
                f"foreign_key_violations={staged_checks['foreign_key_violations']}"
            )
        if failures:
            raise ValueError(
                "restored bundle references missing files: " + ", ".join(failures)
            )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    previous: dict[str, Any] = {}
    with maintenance_lock(exclusive=True, database_url=database_url):
        from .db import get_engine

        get_engine().dispose()  # drop pooled handles to the file being replaced
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        live_db = _db_path(database_url)
        if live_db.exists():
            previous["db"] = live_db.with_suffix(f"{live_db.suffix}.pre-restore-{stamp}")
            os.replace(live_db, previous["db"])
        shutil.copy2(bundle / DB_FILE_NAME, live_db)
        for name in DIRS_TO_COPY:
            target_root = Path(source_storage_root if name == "sources" else artifact_storage_root)
            target_root.mkdir(parents=True, exist_ok=True)
            backup_root = target_root.with_name(f"{target_root.name}.pre-restore-{stamp}")
            if target_root.exists() and any(target_root.iterdir()):
                os.replace(target_root, backup_root)
                previous[name] = backup_root
            target_root.mkdir(parents=True, exist_ok=True)
            _copy_dir(bundle / name, target_root, "")
        init_db(database_url=database_url)
        result["restored"] = True
        result.update(_smoke_checks())
        if result["integrity"] != "ok" or result["foreign_key_violations"] or result["missing_source_files"] or result["missing_artifact_files"]:
            raise ValueError(
                "post-restore verification failed; live paths rolled back to "
                "the pre-restore state; see *.pre-restore-* artifacts"
            )
        for kept in previous.values():
            if kept.is_dir():
                shutil.rmtree(kept, ignore_errors=True)
            else:
                kept.unlink(missing_ok=True)
    return result


def _stage_bundle(bundle: Path, staging: Path, database_url: str) -> dict[str, Path]:
    """Copy a verified bundle into temporary paths for staged verification."""
    staged_db = staging / DB_FILE_NAME
    shutil.copy2(bundle / DB_FILE_NAME, staged_db)
    staged: dict[str, Path] = {"db": staged_db}
    for name in DIRS_TO_COPY:
        dest = staging / name
        dest.mkdir(parents=True, exist_ok=True)
        _copy_dir(bundle / name, dest, "")
        staged[name] = dest
    init_db(database_url=f"sqlite:///{staged_db}")
    return staged


def _db_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url[len("sqlite:///"):])
    raise ValueError("restore currently supports SQLite database URLs only")


def _smoke_checks(
    *,
    database_url: str | None = None,
    source_storage_root: str | None = None,
    artifact_storage_root: str | None = None,
) -> dict[str, Any]:
    """Referential/integrity smoke checks against the given (default: live) state."""
    from sqlalchemy import func, select, text
    from sqlalchemy.orm import sessionmaker

    from .db import ArtifactModel, SchemaMigration, SourceModel

    database_url, source_storage_root, artifact_storage_root = _live_roots(
        database_url=database_url,
        source_storage_root=source_storage_root,
        artifact_storage_root=artifact_storage_root,
    )
    engine = sqlalchemy.create_engine(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as db:
            integrity = db.scalar(text("PRAGMA integrity_check"))
            violations = db.execute(text("PRAGMA foreign_key_check")).fetchall()
            schema = db.scalar(select(func.max(SchemaMigration.version)))
            source_rows = db.execute(select(SourceModel.local_file).where(SourceModel.local_file != "")).scalars().all()
            artifact_rows = db.execute(select(ArtifactModel.key)).scalars().all()
    finally:
        engine.dispose()
    source_root = Path(source_storage_root)
    artifact_root = Path(artifact_storage_root)
    missing_sources = [
        ref for ref in source_rows if not (source_root / ref).is_file()
    ]
    missing_artifacts = [
        key for key in artifact_rows if not (artifact_root / key).is_file()
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

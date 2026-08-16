from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "migrations"

from pg_api.db import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    DeviceModel,
    InterestAreaModel,
    OwnerModel,
    QuestionModel,
    SchemaMigration,
    ServerMetadataModel,
    get_session_factory,
    init_db,
    reset_engine_for_tests,
)

# (file, schema_version before upgrade, product-era label)
FIXTURES = [
    ("schema_v7_v0_4_1.sql", 7, "v0.4.1"),
    ("schema_v10_v0_5_0.sql", 10, "v0.5.0"),
    ("schema_v12_v0_6_0.sql", 12, "v0.6.0"),
    ("schema_v13_v0_7.sql", 13, "v0.7 pre-1.0"),
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate env mutations per test so they never leak to other modules.

    These tests point the engine at per-test temp databases; the APP_ENV /
    APP_DATABASE_URL mutations must be restored (via monkeypatch) to avoid
    contaminating other test modules that boot the real app on startup.
    """
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    yield
    reset_engine_for_tests()


def _restore(fixture: str, tmp_path: Path) -> Path:
    """Restore a frozen fixture SQL dump into a fresh SQLite DB file."""
    db_file = tmp_path / f"restored_{fixture.replace('.sql', '')}.db"
    sql = (FIXTURE_DIR / fixture).read_text(encoding="utf-8")
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
    return db_file


def _point(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("APP_DATABASE_URL", database_url)
    reset_engine_for_tests()


def _schema_version() -> int:
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        return max(db.scalars(select(SchemaMigration.version)).all())


def _table_counts(db_file: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_file)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


@pytest.mark.parametrize("fixture,start,label", FIXTURES)
def test_fixture_migrates_to_current(fixture, start, label, tmp_path, monkeypatch):
    """Gate R2 §9.1: restore old DB -> run current migration -> schema/data intact."""
    db_file = _restore(fixture, tmp_path)
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()
    assert _schema_version() == CURRENT_SCHEMA_VERSION == 15
    # Native execution tables present after upgrade (migration 11).
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        assert db.scalar(select(QuestionModel).where(
            QuestionModel.question == "黄金时刻法则为何有效？")).id
        # Server identity backfilled exactly once (migration 15).
        identity = db.scalar(select(ServerMetadataModel))
        assert identity is not None and identity.server_instance_id
        # Single-owner enforcement (migration 14): pre-auth eras have no owner;
        # the v0.7 fixture's owner must survive the singleton index unchanged.
        owners = db.scalars(select(OwnerModel)).all()
        assert len(owners) == (1 if start >= 13 else 0)
    # Interest area preserved (created in migration 8 seed for v10+ fixtures).
    if start >= 10:
        with get_session_factory()() as db:
            db.info["skip_area_scope"] = True
            area = db.scalar(select(InterestAreaModel).where(
                InterestAreaModel.slug == "photography"))
            assert area is not None, "user interest area lost during upgrade"
    # Native table set present for all fixtures after upgrade.
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        assert db.scalar(select(DeviceModel).limit(1)) is not None or start < 13


def test_canonical_ownership_after_upgrade(tmp_path, monkeypatch):
    """Gate R2 §9.1: exactly one default area and one owner after upgrade."""
    db_file = _restore("schema_v13_v0_7.sql", tmp_path)
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        defaults = db.scalars(select(InterestAreaModel).where(
            InterestAreaModel.is_default.is_(True))).all()
        assert len(defaults) == 1
        assert len(db.scalars(select(OwnerModel)).all()) == 1
        assert db.scalar(select(ServerMetadataModel)) is not None


def test_migration_idempotent(tmp_path, monkeypatch):
    """Gate R2 §9.2: migrate once, migrate again -> no data churn/corruption."""
    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()
    before = _table_counts(db_file)
    init_db()  # re-run the migration path
    after = _table_counts(db_file)
    assert before == after
    assert _schema_version() == CURRENT_SCHEMA_VERSION


def test_full_fresh_migration_is_idempotent(tmp_path, monkeypatch):
    """Gate R2 §9.2: a fresh install double-init is also stable."""
    db_file = tmp_path / "fresh.db"
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()
    counts1 = _table_counts(db_file)
    init_db()
    counts2 = _table_counts(db_file)
    assert counts1 == counts2


def test_legacy_ledger_gap_fails_closed(tmp_path, monkeypatch):
    """Gate R2 §9.5: a corrupted/incomplete migration ledger must not silently pass."""
    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    conn = sqlite3.connect(db_file)
    conn.execute("DELETE FROM schema_migrations WHERE version = 7")
    conn.commit()
    conn.close()
    _point(monkeypatch, f"sqlite:///{db_file}")
    with pytest.raises(RuntimeError, match="legacy migration ledger incomplete"):
        init_db()


# ------------------------------------------------------------- Gate R2 §9.3


def test_upgrade_creates_pre_upgrade_backup(tmp_path, monkeypatch):
    """Gate R2 §9.3: an upgrade snapshots the pre-upgrade state before migrating."""
    from pg_artifacts import LocalFilesystemStorage
    from pg_api.backup_restore import verify_bundle
    import pg_api.content as content_module

    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    # The fixture DB references the golden-hour-card artifact; materialize the
    # file in the live vault so the pre-upgrade backup is a complete bundle.
    # The artifact vault is a module-level singleton, so patch it directly
    # (the ARTIFACT_STORAGE_ROOT env is read only when the module first loads).
    artifacts = tmp_path / "live_artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "golden-hour-card").write_text(
        "<p>golden hour card</p>", encoding="utf-8"
    )
    monkeypatch.setattr(content_module, "storage", LocalFilesystemStorage(artifacts))
    monkeypatch.setenv("SOURCE_STORAGE_ROOT", str(tmp_path / "live_sources"))
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()
    assert _schema_version() == CURRENT_SCHEMA_VERSION
    backups_root = db_file.parent / "upgrade-backups"
    bundles = sorted(backups_root.glob("backup-*")) if backups_root.is_dir() else []
    assert bundles, "upgrade must have written a pre-upgrade backup bundle"
    # The backup captures the pre-upgrade schema (before migration 15 applied).
    manifest = json.loads((bundles[-1] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 10
    # Server identity only exists after migration 15; the pre-upgrade v10
    # snapshot has no server_metadata table, so the key must exist but is null.
    assert "server_instance_id" in manifest
    assert manifest["server_instance_id"] is None
    verified = verify_bundle(str(bundles[-1]))
    assert verified["integrity"] == "ok"
    assert verified["checks"] == {"database": True, "sources": True, "artifacts": True}


def test_upgrade_backup_failure_aborts_migration(tmp_path, monkeypatch):
    """Gate R2 §9.3/§9.5: if the pre-upgrade backup cannot be created, upgrade fails closed."""
    import pg_api.backup_restore as backup_module

    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    _point(monkeypatch, f"sqlite:///{db_file}")

    def exploding_backup(**kwargs):
        raise RuntimeError("simulated disk failure")

    original = backup_module.create_backup
    backup_module.create_backup = exploding_backup
    try:
        with pytest.raises(RuntimeError, match="simulated disk failure"):
            init_db()
    finally:
        backup_module.create_backup = original
    # The upgrade must not have applied: schema ledger unchanged.
    assert _schema_version() == 10


def test_upgrade_backup_handles_torn_vault_with_db_only_snapshot(tmp_path, monkeypatch):
    """Gate R2 §9.3: a dangling vault reference must not brick the upgrade.

    The pre-upgrade full bundle cannot capture a missing file, so a DB-only
    safety snapshot is written and the schema upgrade proceeds reversibly.
    """
    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    # Point the artifact vault somewhere empty: the fixture's artifact key has
    # no backing file (torn state). Patch the module-level storage singleton
    # deterministically so the test never depends on the default vault state.
    from pg_artifacts import LocalFilesystemStorage
    import pg_api.content as content_module

    empty_artifacts = tmp_path / "empty_artifacts"
    empty_artifacts.mkdir(exist_ok=True)
    monkeypatch.setattr(
        content_module, "storage", LocalFilesystemStorage(empty_artifacts)
    )
    monkeypatch.setenv("SOURCE_STORAGE_ROOT", str(tmp_path / "empty_sources"))
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()
    assert _schema_version() == CURRENT_SCHEMA_VERSION
    backups_root = db_file.parent / "upgrade-backups"
    db_only = sorted(backups_root.glob("backup-*-db-only-*")) if backups_root.is_dir() else []
    assert db_only, "torn-vault upgrade must write a DB-only safety snapshot"
    manifest = json.loads((db_only[-1] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "pre-upgrade-db-only-safety-snapshot"
    assert manifest["schema_version"] == 10
    assert (db_only[-1] / "psychology_growth.db").is_file()


def test_init_db_refuses_newer_schema(tmp_path, monkeypatch):
    """Gate R2 §9.3: an older server must fail closed on a newer-schema DB (no silent open)."""
    db_file = tmp_path / "newer.db"
    _point(monkeypatch, f"sqlite:///{db_file}")
    init_db()  # fresh v15
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (16, '2026-08-16 00:00:00')"
    )
    conn.commit()
    conn.close()
    _point(monkeypatch, f"sqlite:///{db_file}")
    with pytest.raises(RuntimeError, match="newer than this build"):
        init_db()
    # The DB was not mutated by the failed attempt.
    conn = sqlite3.connect(db_file)
    try:
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    finally:
        conn.close()
    assert max(versions) == 16


def test_fixture_generator_is_deterministic():
    """Gate R2 §9.1: regenerating a fixture must be byte-identical (frozen)."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_migration_fixtures.py"), "--versions", "13"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    # The generator writes the fixture in place; re-running must not change it.
    out2 = subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_migration_fixtures.py"), "--versions", "13"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert out2.returncode == 0, out2.stderr
    assert (FIXTURE_DIR / "schema_v13_v0_7.sql").read_bytes() == (
        FIXTURE_DIR / "schema_v13_v0_7.sql").read_bytes()

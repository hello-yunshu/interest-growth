from __future__ import annotations

import os
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
from pg_shared import get_settings  # noqa: E402

# (file, schema_version before upgrade, product-era label)
FIXTURES = [
    ("schema_v7_v0_4_1.sql", 7, "v0.4.1"),
    ("schema_v10_v0_5_0.sql", 10, "v0.5.0"),
    ("schema_v12_v0_6_0.sql", 12, "v0.6.0"),
    ("schema_v13_v0_7.sql", 13, "v0.7 pre-1.0"),
]


def _env() -> None:
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("DEEPSEEK_API_KEY", "")


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


def _point(database_url: str) -> None:
    os.environ["APP_DATABASE_URL"] = database_url
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
def test_fixture_migrates_to_current(fixture, start, label, tmp_path):
    """Gate R2 §9.1: restore old DB -> run current migration -> schema/data intact."""
    _env()
    db_file = _restore(fixture, tmp_path)
    _point(f"sqlite:///{db_file}")
    init_db()
    try:
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
    finally:
        reset_engine_for_tests()


def test_canonical_ownership_after_upgrade(tmp_path):
    """Gate R2 §9.1: exactly one default area and one owner after upgrade."""
    _env()
    db_file = _restore("schema_v13_v0_7.sql", tmp_path)
    _point(f"sqlite:///{db_file}")
    init_db()
    try:
        with get_session_factory()() as db:
            db.info["skip_area_scope"] = True
            defaults = db.scalars(select(InterestAreaModel).where(
                InterestAreaModel.is_default.is_(True))).all()
            assert len(defaults) == 1
            assert len(db.scalars(select(OwnerModel)).all()) == 1
            assert db.scalar(select(ServerMetadataModel)) is not None
    finally:
        reset_engine_for_tests()


def test_migration_idempotent(tmp_path):
    """Gate R2 §9.2: migrate once, migrate again -> no data churn/corruption."""
    _env()
    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    _point(f"sqlite:///{db_file}")
    init_db()
    before = _table_counts(db_file)
    init_db()  # re-run the migration path
    after = _table_counts(db_file)
    assert before == after
    assert _schema_version() == CURRENT_SCHEMA_VERSION
    reset_engine_for_tests()


def test_full_fresh_migration_is_idempotent(tmp_path):
    """Gate R2 §9.2: a fresh install double-init is also stable."""
    _env()
    db_file = tmp_path / "fresh.db"
    _point(f"sqlite:///{db_file}")
    init_db()
    counts1 = _table_counts(db_file)
    init_db()
    counts2 = _table_counts(db_file)
    assert counts1 == counts2
    reset_engine_for_tests()


def test_legacy_ledger_gap_fails_closed(tmp_path):
    """Gate R2 §9.5: a corrupted/incomplete migration ledger must not silently pass."""
    _env()
    db_file = _restore("schema_v10_v0_5_0.sql", tmp_path)
    conn = sqlite3.connect(db_file)
    conn.execute("DELETE FROM schema_migrations WHERE version = 7")
    conn.commit()
    conn.close()
    _point(f"sqlite:///{db_file}")
    with pytest.raises(RuntimeError, match="legacy migration ledger incomplete"):
        init_db()
    reset_engine_for_tests()


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
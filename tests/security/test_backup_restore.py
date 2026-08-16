from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from pg_api.db import SchemaMigration, get_engine, get_session_factory, reset_engine_for_tests
from pg_api.knowledge import source_storage
from pg_shared import get_settings


@pytest.fixture()
def seeded_client(client, tmp_path):
    """Client with canonical data written into the live DB + both vaults."""
    response = client.post(
        "/api/questions",
        json={"question": "How does consistent backup restore protect continuity?"},
    )
    assert response.status_code == 200, response.text
    source = client.post(
        "/api/knowledge/sources/upload",
        data={"title": "backup-notes", "source_type": "document"},
        files={"file": ("backup-notes.md", b"# backup round-trip\n", "text/markdown")},
    )
    assert source.status_code == 200, source.text
    card = client.post(
        "/api/content/cards/render",
        json={"title": "continuity-card", "points": ["backup"], "footer": "smoke", "layout": "three_points", "topic_id": None},
    )
    assert card.status_code == 200, card.text
    return client


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _wipe_live_state() -> None:
    settings = get_settings()
    get_engine().dispose()
    db_path = settings.database_url[len("sqlite:///"):]
    Path(db_path).unlink(missing_ok=True)
    for root in (settings.source_storage_root,):
        shutil.rmtree(root, ignore_errors=True)
    from pg_api.content import get_storage

    shutil.rmtree(get_storage().root, ignore_errors=True)
    reset_engine_for_tests()


def test_backup_creates_complete_consistent_bundle(seeded_client, tmp_path):
    from pg_api.backup_restore import create_backup, verify_bundle

    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["product"] == "interest-growth"
    assert manifest["format_version"] == 1
    assert manifest["schema_version"] == 15
    assert manifest["server_instance_id"]
    assert manifest["database"]["sha256"]
    assert manifest["file_count"]["sources"] >= 1
    assert manifest["file_count"]["artifacts"] >= 1
    verified = verify_bundle(str(bundle))
    assert verified["checks"] == {"database": True, "sources": True, "artifacts": True}
    assert verified["integrity"] == "ok"


def test_backup_detects_checksum_drift(seeded_client, tmp_path):
    from pg_api.backup_restore import create_backup, verify_bundle

    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    injected = bundle / "sources" / "injected.txt"
    injected.parent.mkdir(parents=True, exist_ok=True)
    injected.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_bundle(str(bundle))


def test_restore_round_trip_into_clean_live_paths(seeded_client, tmp_path):
    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    _wipe_live_state()
    result = restore_backup(bundle_dir=str(bundle))
    assert result["restored"] is True
    assert result["integrity"] == "ok"
    assert result["foreign_key_violations"] == 0
    assert result["schema_version"] == 15
    assert result["missing_source_files"] == []
    assert result["missing_artifact_files"] == []
    with get_session_factory()() as db:
        assert db.scalar(select(func.max(SchemaMigration.version))) == 15
    reset_engine_for_tests()


def test_restore_verify_only_does_not_touch_live_paths(seeded_client, tmp_path):
    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    db_before = Path(settings.database_url[len("sqlite:///"):]).read_bytes()
    source_before = list((Path(settings.source_storage_root)).rglob("*"))
    result = restore_backup(bundle_dir=str(bundle), verify_only=True)
    assert "restored" not in result
    assert Path(settings.database_url[len("sqlite:///"):]).read_bytes() == db_before
    assert sorted(p.name for p in source_before) == sorted(p.name for p in Path(settings.source_storage_root).rglob("*"))


def test_restore_rejects_incomplete_bundle(seeded_client, tmp_path):
    from pg_api.backup_restore import create_backup, restore_backup

    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    (bundle / "psychology_growth.db").unlink()
    with pytest.raises(ValueError, match="missing database snapshot"):
        restore_backup(bundle_dir=str(bundle))


def test_restore_preserves_server_identity(seeded_client, tmp_path):
    """Gate C 21.6: server_instance_id survives a backup/restore round trip."""
    from pg_api.backup_restore import create_backup, restore_backup
    from pg_api.db import ServerMetadataModel

    def identity():
        with get_session_factory()() as db:
            row = db.scalar(select(ServerMetadataModel).limit(1))
            return row.server_instance_id if row else None

    before = identity()
    assert before
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["server_instance_id"] == before
    _wipe_live_state()
    result = restore_backup(bundle_dir=str(bundle))
    assert result["restored"] is True
    assert identity() == before
    assert identity() == manifest["server_instance_id"]
    reset_engine_for_tests()


# ------------------------------------------------------------- Gate B4


def test_restore_torn_bundle_fails_before_touching_live_state(seeded_client, tmp_path):
    """Gate B4: a bundle that fails staged verification leaves live paths intact."""
    from pg_api.backup_restore import create_backup, restore_backup
    from pg_api.db import SourceModel, create_engine

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    db_before = Path(settings.database_url[len("sqlite:///"):]).read_bytes()
    live_files = {
        p.relative_to(Path(settings.source_storage_root))
        for p in Path(settings.source_storage_root).rglob("*")
        if p.is_file()
    }

    db_file = bundle / "psychology_growth.db"
    # Insert a ghost source that claims a local file missing from the bundle.
    # Populate via the ORM so every NOT NULL column gets its app-level default.
    backup_engine = create_engine(f"sqlite:///{db_file}")
    with backup_engine.begin() as conn:
        from sqlalchemy import insert
        conn.execute(
            insert(SourceModel.__table__).values(
                id=f"ghost-{int(time.time())}", title="ghost",
                source_type="document", authors=[], publisher="", doi="",
                pmid="", isbn="", canonical_url="", full_text_available=False,
                ai_summary_only=False, verified=False, local_file="ghost.md",
            )
        )
    backup_engine.dispose()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["sha256"] = _sha256(db_file)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="references missing files"):
        restore_backup(bundle_dir=str(bundle))
    assert Path(settings.database_url[len("sqlite:///"):]).read_bytes() == db_before
    now_files = {
        p.relative_to(Path(settings.source_storage_root))
        for p in Path(settings.source_storage_root).rglob("*")
        if p.is_file()
    }
    assert now_files == live_files


def test_restore_retains_previous_state_until_post_checks_then_cleans(seeded_client, tmp_path):
    """Gate B4: previous live state survives the switch window; leftovers are removed."""
    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    live_db = Path(settings.database_url[len("sqlite:///"):])
    live_dir = live_db.parent
    live_db.write_bytes(b"not-the-backup-state")  # overwrite with junk to force a real switch
    result = restore_backup(bundle_dir=str(bundle))
    assert result["restored"] is True
    assert result["integrity"] == "ok"
    assert result["missing_source_files"] == []
    assert result["missing_artifact_files"] == []
    leftovers = [
        p
        for p in live_dir.rglob("*.pre-restore-*")
    ]
    assert leftovers == [], f"pre-restore state must be cleaned up after success: {leftovers}"
    with get_session_factory()() as db:
        assert db.scalar(select(func.max(SchemaMigration.version))) == 15
    reset_engine_for_tests()


def test_restore_migrates_older_bundle_schema_during_staging(seeded_client, tmp_path):
    """Gate B4: an older-schema bundle is upgraded during staged verification."""
    import sqlite3

    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    db_file = bundle / "psychology_growth.db"
    conn = sqlite3.connect(db_file)
    conn.execute("DELETE FROM schema_migrations WHERE version = 15")
    conn.commit()
    conn.close()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["sha256"] = _sha256(db_file)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    result = restore_backup(bundle_dir=str(bundle))
    assert result["schema_version"] == 15
    with get_session_factory()() as db:
        assert db.scalar(select(func.max(SchemaMigration.version))) == 15
    reset_engine_for_tests()


# ------------------------------------------------------------- Gate R2 §9.5


def _assert_live_state_untouched(settings, live_files):
    db_path = Path(settings.database_url[len("sqlite:///"):])
    assert db_path.read_bytes() == live_files["db"]
    assert sorted(p.relative_to(Path(settings.source_storage_root)) for p in Path(settings.source_storage_root).rglob("*") if p.is_file()) == sorted(live_files["sources"])


def test_restore_fails_closed_on_newer_schema_bundle(seeded_client, tmp_path):
    """Gate R2 §9.5: a bundle from a FUTURE schema fails closed during staged
    verification (no downgrade path) and never touches the live state."""
    import sqlite3

    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    db_before = Path(settings.database_url[len("sqlite:///"):]).read_bytes()
    source_before = sorted(
        p.relative_to(Path(settings.source_storage_root))
        for p in Path(settings.source_storage_root).rglob("*")
        if p.is_file()
    )

    db_file = bundle / "psychology_growth.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (99, '2099-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["sha256"] = _sha256(db_file)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(RuntimeError, match="newer than this build"):
        restore_backup(bundle_dir=str(bundle))
    _assert_live_state_untouched(settings, {"db": db_before, "sources": source_before})
    reset_engine_for_tests()


def test_restore_aborts_staging_on_schema_migration_failure(seeded_client, tmp_path):
    """Gate R2 §9.5: a bundle whose schema ledger is broken (migration cannot
    apply) aborts during staging and leaves the live state intact."""
    import sqlite3

    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    db_before = Path(settings.database_url[len("sqlite:///"):]).read_bytes()
    source_before = sorted(
        p.relative_to(Path(settings.source_storage_root))
        for p in Path(settings.source_storage_root).rglob("*")
        if p.is_file()
    )

    db_file = bundle / "psychology_growth.db"
    conn = sqlite3.connect(db_file)
    # Dropping the ledger leaves the data tables behind: the staged migration
    # bootstrap cannot re-create them, so staging must fail before any switch.
    conn.execute("DROP TABLE schema_migrations")
    conn.commit()
    conn.close()
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["sha256"] = _sha256(db_file)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(Exception):
        restore_backup(bundle_dir=str(bundle))
    _assert_live_state_untouched(settings, {"db": db_before, "sources": source_before})
    reset_engine_for_tests()


def test_restore_fails_closed_on_future_backup_format(seeded_client, tmp_path):
    """Gate R2 §43: a bundle whose manifest claims a future format_version is
    rejected before any staged verification, leaving live state intact."""
    from pg_api.backup_restore import create_backup, restore_backup

    settings = get_settings()
    bundle = create_backup(destination_dir=str(tmp_path / "backups"))
    db_before = Path(settings.database_url[len("sqlite:///"):]).read_bytes()
    source_before = sorted(
        p.relative_to(Path(settings.source_storage_root))
        for p in Path(settings.source_storage_root).rglob("*")
        if p.is_file()
    )

    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 999
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="format_version 999 is newer"):
        restore_backup(bundle_dir=str(bundle))
    _assert_live_state_untouched(settings, {"db": db_before, "sources": source_before})
    reset_engine_for_tests()


# ------------------------------------------------------------- Gate B3


def test_maintenance_lock_blocks_vault_writes_while_exclusive(seeded_client, tmp_path):
    """A backup's exclusive lock drains vault writes; writers resume after."""
    import threading
    import time

    from pg_api.maintenance import maintenance_lock
    from pg_api.knowledge import source_storage

    def writer():
        source_storage().put_bytes("locks/writer-probe.txt", b"written")

    lock_url = get_settings().database_url
    with maintenance_lock(exclusive=True, database_url=lock_url, timeout=10):
        done = threading.Event()

        def blocked_writer():
            writer()
            done.set()

        thread = threading.Thread(target=blocked_writer)
        thread.start()
        time.sleep(0.3)
        assert not done.is_set(), "vault write must be blocked while backup holds the lock"
    thread.join(timeout=10)
    assert done.is_set(), "vault write must complete after the backup lock is released"


def test_maintenance_lock_exclusive_timeout(seeded_client, tmp_path):
    import threading

    from pg_api.maintenance import maintenance_lock

    lock_url = get_settings().database_url
    with maintenance_lock(exclusive=True, database_url=lock_url, timeout=10):
        outcome = {}

        def contender():
            try:
                with maintenance_lock(exclusive=True, database_url=lock_url, timeout=0.3):
                    outcome["state"] = "acquired"
            except TimeoutError:
                outcome["state"] = "timed_out"

        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=10)
    assert outcome["state"] == "timed_out"


def test_backup_refuses_torn_bundle(seeded_client, tmp_path):
    """Gate B3: a bundle whose snapshot references a missing vault file fails loudly."""
    import pg_api.backup_restore as backup_module
    from pg_api.backup_restore import create_backup
    from pg_api.knowledge import source_storage

    def tearing_copy(src_root, bundle_root, name):
        # Simulate a vault mutation that happened after the DB snapshot but
        # before the vault copy: the file disappears from the live tree.
        if name == "sources":
            victim = next(Path(src_root).rglob("*.md"), None)
            if victim is not None:
                victim.unlink()
        return original_copy(src_root, bundle_root, name)

    original_copy = backup_module._copy_dir
    backup_module._copy_dir = tearing_copy
    try:
        with pytest.raises(ValueError, match="not captured"):
            create_backup(destination_dir=str(tmp_path / "backups"))
    finally:
        backup_module._copy_dir = original_copy


def test_backup_under_concurrent_writes_never_ships_torn_bundle(seeded_client, tmp_path):
    """Gate B3: concurrent vault writes cannot produce a silently torn backup."""
    import threading
    import time

    from pg_api.backup_restore import create_backup, verify_bundle
    from pg_api.content import get_storage
    from pg_api.knowledge import source_storage

    stop = threading.Event()

    def churn():
        index = 0
        while not stop.is_set():
            index += 1
            source_storage().put_bytes(f"churn/source-{index}.txt", b"s")
            get_storage().put_text(f"churn/card-{index}.html", "<p>c</p>")
            time.sleep(0.01)

    writer = threading.Thread(target=churn)
    writer.start()
    try:
        bundles = []
        for _ in range(5):
            bundle = create_backup(destination_dir=str(tmp_path / "backups"))
            verified = verify_bundle(str(bundle))
            assert verified["checks"] == {"database": True, "sources": True, "artifacts": True}
            assert verified["integrity"] == "ok"
            bundles.append(bundle)
    finally:
        stop.set()
        writer.join(timeout=10)
    assert len(bundles) == 5
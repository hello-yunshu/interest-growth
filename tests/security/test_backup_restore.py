from __future__ import annotations

import json
import shutil
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
    assert manifest["schema_version"] == 13
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
    assert result["schema_version"] == 13
    assert result["missing_source_files"] == []
    assert result["missing_artifact_files"] == []
    with get_session_factory()() as db:
        assert db.scalar(select(func.max(SchemaMigration.version))) == 13
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
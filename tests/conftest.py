from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from pg_artifacts import LocalFilesystemStorage
from pg_api import content as content_module
from pg_api.db import reset_engine_for_tests
import pg_api.plugins as plugin_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SOURCE_STORAGE_ROOT", str(tmp_path / "source_files"))
    reset_engine_for_tests()
    plugin_module._runtime = None
    from pg_api.native_execution import reset_native_bundle_for_tests
    reset_native_bundle_for_tests()
    monkeypatch.setattr(content_module, "storage", LocalFilesystemStorage(tmp_path / "artifacts"))

    from pg_api.main import app

    with TestClient(app) as test_client:
        yield test_client

    plugin_module._runtime = None
    reset_native_bundle_for_tests()
    reset_engine_for_tests()

from pathlib import Path
import pytest

@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]

from pathlib import Path

import pytest

from pg_artifacts import LocalFilesystemStorage
from pg_event_bus import DomainEvent, EventBus


def test_event_bus_isolates_subscriber_failure():
    bus = EventBus()
    calls = []

    def broken(_):
        raise RuntimeError("plugin failed")

    def healthy(event):
        calls.append(event.type)

    bus.subscribe("claim.revised", broken)
    bus.subscribe("claim.revised", healthy)
    errors = bus.publish(DomainEvent(type="claim.revised", payload={"claim_id": "c1"}))

    assert len(errors) == 1
    assert calls == ["claim.revised"]


def test_local_storage_rejects_path_escape(tmp_path: Path):
    storage = LocalFilesystemStorage(tmp_path / "artifacts")
    storage.put_text("ok/note.md", "hello")
    assert storage.read_text("ok/note.md") == "hello"
    with pytest.raises(ValueError):
        storage.put_text("../secret.txt", "no")

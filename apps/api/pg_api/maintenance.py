"""Maintenance/write coordination lock for online backup consistency (Gate B3).

The backup bundle spans three components (SQLite snapshot + Source vault +
Artifact vault). The SQLite online snapshot is self-consistent, but the vault
copies must not race application writes, otherwise a bundle could reference a
file that was never copied.

Coordination model:
- Backups and restores take an EXCLUSIVE lock for their entire mutation span.
- Application vault writes take a SHARED lock around each file mutation.
- Within one process, a reader/writer gate serializes the two modes. Across
  processes, an advisory flock on the shared lock file provides exclusion.

The lock file lives next to the database so every process that can mutate the
persistent unit (API server, backup CLI) resolves the same path.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Iterator

try:  # POSIX advisory locking
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]
    _HAVE_FCNTL = False

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None  # type: ignore[assignment]

_cond = threading.Condition()
_readers = 0
_writer = False
_thread_counts: dict[int, dict[str, int]] = {}


def _lock_file_path(database_url: str) -> Path:
    data_root = os.getenv("APP_DATA_ROOT", "").strip()
    if data_root:
        root = Path(data_root)
    elif database_url.startswith("sqlite:///"):
        root = Path(database_url[len("sqlite:///"):]).parent
    else:
        root = Path(".").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / "maintenance.lock"


def _acquire_in_process(exclusive: bool, timeout: float | None = None) -> None:
    me = threading.get_ident()
    deadline = None if timeout is None else time.monotonic() + timeout
    global _readers, _writer
    with _cond:
        counts = _thread_counts.setdefault(me, {"shared": 0, "exclusive": 0})
        if exclusive and counts["exclusive"] == 0 and counts["shared"] == 0:
            while _readers or _writer:
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("maintenance lock not acquired within timeout")
                    _cond.wait(remaining)
                else:
                    _cond.wait()
            _writer = True
            counts["exclusive"] += 1
            return
        if exclusive:
            counts["exclusive"] += 1
            return
        if counts["exclusive"] or counts["shared"]:
            counts["shared"] += 1
            return
        while _writer:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("maintenance lock not acquired within timeout")
                _cond.wait(remaining)
            else:
                _cond.wait()
        _readers += 1
        counts["shared"] += 1


def _release_in_process(exclusive: bool) -> None:
    global _readers, _writer
    me = threading.get_ident()
    with _cond:
        counts = _thread_counts.get(me, {"shared": 0, "exclusive": 0})
        if exclusive:
            counts["exclusive"] -= 1
            if counts["exclusive"] == 0 and counts["shared"] == 0:
                _writer = False
        else:
            counts["shared"] -= 1
            if counts["shared"] == 0 and counts["exclusive"] == 0:
                _readers -= 1
        if not counts["exclusive"] and not counts["shared"]:
            _thread_counts.pop(me, None)
        _cond.notify_all()


def _flock_fd(handle, exclusive: bool) -> None:
    if _HAVE_FCNTL:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    elif exclusive and msvcrt is not None:  # pragma: no cover - Windows only
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)


def _flock_fd_timeout(handle, exclusive: bool, timeout: float | None) -> None:
    if timeout is None:
        _flock_fd(handle, exclusive)
        return
    if not _HAVE_FCNTL:  # pragma: no cover - Windows timeout best effort
        _flock_fd(handle, exclusive)
        return
    deadline = time.monotonic() + timeout
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    while True:
        try:
            fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"maintenance lock not acquired within {timeout}s"
                ) from None
            time.sleep(0.02)


@contextlib.contextmanager
def maintenance_lock(
    *,
    exclusive: bool,
    database_url: str | None = None,
    timeout: float | None = None,
) -> Iterator[None]:
    """Acquire the maintenance/write lock for one mutation or backup span."""
    from .db import get_settings  # local import: keep this module dependency-free

    url = database_url or get_settings().database_url
    _acquire_in_process(exclusive, timeout)
    handle = open(_lock_file_path(url), "a+b")
    try:
        _flock_fd_timeout(handle, exclusive, timeout)
        yield
    finally:
        try:
            _flock_fd(handle, exclusive=False)
        finally:
            handle.close()
            _release_in_process(exclusive)


@contextlib.contextmanager
def write_lock() -> Iterator[None]:
    """Shared lock held by application vault mutations during a backup/restore."""
    from .db import get_settings

    with maintenance_lock(exclusive=False, database_url=get_settings().database_url):
        yield

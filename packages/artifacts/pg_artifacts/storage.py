from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import nullcontext
from pathlib import Path
from typing import Any


class StorageProvider(ABC):
    @abstractmethod
    def put_text(self, key: str, content: str) -> str: ...

    @abstractmethod
    def read_text(self, key: str) -> str: ...

    @abstractmethod
    def put_bytes(self, key: str, content: bytes) -> str: ...

    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def path_for(self, key: str) -> Path: ...


class LocalFilesystemStorage(StorageProvider):
    def __init__(
        self,
        root: str | Path,
        *,
        write_lock: Any = None,
    ):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Optional shared write lock (e.g. the API maintenance lock) that
        # coordinates vault mutations with online backups. Pure-package
        # consumers keep a no-op lock and stay dependency-free.
        self._write_lock = write_lock or (lambda: nullcontext())

    def _safe(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("artifact key escapes storage root")
        return candidate

    def path_for(self, key: str) -> Path:
        return self._safe(key)

    def put_text(self, key: str, content: str) -> str:
        with self._write_lock():
            path = self._safe(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, "utf-8")
            return str(path.relative_to(self.root))

    def read_text(self, key: str) -> str:
        return self._safe(key).read_text("utf-8")

    def put_bytes(self, key: str, content: bytes) -> str:
        with self._write_lock():
            path = self._safe(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return str(path.relative_to(self.root))

    def read_bytes(self, key: str) -> bytes:
        return self._safe(key).read_bytes()

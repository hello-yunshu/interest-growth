from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


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
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("artifact key escapes storage root")
        return candidate

    def path_for(self, key: str) -> Path:
        return self._safe(key)

    def put_text(self, key: str, content: str) -> str:
        path = self._safe(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
        return str(path.relative_to(self.root))

    def read_text(self, key: str) -> str:
        return self._safe(key).read_text("utf-8")

    def put_bytes(self, key: str, content: bytes) -> str:
        path = self._safe(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path.relative_to(self.root))

    def read_bytes(self, key: str) -> bytes:
        return self._safe(key).read_bytes()

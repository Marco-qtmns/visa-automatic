from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


class StorageObjectNotFound(FileNotFoundError):
    pass


class StorageLimitExceeded(ValueError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int


class StorageProvider(Protocol):
    """Opaque binary storage contract used by document application services."""

    def save(self, source: BinaryIO, *, max_bytes: int) -> StoredObject: ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

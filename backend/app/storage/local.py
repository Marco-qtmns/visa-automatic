from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import BinaryIO

from .base import StorageLimitExceeded, StorageObjectNotFound, StoredObject


class LocalStorageProvider:
    """Development storage using generated opaque keys beneath one safe root."""

    CHUNK_SIZE = 1024 * 1024

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)

    @classmethod
    def from_environment(cls) -> LocalStorageProvider:
        default_root = Path(__file__).resolve().parents[2] / "storage"
        return cls(Path(os.environ.get("DOCUMENT_STORAGE_ROOT", str(default_root))))

    @classmethod
    def generated_from_environment(cls) -> LocalStorageProvider:
        default_root = Path(__file__).resolve().parents[2] / "generated-storage"
        return cls(Path(os.environ.get("GENERATED_ARTIFACT_STORAGE_ROOT", str(default_root))))

    def _path(self, key: str) -> Path:
        if not key or Path(key).is_absolute() or len(Path(key).parts) != 1:
            raise StorageObjectNotFound("stored document not found")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise StorageObjectNotFound("stored document not found")
        return path

    def save(self, source: BinaryIO, *, max_bytes: int) -> StoredObject:
        key = uuid.uuid4().hex
        destination = self._path(key)
        temporary = self._path(f"{key}.partial")
        size = 0
        try:
            with temporary.open("xb") as output:
                while chunk := source.read(self.CHUNK_SIZE):
                    size += len(chunk)
                    if size > max_bytes:
                        raise StorageLimitExceeded("file exceeds the maximum upload size")
                    output.write(chunk)
            temporary.replace(destination)
            if os.name != "nt":
                destination.chmod(0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return StoredObject(key=key, size_bytes=size)

    def open(self, key: str) -> BinaryIO:
        try:
            return self._path(key).open("rb")
        except FileNotFoundError as error:
            raise StorageObjectNotFound("stored document not found") from error

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except StorageObjectNotFound:
            return False

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except StorageObjectNotFound:
            return

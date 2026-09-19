from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .base import StorageBackend, StorageError


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        candidate = (self.root / key.lstrip("/")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError(f"Local storage key escapes its root: {key!r}")
        return candidate

    def upload_file(self, source: Path, key: str) -> bool:
        source = Path(source).resolve()
        destination = self._path(key)
        if source == destination:
            return False
        if destination.exists() and file_sha256(source) == file_sha256(destination):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise StorageError(f"Unable to store {source} at {destination}: {exc}") from exc
        return True

    def download_file(self, key: str, destination: Path) -> None:
        source = self._path(key)
        if not source.exists():
            raise StorageError(f"Local object does not exist: {key}")
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".downloading")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(destination)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise StorageError(f"Unable to restore {key} to {destination}: {exc}") from exc

    def object_exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list_objects(self, prefix: str) -> list[str]:
        start = self._path(prefix)
        if start.is_file():
            return [start.relative_to(self.root).as_posix()]
        if not start.exists():
            return []
        return sorted(path.relative_to(self.root).as_posix() for path in start.rglob("*") if path.is_file())

    def object_metadata(self, key: str) -> dict[str, Any]:
        path = self._path(key)
        if not path.exists():
            raise StorageError(f"Local object does not exist: {key}")
        stat = path.stat()
        return {"ContentLength": stat.st_size, "sha256": file_sha256(path), "LastModified": stat.st_mtime}

    def delete_object(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

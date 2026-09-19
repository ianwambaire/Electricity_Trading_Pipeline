from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    """A durable-storage operation failed."""


class StorageBackend(ABC):
    @abstractmethod
    def upload_file(self, source: Path, key: str) -> bool:
        """Upload source to key and return False when identical content exists."""

    @abstractmethod
    def download_file(self, key: str, destination: Path) -> None:
        pass

    @abstractmethod
    def object_exists(self, key: str) -> bool:
        pass

    @abstractmethod
    def list_objects(self, prefix: str) -> list[str]:
        pass

    @abstractmethod
    def object_metadata(self, key: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def delete_object(self, key: str) -> None:
        pass

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import StorageConfig
from .factory import create_storage_backend
from .mappings import ARTIFACT_MAPPINGS, GROUPS


@dataclass
class SyncResult:
    stage: str
    status: str
    uploaded: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


class StorageSync:
    def __init__(self, config: StorageConfig, project_root: Path, backend=None):
        self.config = config
        self.project_root = Path(project_root)
        self.backend = backend or create_storage_backend(config)

    def sync_group(self, group: str, *, require_all: bool = True) -> SyncResult:
        if group not in GROUPS:
            raise ValueError(f"Unknown storage sync group: {group}")
        if self.config.backend == "local":
            return SyncResult(group, "NOT_REQUIRED")

        result = SyncResult(group, "SUCCESS")
        for relative_path in GROUPS[group]:
            source = self.project_root / relative_path
            if not source.is_file():
                if require_all:
                    raise FileNotFoundError(f"Expected artifact does not exist: {source}")
                continue
            key = ARTIFACT_MAPPINGS[relative_path]
            changed = self.backend.upload_file(source, key)
            (result.uploaded if changed else result.unchanged).append(key)
        return result

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_AWS_REGION = "us-east-1"


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "local"
    s3_bucket: str | None = None
    aws_region: str = DEFAULT_AWS_REGION
    local_root: Path = Path(".")

    def __post_init__(self):
        backend = self.backend.strip().lower()
        if backend not in {"local", "s3"}:
            raise ValueError("POWERFLOW_STORAGE_BACKEND must be 'local' or 's3'.")
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "local_root", Path(self.local_root))
        if backend == "s3" and not self.s3_bucket:
            raise ValueError("POWERFLOW_S3_BUCKET is required for the S3 backend.")

    @classmethod
    def from_env(cls, backend_override: str | None = None) -> "StorageConfig":
        return cls(
            backend=backend_override or os.getenv("POWERFLOW_STORAGE_BACKEND", "local"),
            s3_bucket=os.getenv("POWERFLOW_S3_BUCKET") or None,
            aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", DEFAULT_AWS_REGION)),
            local_root=Path(os.getenv("POWERFLOW_LOCAL_STORAGE_ROOT", ".")),
        )

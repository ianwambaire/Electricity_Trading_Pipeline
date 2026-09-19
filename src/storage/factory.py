from .base import StorageBackend
from .config import StorageConfig
from .local import LocalStorageBackend
from .s3 import S3StorageBackend


def create_storage_backend(config: StorageConfig, *, s3_client=None) -> StorageBackend:
    if config.backend == "local":
        return LocalStorageBackend(config.local_root)
    return S3StorageBackend(config.s3_bucket, config.aws_region, client=s3_client)

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from .base import StorageBackend, StorageError
from .local import file_sha256

logger = logging.getLogger(__name__)


class S3StorageBackend(StorageBackend):
    """Small boto3-backed adapter using the normal AWS provider chain."""

    def __init__(self, bucket: str, region: str, client=None):
        self.bucket = bucket
        self.region = region
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise StorageError("boto3 is required when POWERFLOW_STORAGE_BACKEND=s3.") from exc
            client = boto3.client(
                "s3",
                region_name=region,
                config=Config(retries={"max_attempts": 5, "mode": "standard"}),
            )
        self.client = client

    @staticmethod
    def _not_found(error: Exception) -> bool:
        response = getattr(error, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in {"404", "NoSuchKey", "NotFound"} or status == 404

    def object_metadata(self, key: str) -> dict[str, Any]:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"Unable to read s3://{self.bucket}/{key} metadata: {exc}") from exc

    def object_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            if self._not_found(exc):
                return False
            raise StorageError(f"Unable to check s3://{self.bucket}/{key}: {exc}") from exc

    def upload_file(self, source: Path, key: str) -> bool:
        source = Path(source)
        if not source.is_file():
            raise StorageError(f"Upload source is not a file: {source}")
        digest = file_sha256(source)
        try:
            if self.object_exists(key):
                existing = self.object_metadata(key)
                if (
                    existing.get("Metadata", {}).get("powerflow-sha256") == digest
                    and existing.get("ContentLength") == source.stat().st_size
                ):
                    logger.info("S3 object unchanged; skipping s3://%s/%s", self.bucket, key)
                    return False

            temporary_key = f"{key}.uploading-{uuid.uuid4().hex}"
            logger.info("Uploading %s to temporary S3 key %s", source, temporary_key)
            self.client.upload_file(
                str(source), self.bucket, temporary_key,
                ExtraArgs={"Metadata": {"powerflow-sha256": digest}},
            )
            temporary = self.client.head_object(
                Bucket=self.bucket,
                Key=temporary_key,
            )
            temporary_version_id = temporary.get("VersionId")
            if (
                temporary.get("ContentLength") != source.stat().st_size
                or temporary.get("Metadata", {}).get("powerflow-sha256") != digest
            ):
                raise StorageError(
                    f"S3 temporary-upload verification failed for "
                    f"s3://{self.bucket}/{key}"
                )
            self.client.copy_object(
                Bucket=self.bucket,
                Key=key,
                CopySource={"Bucket": self.bucket, "Key": temporary_key},
                Metadata={"powerflow-sha256": digest},
                MetadataDirective="REPLACE",
            )
            self.delete_uploaded_object(temporary_key, temporary_version_id)
            final = self.client.head_object(Bucket=self.bucket, Key=key)
            if (
                final.get("ContentLength") != source.stat().st_size
                or final.get("Metadata", {}).get("powerflow-sha256") != digest
            ):
                raise StorageError(
                    f"S3 final-object verification failed for s3://{self.bucket}/{key}"
                )
            logger.info("Uploaded %s to s3://%s/%s", source, self.bucket, key)
            return True
        except Exception as exc:
            try:
                if "temporary_key" in locals():
                    if "temporary_version_id" not in locals():
                        temporary_version_id = self.client.head_object(
                            Bucket=self.bucket,
                            Key=temporary_key,
                        ).get("VersionId")
                    self.delete_uploaded_object(temporary_key, temporary_version_id)
            except Exception:
                logger.warning("Unable to clean temporary S3 key %s", temporary_key, exc_info=True)
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"Unable to upload {source} to s3://{self.bucket}/{key}: {exc}") from exc

    def delete_uploaded_object(self, key: str, version_id: str | None = None) -> None:
        """Remove an object just uploaded by PowerFlow, including its version marker."""
        try:
            response = self.client.delete_object(Bucket=self.bucket, Key=key)
            marker_version = (
                response.get("VersionId") if response.get("DeleteMarker") else None
            )
            if version_id:
                self.client.delete_object(
                    Bucket=self.bucket,
                    Key=key,
                    VersionId=version_id,
                )
            if marker_version and marker_version != version_id:
                self.client.delete_object(
                    Bucket=self.bucket,
                    Key=key,
                    VersionId=marker_version,
                )
        except Exception as exc:
            raise StorageError(
                f"Unable to purge uploaded s3://{self.bucket}/{key}: {exc}"
            ) from exc

    def download_file(self, key: str, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".downloading")
        try:
            self.client.download_file(self.bucket, key, str(temporary))
            temporary.replace(destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise StorageError(f"Unable to download s3://{self.bucket}/{key}: {exc}") from exc

    def list_objects(self, prefix: str) -> list[str]:
        keys = []
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys.extend(item["Key"] for item in page.get("Contents", []))
        except Exception as exc:
            raise StorageError(f"Unable to list s3://{self.bucket}/{prefix}: {exc}") from exc
        return keys

    def delete_object(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"Unable to delete s3://{self.bucket}/{key}: {exc}") from exc

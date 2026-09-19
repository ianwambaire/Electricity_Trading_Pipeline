"""Non-destructive S3 reachability and read/write/delete smoke check."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import uuid
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1]
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from storage.config import StorageConfig
from storage.factory import create_storage_backend


EXPECTED_PREFIXES = (
    "raw/entsoe/prices/", "raw/entsoe/load/", "raw/entsoe/generation/",
    "raw/weather/", "silver/", "gold/", "reports/predictions/",
    "reports/anomalies/", "reports/monitoring/", "models/releases/",
)


def check_s3(config: StorageConfig) -> dict:
    if config.backend != "s3":
        raise ValueError("S3 check requires POWERFLOW_STORAGE_BACKEND=s3.")
    backend = create_storage_backend(config)
    backend.client.head_bucket(Bucket=config.s3_bucket)
    prefix_counts = {prefix: len(backend.list_objects(prefix)) for prefix in EXPECTED_PREFIXES}
    key = f"reports/monitoring/storage-check-{uuid.uuid4().hex}.json"
    payload = {"check": "powerflow-s3-read-write-delete", "bucket": config.s3_bucket}
    with tempfile.TemporaryDirectory(prefix="powerflow-s3-check-") as directory:
        source = Path(directory) / "probe.json"
        restored = Path(directory) / "restored.json"
        source.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        uploaded_version_id = None
        try:
            backend.upload_file(source, key)
            uploaded_version_id = backend.object_metadata(key).get("VersionId")
            backend.download_file(key, restored)
            if json.loads(restored.read_text(encoding="utf-8")) != payload:
                raise RuntimeError("S3 smoke-check content verification failed.")
        finally:
            backend.delete_uploaded_object(key, uploaded_version_id)
    return {"bucket": config.s3_bucket, "region": config.aws_region, "prefix_counts": prefix_counts, "success": True}


def main():
    parser = argparse.ArgumentParser(description="Verify PowerFlow S3 access.")
    parser.add_argument("--bucket", help="Override POWERFLOW_S3_BUCKET.")
    parser.add_argument("--region", help="Override AWS_REGION.")
    args = parser.parse_args()
    config = StorageConfig.from_env("s3")
    if args.bucket or args.region:
        config = StorageConfig("s3", args.bucket or config.s3_bucket, args.region or config.aws_region)
    print(json.dumps(check_s3(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only inspection of PowerFlow S3 recovery settings and prefixes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PREFIXES = ("raw/", "silver/", "gold/", "reports/", "models/releases/")
STATIC_CREDENTIAL_VARIABLES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


def _no_such_configuration(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in {"NoSuchLifecycleConfiguration", "NoSuchConfiguration", "404"}


def check_s3_recovery_readiness(bucket: str, region: str, *, client=None) -> dict:
    """Inspect recovery controls using only read/list S3 API calls."""
    if not bucket:
        raise ValueError("An S3 bucket name is required.")
    if client is None:
        client = boto3.client("s3", region_name=region)
    client.head_bucket(Bucket=bucket)
    versioning = client.get_bucket_versioning(Bucket=bucket)
    try:
        encryption = client.get_bucket_encryption(Bucket=bucket)
        encryption_rules = [
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
            for rule in encryption.get("ServerSideEncryptionConfiguration", {}).get(
                "Rules", []
            )
        ]
        encryption_rules = [value for value in encryption_rules if value]
    except ClientError as error:
        if not _no_such_configuration(error):
            raise
        encryption_rules = []
    try:
        lifecycle = client.get_bucket_lifecycle_configuration(Bucket=bucket)
        lifecycle_rules = [
            {"id": rule.get("ID"), "status": rule.get("Status")}
            for rule in lifecycle.get("Rules", [])
        ]
    except ClientError as error:
        if not _no_such_configuration(error):
            raise
        lifecycle_rules = []
    prefixes = {}
    for prefix in PRODUCTION_PREFIXES:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
        prefixes[prefix] = {
            "present": bool(response.get("KeyCount", 0)),
            "sample_key": response.get("Contents", [{}])[0].get("Key")
            if response.get("Contents")
            else None,
        }
    return {
        "bucket": bucket,
        "region": region,
        "bucket_accessible": True,
        "versioning_status": versioning.get("Status", "Disabled"),
        "mfa_delete": versioning.get("MFADelete"),
        "encryption_algorithms": encryption_rules,
        "lifecycle_rules": lifecycle_rules,
        "prefixes": prefixes,
        "read_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", help="Override POWERFLOW_S3_BUCKET.")
    parser.add_argument("--region", help="Override AWS_REGION/AWS_DEFAULT_REGION.")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    configured_static = [name for name in STATIC_CREDENTIAL_VARIABLES if os.getenv(name)]
    if configured_static:
        raise RuntimeError(
            "Static AWS credential environment variables are not permitted; "
            "use the EC2 IAM role."
        )
    bucket = args.bucket or os.getenv("POWERFLOW_S3_BUCKET")
    region = args.region or os.getenv("AWS_REGION") or os.getenv(
        "AWS_DEFAULT_REGION", "us-east-1"
    )
    print(json.dumps(check_s3_recovery_readiness(bucket, region), indent=2))


if __name__ == "__main__":
    main()

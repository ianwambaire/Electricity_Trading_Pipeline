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
ACCESS_DENIED_CODES = {"AccessDenied", "AllAccessDisabled", "403"}
PERMISSIONS = {
    "bucket_access": "s3:ListBucket",
    "versioning": "s3:GetBucketVersioning",
    "encryption": "s3:GetEncryptionConfiguration",
    "lifecycle": "s3:GetLifecycleConfiguration",
    "prefix_listing": "s3:ListBucket",
}


def _no_such_configuration(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in {
        "NoSuchLifecycleConfiguration",
        "NoSuchConfiguration",
        "ServerSideEncryptionConfigurationNotFoundError",
        "404",
    }


def _error_result(error: ClientError, permission: str) -> dict:
    code = str(error.response.get("Error", {}).get("Code", "Unknown"))
    if code in ACCESS_DENIED_CODES:
        return {
            "status": "permission_unavailable",
            "required_permission": permission,
        }
    return {"status": "error", "error_code": code}


def _overall_status(results: list[dict]) -> str:
    statuses = {result.get("status") for result in results}
    for status in ("error", "permission_unavailable", "not_configured"):
        if status in statuses:
            return status
    return "configured"


def check_s3_recovery_readiness(bucket: str, region: str, *, client=None) -> dict:
    """Inspect recovery controls using only read/list S3 API calls."""
    if not bucket:
        raise ValueError("An S3 bucket name is required.")
    if client is None:
        client = boto3.client("s3", region_name=region)

    try:
        client.head_bucket(Bucket=bucket)
        bucket_access = {"status": "configured", "accessible": True}
    except ClientError as error:
        bucket_access = _error_result(error, PERMISSIONS["bucket_access"])

    try:
        response = client.get_bucket_versioning(Bucket=bucket)
        versioning_value = response.get("Status")
        versioning = {
            "status": "configured" if versioning_value == "Enabled" else "not_configured",
            "value": versioning_value or "Disabled",
            "mfa_delete": response.get("MFADelete"),
        }
    except ClientError as error:
        versioning = _error_result(error, PERMISSIONS["versioning"])

    try:
        response = client.get_bucket_encryption(Bucket=bucket)
        encryption_rules = [
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
            for rule in response.get("ServerSideEncryptionConfiguration", {}).get(
                "Rules", []
            )
        ]
        encryption_rules = [value for value in encryption_rules if value]
        encryption = {
            "status": "configured" if encryption_rules else "not_configured",
            "algorithms": encryption_rules,
        }
    except ClientError as error:
        encryption = (
            {"status": "not_configured", "algorithms": []}
            if _no_such_configuration(error)
            else _error_result(error, PERMISSIONS["encryption"])
        )

    try:
        response = client.get_bucket_lifecycle_configuration(Bucket=bucket)
        lifecycle_rules = [
            {"id": rule.get("ID"), "status": rule.get("Status")}
            for rule in response.get("Rules", [])
        ]
        lifecycle = {
            "status": "configured" if lifecycle_rules else "not_configured",
            "rules": lifecycle_rules,
        }
    except ClientError as error:
        lifecycle = (
            {"status": "not_configured", "rules": []}
            if _no_such_configuration(error)
            else _error_result(error, PERMISSIONS["lifecycle"])
        )

    prefixes = {}
    for prefix in PRODUCTION_PREFIXES:
        try:
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
            present = bool(response.get("KeyCount", 0))
            prefixes[prefix] = {
                "status": "configured" if present else "not_configured",
                "present": present,
                "sample_key": response.get("Contents", [{}])[0].get("Key")
                if response.get("Contents")
                else None,
            }
        except ClientError as error:
            prefixes[prefix] = _error_result(
                error, PERMISSIONS["prefix_listing"]
            )
    capability_results = [bucket_access, versioning, encryption, lifecycle, *prefixes.values()]
    return {
        "bucket": bucket,
        "region": region,
        "overall_status": _overall_status(capability_results),
        "bucket_access": bucket_access,
        "versioning": versioning,
        "encryption": encryption,
        "lifecycle": lifecycle,
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

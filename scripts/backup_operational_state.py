#!/usr/bin/env python3
"""Create a consistent, hash-verifiable backup of PowerFlow operational SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from operational_recovery import backup_operational_database, upload_operational_backup


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "database/electricity_trading.db",
        help="Operational SQLite database to back up.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "backups/operational",
        help="Directory under which a UTC-stamped backup is created.",
    )
    parser.add_argument(
        "--upload-s3",
        action="store_true",
        help="Upload the validated backup to the dedicated S3 backup prefix.",
    )
    parser.add_argument(
        "--bucket",
        default=os.getenv("POWERFLOW_S3_BUCKET"),
        help="S3 bucket; defaults to POWERFLOW_S3_BUCKET.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        help="AWS region for IAM-role-backed S3 access.",
    )
    args = parser.parse_args()
    backup_dir = backup_operational_database(
        args.database,
        backup_root=args.output_root,
        project_root=PROJECT_ROOT,
    )
    result = {"status": "created", "backup_dir": str(backup_dir)}
    if args.upload_s3:
        if not args.bucket:
            parser.error("--upload-s3 requires --bucket or POWERFLOW_S3_BUCKET.")
        import boto3

        client = boto3.client("s3", region_name=args.region)
        result["s3"] = upload_operational_backup(
            backup_dir,
            bucket=args.bucket,
            client=client,
        )
        result["status"] = "created_and_uploaded"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

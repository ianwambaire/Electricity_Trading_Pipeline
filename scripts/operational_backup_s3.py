#!/usr/bin/env python3
"""List, download, or restore validated PowerFlow operational backups from S3."""

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

from operational_recovery import (  # noqa: E402
    download_operational_backup,
    list_operational_backups,
    restore_operational_database_from_s3,
)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bucket",
        default=os.getenv("POWERFLOW_S3_BUCKET"),
        help="S3 bucket; defaults to POWERFLOW_S3_BUCKET.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        help="AWS region using the standard IAM role credential chain.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List complete operational backups in S3.")

    download = commands.add_parser("download", help="Download and validate one backup.")
    download.add_argument("backup_id", help="Explicit UTC timestamp backup ID.")
    download.add_argument(
        "--download-root",
        type=Path,
        default=PROJECT_ROOT / "backups/operational-s3",
    )

    restore = commands.add_parser("restore", help="Download, validate, and restore one backup.")
    restore.add_argument("backup_id", help="Explicit UTC timestamp backup ID.")
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument(
        "--download-root",
        type=Path,
        default=PROJECT_ROOT / "backups/operational-s3",
    )
    restore.add_argument("--force", action="store_true")
    restore.add_argument("--pre-restore-root", type=Path)
    args = parser.parse_args()
    if not args.bucket:
        parser.error("--bucket or POWERFLOW_S3_BUCKET is required.")

    import boto3

    client = boto3.client("s3", region_name=args.region)
    if args.command == "list":
        result = {
            "status": "ok",
            "bucket": args.bucket,
            "backups": list_operational_backups(bucket=args.bucket, client=client),
        }
    elif args.command == "download":
        result = download_operational_backup(
            args.backup_id,
            bucket=args.bucket,
            client=client,
            download_root=args.download_root,
        )
    else:
        if args.force:
            print(
                "WARNING: --force requested; the active database is replaced only "
                "after S3 download and checksum validation."
            )
        result = restore_operational_database_from_s3(
            args.backup_id,
            args.destination,
            bucket=args.bucket,
            client=client,
            download_root=args.download_root,
            force=args.force,
            pre_restore_root=args.pre_restore_root,
            project_root=PROJECT_ROOT,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

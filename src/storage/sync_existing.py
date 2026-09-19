"""Idempotently upload existing PowerFlow artifacts to configured S3 storage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOURCE_DIR.parent
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from storage.config import StorageConfig
from storage.sync import StorageSync


MIGRATION_GROUPS = ("raw", "silver", "gold", "predictions", "anomalies", "monitoring", "models")


def main():
    parser = argparse.ArgumentParser(description="Upload existing PowerFlow artifacts to S3.")
    parser.add_argument("groups", nargs="*", choices=MIGRATION_GROUPS, default=list(MIGRATION_GROUPS))
    args = parser.parse_args()
    config = StorageConfig.from_env()
    if config.backend != "s3":
        raise SystemExit("Set POWERFLOW_STORAGE_BACKEND=s3 before running migration.")
    synchronizer = StorageSync(config, PROJECT_ROOT)
    results = []
    for group in args.groups:
        result = synchronizer.sync_group(group, require_all=False)
        results.append({"group": group, "status": result.status, "uploaded": result.uploaded, "unchanged": result.unchanged})
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

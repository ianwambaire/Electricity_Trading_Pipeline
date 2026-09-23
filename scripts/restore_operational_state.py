#!/usr/bin/env python3
"""Restore PowerFlow operational SQLite to an explicit destination safely."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from operational_recovery import restore_operational_database


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Restore a validated operational backup. Existing destinations are "
            "never overwritten unless --force is supplied; forced restores first "
            "create a pre-restore backup."
        )
    )
    parser.add_argument("backup_dir", type=Path, help="UTC-stamped backup directory.")
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Explicit SQLite destination path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Permit replacement after creating a pre-restore backup.",
    )
    parser.add_argument(
        "--pre-restore-root",
        type=Path,
        help="Optional directory for the mandatory pre-overwrite backup.",
    )
    args = parser.parse_args()
    if args.force:
        print("WARNING: --force requested; the destination will be replaced only after backup.")
    result = restore_operational_database(
        args.backup_dir,
        args.destination,
        force=args.force,
        pre_restore_root=args.pre_restore_root,
        project_root=PROJECT_ROOT,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

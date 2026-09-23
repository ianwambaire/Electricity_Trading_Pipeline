#!/usr/bin/env python3
"""Create a consistent, hash-verifiable backup of PowerFlow operational SQLite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from operational_recovery import backup_operational_database


def main() -> None:
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
    args = parser.parse_args()
    backup_dir = backup_operational_database(
        args.database,
        backup_root=args.output_root,
        project_root=PROJECT_ROOT,
    )
    print(json.dumps({"status": "created", "backup_dir": str(backup_dir)}, indent=2))


if __name__ == "__main__":
    main()

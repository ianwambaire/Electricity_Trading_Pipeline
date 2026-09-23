#!/usr/bin/env python3
"""Capture approved PowerFlow reports and operational evidence for presentation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from presentation_snapshot import create_presentation_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "database/electricity_trading.db",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "presentation_snapshots",
    )
    args = parser.parse_args()
    snapshot_dir = create_presentation_snapshot(
        PROJECT_ROOT,
        output_root=args.output_root,
        database_path=args.database,
    )
    print(json.dumps({"status": "created", "snapshot_dir": str(snapshot_dir)}, indent=2))


if __name__ == "__main__":
    main()

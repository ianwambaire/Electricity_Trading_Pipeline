#!/usr/bin/env python3
"""Validate a PowerFlow operational backup without restoring it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "src"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from operational_recovery import validate_operational_backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_dir", type=Path, help="UTC-stamped backup directory.")
    args = parser.parse_args()
    print(json.dumps(validate_operational_backup(args.backup_dir), indent=2))


if __name__ == "__main__":
    main()

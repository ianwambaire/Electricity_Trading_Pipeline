"""Read-only preview or guarded late-value repair for raw ENTSO-E generation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ingestion.fetch_entsoe_data import repair_generation_interval  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or fill only missing raw generation cells from ENTSO-E."
    )
    parser.add_argument("--start", required=True, help="Inclusive UTC timestamp.")
    parser.add_argument("--end", required=True, help="Exclusive UTC timestamp.")
    parser.add_argument(
        "--apply", action="store_true",
        help="Atomically write genuine newly available values; default is read-only.",
    )
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("ENTSOE_API_KEY")
    if not token:
        parser.error("ENTSOE_API_KEY is not configured.")
    client = EntsoePandasClient(api_key=token)
    result = repair_generation_interval(
        client,
        pd.Timestamp(args.start),
        pd.Timestamp(args.end),
        path=PROJECT_ROOT / "data/raw/entsoe/generation.csv",
        apply=args.apply,
    )
    print(json.dumps(result, indent=2))
    if not result["repaired_cells"]:
        print("No genuine missing generation values were available; stored data is unchanged.")
    elif not args.apply:
        print("Dry run only. Rerun with --apply after reviewing the proposed repairs.")


if __name__ == "__main__":
    main()

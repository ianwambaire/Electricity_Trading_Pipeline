import argparse
import sys
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1]

if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from scheduled_pipeline import powerflow_entsoe_pipeline


def parse_args():
    parser = argparse.ArgumentParser(description="Run the PowerFlow ENTSO-E flow.")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        default="incremental",
    )
    parser.add_argument("--start-date", help="Historical mode start (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Historical mode end (YYYY-MM-DD).")
    return parser.parse_args()


def main():
    arguments = parse_args()
    powerflow_entsoe_pipeline(
        mode=arguments.mode,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
    )


if __name__ == "__main__":
    main()

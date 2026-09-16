import sys
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[1]

if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

from scheduled_pipeline import powerflow_entsoe_pipeline


def main():
    powerflow_entsoe_pipeline()


if __name__ == "__main__":
    main()

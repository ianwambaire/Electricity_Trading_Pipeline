from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = PROJECT_ROOT / "data" / "sample" / "entsoe_silver_sample.csv"


def test_repository_silver_sample_is_readable():
    sample = pd.read_csv(SAMPLE_PATH)
    timestamps = pd.to_datetime(sample["timestamp"], errors="coerce", utc=True)

    assert len(sample) == 150
    assert set(["timestamp", "price_eur_mwh", "load_mw"]).issubset(sample.columns)
    assert timestamps.notna().all()

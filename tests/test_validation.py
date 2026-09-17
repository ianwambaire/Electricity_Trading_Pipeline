import pandas as pd
import pytest

from validate_data import (
    GOLD_MODEL_FEATURE_COLUMNS,
    GOLD_TARGET_COLUMN,
    MIN_GOLD_ROWS,
    MIN_SILVER_ROWS,
    SILVER_REQUIRED_COLUMNS,
    validate_gold_data,
    validate_silver_data,
)


@pytest.fixture
def valid_silver_data():
    row_count = MIN_SILVER_ROWS
    data = {
        "timestamp": pd.date_range(
            "2024-01-01", periods=row_count, freq="h", tz="UTC"
        )
    }
    for position, column in enumerate(SILVER_REQUIRED_COLUMNS[1:], start=1):
        data[column] = [float(position + row) for row in range(row_count)]
    return pd.DataFrame(data)


@pytest.fixture
def valid_gold_data():
    row_count = MIN_GOLD_ROWS
    data = {
        "timestamp": pd.date_range(
            "2024-01-01", periods=row_count, freq="h", tz="UTC"
        )
    }
    for position, column in enumerate(GOLD_MODEL_FEATURE_COLUMNS, start=1):
        data[column] = [float(position + row) for row in range(row_count)]
    data[GOLD_TARGET_COLUMN] = [float(50 + row) for row in range(row_count)]
    return pd.DataFrame(data)


def test_valid_silver_sample_passes(valid_silver_data):
    assert validate_silver_data(valid_silver_data, log_results=False)


def test_valid_gold_sample_passes(valid_gold_data):
    assert validate_gold_data(valid_gold_data, log_results=False)


def test_negative_electricity_prices_are_accepted(valid_silver_data):
    valid_silver_data.loc[0, "price_eur_mwh"] = -25.0

    assert validate_silver_data(valid_silver_data, log_results=False)


def test_malformed_timestamp_fails_validation(valid_silver_data):
    valid_silver_data["timestamp"] = valid_silver_data["timestamp"].astype(str)
    valid_silver_data.loc[valid_silver_data.index[-1], "timestamp"] = "not-a-timestamp"

    assert not validate_silver_data(valid_silver_data, log_results=False)


def test_missing_hour_fails_silver_temporal_integrity(valid_silver_data):
    data_with_gap = valid_silver_data.drop(index=10).reset_index(drop=True)

    assert not validate_silver_data(data_with_gap, log_results=False)

import pandas as pd
import pytest
import validate_data as validation_module

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


def test_missing_hour_is_allowed_when_later_silver_hours_are_valid(valid_silver_data):
    data_with_gap = pd.concat(
        [valid_silver_data, valid_silver_data.tail(1).assign(
            timestamp=valid_silver_data["timestamp"].iloc[-1] + pd.Timedelta(hours=1)
        )], ignore_index=True
    ).drop(index=10).reset_index(drop=True)

    assert validate_silver_data(data_with_gap, log_results=False)


def test_missing_silver_hour_is_recorded_as_warning(valid_silver_data, monkeypatch):
    data_with_gap = valid_silver_data.drop(index=10).reset_index(drop=True)
    data_with_gap = pd.concat(
        [data_with_gap, valid_silver_data.tail(1).assign(
            timestamp=valid_silver_data["timestamp"].iloc[-1] + pd.Timedelta(hours=1)
        )], ignore_index=True
    )
    recorded = []
    monkeypatch.setattr(validation_module, "initialize_database", lambda: None)
    monkeypatch.setattr(
        validation_module, "log_data_quality_result",
        lambda name, status, message: recorded.append((name, status, message)),
    )

    assert validate_silver_data(data_with_gap, log_results=True)
    warnings = [item for item in recorded if item[1] == "WARNING"]
    assert len(warnings) == 1
    assert "1 hourly timestamps excluded" in warnings[0][2]
    assert "later valid hours retained" in warnings[0][2]


def test_non_hourly_silver_timestamp_still_fails(valid_silver_data):
    valid_silver_data.loc[10, "timestamp"] += pd.Timedelta(minutes=15)

    assert not validate_silver_data(valid_silver_data, log_results=False)

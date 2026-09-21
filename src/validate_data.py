import argparse
import pandas as pd
from pathlib import Path
from store_data import initialize_database, log_data_quality_result


VALIDATION_REPORT_PATH = Path("data/reports/validation_report.txt")
SILVER_DATA_PATH = Path("data/processed/silver_electricity_market_data.csv")
GOLD_DATA_PATH = Path("data/features/gold_model_features.csv")

SILVER_REQUIRED_COLUMNS = [
    "timestamp",
    "price_eur_mwh",
    "load_mw",
    "biomass_mw",
    "lignite_mw",
    "gas_mw",
    "hard_coal_mw",
    "hydro_mw",
    "nuclear_mw",
    "solar_mw",
    "wind_offshore_mw",
    "wind_onshore_mw",
    "wind_total_mw",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
]

# Nuclear generation is intentionally excluded because Germany's final nuclear
# plants stopped reporting from local midnight on 2023-04-16
# (2023-04-15 22:00 UTC), and the gold builder converts later nulls to 0 MW.
SILVER_ESSENTIAL_FORECASTING_FIELDS = [
    column for column in SILVER_REQUIRED_COLUMNS
    if column not in {"timestamp", "nuclear_mw"}
]

GOLD_MODEL_FEATURE_COLUMNS = [
    "price_eur_mwh",
    "load_mw",
    "biomass_mw",
    "lignite_mw",
    "gas_mw",
    "hard_coal_mw",
    "hydro_mw",
    "nuclear_mw",
    "solar_mw",
    "wind_offshore_mw",
    "wind_onshore_mw",
    "wind_total_mw",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "cloud_cover",
    "shortwave_radiation",
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "price_lag_1h",
    "price_lag_24h",
    "price_lag_168h",
    "load_lag_1h",
    "load_lag_24h",
    "price_rolling_mean_24h",
    "price_rolling_std_24h",
    "load_rolling_mean_24h",
    "renewable_generation_mw",
    "renewable_share",
]

GOLD_TARGET_COLUMN = "target_price_next_hour"
MIN_GOLD_ROWS = 10
NUCLEAR_SHUTDOWN_UTC = pd.Timestamp("2023-04-15T22:00:00Z")
# The gold builder needs a 168-hour lag, a next-hour target, and at least ten
# resulting rows for the existing chronological 80/20 model split.
MIN_SILVER_ROWS = 168 + 1 + MIN_GOLD_ROWS


def _log_check(
    check_name: str,
    passed: bool,
    passed_message: str,
    failed_message: str,
    errors: list[str],
    log_results: bool,
):
    status = "PASSED" if passed else "FAILED"
    message = passed_message if passed else failed_message

    if not passed:
        errors.append(message)

    if log_results:
        log_data_quality_result(check_name, status, message)


def _validate_timestamp(
    data: pd.DataFrame,
    dataset_name: str,
    errors: list[str],
    log_results: bool,
    require_order: bool,
):
    if "timestamp" not in data.columns:
        _log_check(
            f"{dataset_name} Timestamp Check",
            False,
            "Timestamp column is present and parseable.",
            "Missing required timestamp column.",
            errors,
            log_results,
        )
        return

    timestamps = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    invalid_count = int(timestamps.isna().sum())
    _log_check(
        f"{dataset_name} Timestamp Check",
        invalid_count == 0,
        "All timestamps are present and parseable.",
        f"Timestamp column contains {invalid_count} missing or unparseable values.",
        errors,
        log_results,
    )

    duplicate_count = int(timestamps.dropna().duplicated().sum())
    _log_check(
        f"{dataset_name} Timestamp Uniqueness Check",
        duplicate_count == 0,
        "No duplicate timestamps found.",
        f"Dataset contains {duplicate_count} duplicate timestamps.",
        errors,
        log_results,
    )

    if require_order:
        ordered = invalid_count == 0 and timestamps.is_monotonic_increasing
        _log_check(
            f"{dataset_name} Timestamp Order Check",
            ordered,
            "Timestamps are in chronological order.",
            "Timestamps are not in chronological order.",
            errors,
            log_results,
        )


def _validate_numeric_columns(
    data: pd.DataFrame,
    columns: list[str],
    dataset_name: str,
    errors: list[str],
    log_results: bool,
):
    unusable_columns = []

    for column in columns:
        if column not in data.columns:
            continue

        numeric_values = pd.to_numeric(data[column], errors="coerce")
        invalid_count = int((data[column].notna() & numeric_values.isna()).sum())

        if invalid_count > 0 or not numeric_values.notna().any():
            unusable_columns.append(f"{column} ({invalid_count} invalid values)")

    _log_check(
        f"{dataset_name} Numeric Columns Check",
        not unusable_columns,
        "All required numeric columns contain usable numeric values.",
        "Unusable numeric columns: " + ", ".join(unusable_columns),
        errors,
        log_results,
    )


def _validate_hourly_continuity(
    data: pd.DataFrame,
    dataset_name: str,
    errors: list[str],
    log_results: bool,
):
    if "timestamp" not in data.columns:
        return

    timestamps = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    valid_timestamps = pd.DatetimeIndex(timestamps.dropna())
    if valid_timestamps.empty:
        missing_timestamps = pd.DatetimeIndex([], tz="UTC")
        valid_hours = False
    else:
        expected = pd.date_range(
            valid_timestamps.min(),
            valid_timestamps.max(),
            freq="h",
            tz="UTC",
        )
        missing_timestamps = expected.difference(valid_timestamps)
        valid_hours = (
            timestamps.notna().all()
            and timestamps.is_unique
            and timestamps.is_monotonic_increasing
            and timestamps.eq(timestamps.dt.floor("h")).all()
        )

    _log_check(
        f"{dataset_name} Hourly Continuity Check",
        valid_hours,
        "Timestamps are unique, ordered, exact UTC hours.",
        "Timestamps must be unique, ordered, exact UTC hours.",
        errors,
        log_results,
    )
    if valid_hours and len(missing_timestamps) and log_results:
        log_data_quality_result(
            f"{dataset_name} Missing Hour Coverage",
            "WARNING",
            f"{len(missing_timestamps)} hourly timestamps excluded; first="
            f"{missing_timestamps[0].isoformat()}, last="
            f"{missing_timestamps[-1].isoformat()}, later valid hours retained through "
            f"{valid_timestamps.max().isoformat()}.",
        )


def _validate_nuclear_shutdown_missingness(
    data: pd.DataFrame,
    errors: list[str],
    log_results: bool,
):
    if "timestamp" not in data.columns or "nuclear_mw" not in data.columns:
        return

    timestamps = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    unexpected_nulls = data["nuclear_mw"].isna() & (
        timestamps < NUCLEAR_SHUTDOWN_UTC
    )
    unexpected_timestamps = [
        timestamp.isoformat()
        for timestamp in timestamps[unexpected_nulls].dropna()
    ]
    _log_check(
        "ENTSO-E Silver Nuclear Availability Check",
        not unexpected_timestamps,
        (
            "Nuclear nulls occur only from Germany's local-time shutdown "
            "boundary onward."
        ),
        f"Unexpected pre-shutdown nuclear nulls: {unexpected_timestamps}",
        errors,
        log_results,
    )


def validate_silver_data(data: pd.DataFrame, log_results: bool = True) -> bool:
    if log_results:
        initialize_database()

    errors = []
    missing_columns = [
        column for column in SILVER_REQUIRED_COLUMNS
        if column not in data.columns
    ]

    _log_check(
        "ENTSO-E Silver Required Columns Check",
        not missing_columns,
        "All required silver columns are present.",
        f"Missing required silver columns: {missing_columns}",
        errors,
        log_results,
    )

    _validate_timestamp(data, "ENTSO-E Silver", errors, log_results, require_order=True)
    _validate_hourly_continuity(data, "ENTSO-E Silver", errors, log_results)

    duplicate_rows = int(data.duplicated().sum())
    _log_check(
        "ENTSO-E Silver Duplicate Rows Check",
        duplicate_rows == 0,
        "No duplicate rows found.",
        f"Silver dataset contains {duplicate_rows} duplicate rows.",
        errors,
        log_results,
    )

    available_essential_fields = [
        column for column in SILVER_ESSENTIAL_FORECASTING_FIELDS
        if column in data.columns
    ]
    null_counts = data[available_essential_fields].isna().sum()
    null_counts = {column: int(count) for column, count in null_counts.items() if count > 0}
    _log_check(
        "ENTSO-E Silver Essential Fields Null Check",
        not null_counts,
        "No nulls found in essential forecasting fields.",
        f"Nulls found in essential forecasting fields: {null_counts}",
        errors,
        log_results,
    )
    _validate_nuclear_shutdown_missingness(data, errors, log_results)

    numeric_columns = [
        column for column in SILVER_REQUIRED_COLUMNS
        if column != "timestamp"
    ]
    _validate_numeric_columns(
        data, numeric_columns, "ENTSO-E Silver", errors, log_results
    )

    _log_check(
        "ENTSO-E Silver Row Count Check",
        len(data) >= MIN_SILVER_ROWS,
        f"Silver dataset contains {len(data)} rows.",
        f"Silver dataset contains {len(data)} rows; at least {MIN_SILVER_ROWS} are required.",
        errors,
        log_results,
    )

    return len(errors) == 0


def validate_gold_data(data: pd.DataFrame, log_results: bool = True) -> bool:
    if log_results:
        initialize_database()

    errors = []
    required_columns = ["timestamp", *GOLD_MODEL_FEATURE_COLUMNS, GOLD_TARGET_COLUMN]
    missing_columns = [column for column in required_columns if column not in data.columns]

    _log_check(
        "ENTSO-E Gold Required Columns Check",
        not missing_columns,
        "The timestamp, target, and all required model features are present.",
        f"Missing required gold columns: {missing_columns}",
        errors,
        log_results,
    )

    _validate_timestamp(data, "ENTSO-E Gold", errors, log_results, require_order=True)

    duplicate_rows = int(data.duplicated().sum())
    _log_check(
        "ENTSO-E Gold Duplicate Rows Check",
        duplicate_rows == 0,
        "No duplicate rows found.",
        f"Gold dataset contains {duplicate_rows} duplicate rows.",
        errors,
        log_results,
    )

    available_model_columns = [
        column for column in [*GOLD_MODEL_FEATURE_COLUMNS, GOLD_TARGET_COLUMN]
        if column in data.columns
    ]
    null_counts = data[available_model_columns].isna().sum()
    null_counts = {column: int(count) for column, count in null_counts.items() if count > 0}
    _log_check(
        "ENTSO-E Gold Model Values Null Check",
        not null_counts,
        "No nulls found in model features or target.",
        f"Nulls found in model features or target: {null_counts}",
        errors,
        log_results,
    )

    _validate_numeric_columns(
        data,
        [*GOLD_MODEL_FEATURE_COLUMNS, GOLD_TARGET_COLUMN],
        "ENTSO-E Gold",
        errors,
        log_results,
    )

    split_index = int(len(data) * 0.8)
    training_rows = split_index
    testing_rows = len(data) - split_index
    enough_rows = (
        len(data) >= MIN_GOLD_ROWS
        and training_rows > 0
        and testing_rows >= 2
    )
    _log_check(
        "ENTSO-E Gold Chronological Split Check",
        enough_rows,
        f"Chronological split provides {training_rows} training and {testing_rows} testing rows.",
        (
            f"Gold dataset cannot support the existing chronological 80/20 split: "
            f"{training_rows} training and {testing_rows} testing rows."
        ),
        errors,
        log_results,
    )

    return len(errors) == 0


def validate_data(data: pd.DataFrame) -> bool:
    initialize_database()

    errors = []

    required_columns = [
        "timestamp",
        "market_price",
        "demand_mw",
        "supply_mw",
        "weather_temperature",
        "region",
        "energy_source",
        "hour",
        "day",
        "month",
        "day_of_week",
        "supply_demand_gap"
    ]

    for column in required_columns:
        if column not in data.columns:
            error_message = f"Missing required column: {column}"
            errors.append(error_message)
            log_data_quality_result("Required Columns Check", "FAILED", error_message)

    if "timestamp" in data.columns and data["timestamp"].isnull().any():
        error_message = "Timestamp column contains null values."
        errors.append(error_message)
        log_data_quality_result("Timestamp Null Check", "FAILED", error_message)
    else:
        log_data_quality_result("Timestamp Null Check", "PASSED", "No null timestamps found.")

    if "market_price" in data.columns and data["market_price"].isnull().any():
        error_message = "Market price column contains null values."
        errors.append(error_message)
        log_data_quality_result("Market Price Null Check", "FAILED", error_message)
    else:
        log_data_quality_result("Market Price Null Check", "PASSED", "No null market prices found.")

    if "market_price" in data.columns and (data["market_price"] < 0).any():
        error_message = "Market price contains negative values."
        errors.append(error_message)
        log_data_quality_result("Market Price Range Check", "FAILED", error_message)
    else:
        log_data_quality_result("Market Price Range Check", "PASSED", "No negative market prices found.")

    if "demand_mw" in data.columns and (data["demand_mw"] < 0).any():
        error_message = "Demand contains negative values."
        errors.append(error_message)
        log_data_quality_result("Demand Range Check", "FAILED", error_message)
    else:
        log_data_quality_result("Demand Range Check", "PASSED", "No negative demand values found.")

    if "supply_mw" in data.columns and (data["supply_mw"] < 0).any():
        error_message = "Supply contains negative values."
        errors.append(error_message)
        log_data_quality_result("Supply Range Check", "FAILED", error_message)
    else:
        log_data_quality_result("Supply Range Check", "PASSED", "No negative supply values found.")

    if data.duplicated().any():
        error_message = "Dataset contains duplicate rows."
        errors.append(error_message)
        log_data_quality_result("Duplicate Check", "FAILED", error_message)
    else:
        log_data_quality_result("Duplicate Check", "PASSED", "No duplicate records found.")

    VALIDATION_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(VALIDATION_REPORT_PATH, "w") as file:
        if errors:
            file.write("DATA VALIDATION FAILED\n\n")
            for error in errors:
                file.write(f"- {error}\n")
        else:
            file.write("DATA VALIDATION PASSED\n")
            file.write(f"Total records validated: {len(data)}\n")

    return len(errors) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate PowerFlow datasets.")
    parser.add_argument(
        "dataset",
        nargs="?",
        choices=["legacy", "silver", "gold"],
        default="legacy",
        help="Dataset to validate. Defaults to the existing legacy dataset.",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Run validation without writing data-quality results to SQLite.",
    )
    args = parser.parse_args()

    if args.dataset == "silver":
        df = pd.read_csv(SILVER_DATA_PATH, low_memory=False)
        result = validate_silver_data(df, log_results=not args.no_log)
        dataset_label = "ENTSO-E silver"
    elif args.dataset == "gold":
        df = pd.read_csv(GOLD_DATA_PATH, low_memory=False)
        result = validate_gold_data(df, log_results=not args.no_log)
        dataset_label = "ENTSO-E gold"
    else:
        clean_data_path = Path("data/processed/clean_electricity_market_data.csv")
        df = pd.read_csv(clean_data_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        result = validate_data(df)
        dataset_label = "Legacy"

    if result:
        print(f"{dataset_label} data validation passed.")
    else:
        print(f"{dataset_label} data validation failed.")
        raise SystemExit(1)

import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd


DATABASE_PATH = Path("database/electricity_trading.db")


def log_quality_result(check_name: str, status: str, message: str):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO data_quality_results
        (check_time, check_name, status, message)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            check_name,
            status,
            message,
        ),
    )

    connection.commit()
    connection.close()


def run_advanced_validation(data: pd.DataFrame) -> bool:
    errors = []

    required_columns = [
        "timestamp",
        "market_price",
        "demand_mw",
        "supply_mw",
        "weather_temperature",
        "region",
        "energy_source",
    ]

    for column in required_columns:
        if column not in data.columns:
            message = f"Missing required column: {column}"
            errors.append(message)
            log_quality_result("Schema Check", "FAILED", message)

    if errors:
        return False

    data = data.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"])

    if data["timestamp"].duplicated().any():
        message = "Duplicate timestamps detected."
        errors.append(message)
        log_quality_result("Duplicate Timestamp Check", "FAILED", message)
    else:
        log_quality_result("Duplicate Timestamp Check", "PASSED", "No duplicate timestamps found.")

    null_columns = data[required_columns].isnull().sum()
    null_columns = null_columns[null_columns > 0]

    if not null_columns.empty:
        message = f"Null values found: {null_columns.to_dict()}"
        errors.append(message)
        log_quality_result("Null Value Check", "FAILED", message)
    else:
        log_quality_result("Null Value Check", "PASSED", "No null values in required columns.")

    if (data["market_price"] < 0).any():
        message = "Negative market prices found."
        errors.append(message)
        log_quality_result("Market Price Range Check", "FAILED", message)
    else:
        log_quality_result("Market Price Range Check", "PASSED", "No negative market prices.")

    if (data["demand_mw"] < 0).any():
        message = "Negative demand values found."
        errors.append(message)
        log_quality_result("Demand Range Check", "FAILED", message)
    else:
        log_quality_result("Demand Range Check", "PASSED", "No negative demand values.")

    if (data["supply_mw"] < 0).any():
        message = "Negative supply values found."
        errors.append(message)
        log_quality_result("Supply Range Check", "FAILED", message)
    else:
        log_quality_result("Supply Range Check", "PASSED", "No negative supply values.")

    price_mean = data["market_price"].mean()
    price_std = data["market_price"].std()

    if price_std > 0:
        outliers = data[
            (data["market_price"] > price_mean + 3 * price_std)
            | (data["market_price"] < price_mean - 3 * price_std)
        ]

        if not outliers.empty:
            message = f"Extreme market price outliers detected: {len(outliers)} rows."
            errors.append(message)
            log_quality_result("Price Outlier Check", "FAILED", message)
        else:
            log_quality_result("Price Outlier Check", "PASSED", "No extreme price outliers detected.")

    latest_date = data["timestamp"].max()
    today = pd.Timestamp.today()
    days_old = (today - latest_date).days

    if days_old > 120:
        message = f"Data may be stale. Latest record is {days_old} days old."
        log_quality_result("Freshness Check", "WARNING", message)
    else:
        log_quality_result("Freshness Check", "PASSED", "Dataset is reasonably fresh.")

    total_checks = 7
    failed_checks = len(errors)
    quality_score = ((total_checks - failed_checks) / total_checks) * 100

    log_quality_result(
        "Overall Data Quality Score",
        "PASSED" if quality_score >= 80 else "FAILED",
        f"Data quality score: {quality_score:.2f}%",
    )

    return len(errors) == 0


if __name__ == "__main__":
    data_path = Path("data/raw/electricity_market_data.csv")
    df = pd.read_csv(data_path)

    result = run_advanced_validation(df)

    if result:
        print("Advanced validation passed.")
    else:
        print("Advanced validation failed.")
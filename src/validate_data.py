import pandas as pd
from pathlib import Path
from store_data import initialize_database, log_data_quality_result


VALIDATION_REPORT_PATH = Path("data/reports/validation_report.txt")


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
    clean_data_path = Path("data/processed/clean_electricity_market_data.csv")

    df = pd.read_csv(clean_data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    result = validate_data(df)

    if result:
        print("Data validation passed.")
    else:
        print("Data validation failed.")
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime


DATABASE_PATH = Path("database/electricity_trading.db")
SCHEMA_PATH = Path("database/schema.sql")


def initialize_database():
    connection = sqlite3.connect(DATABASE_PATH)

    with open(SCHEMA_PATH, "r") as schema_file:
        schema = schema_file.read()

    connection.executescript(schema)
    connection.commit()
    connection.close()


def store_clean_data(data: pd.DataFrame):
    connection = sqlite3.connect(DATABASE_PATH)

    data.to_sql(
        "clean_market_data",
        connection,
        if_exists="replace",
        index=False
    )

    connection.close()


def log_pipeline_run(status: str, records_processed: int, message: str):
    connection = sqlite3.connect(DATABASE_PATH)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO pipeline_runs
        (run_time, status, records_processed, message)
        VALUES (?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status,
            records_processed,
            message
        )
    )

    connection.commit()
    connection.close()


def log_data_quality_result(check_name: str, status: str, message: str):
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
            message
        )
    )

    connection.commit()
    connection.close()
import sqlite3
import pandas as pd
from pathlib import Path


DATABASE_PATH = Path("database/electricity_trading.db")


def check_pipeline_runs():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM pipeline_runs
    ORDER BY run_time DESC
    LIMIT 10
    """

    data = pd.read_sql_query(query, connection)
    connection.close()

    return data


def check_data_quality_results():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM data_quality_results
    ORDER BY check_time DESC
    LIMIT 20
    """

    data = pd.read_sql_query(query, connection)
    connection.close()

    return data


if __name__ == "__main__":
    print("\nLATEST PIPELINE RUNS")
    print(check_pipeline_runs())

    print("\nLATEST DATA QUALITY RESULTS")
    print(check_data_quality_results())
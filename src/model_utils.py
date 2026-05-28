import sqlite3
import pandas as pd
from pathlib import Path


DATABASE_PATH = Path("database/electricity_trading.db")


def get_model_registry():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM model_registry
    ORDER BY training_date DESC
    """

    data = pd.read_sql_query(query, connection)

    connection.close()

    return data


def get_predictions():
    connection = sqlite3.connect(DATABASE_PATH)

    query = """
    SELECT *
    FROM predictions
    ORDER BY prediction_time DESC
    """

    data = pd.read_sql_query(query, connection)

    connection.close()

    return data


if __name__ == "__main__":
    print("\nMODEL REGISTRY")
    print(get_model_registry())

    print("\nPREDICTIONS")
    print(get_predictions())
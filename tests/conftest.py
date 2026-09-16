from pathlib import Path

import pytest

import store_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def temporary_database(tmp_path, monkeypatch):
    database_path = tmp_path / "electricity_trading_test.db"
    schema_path = PROJECT_ROOT / "database" / "schema.sql"

    monkeypatch.setattr(store_data, "DATABASE_PATH", database_path)
    monkeypatch.setattr(store_data, "SCHEMA_PATH", schema_path)
    store_data.initialize_database()

    return database_path

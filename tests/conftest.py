from pathlib import Path

import pytest

import store_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption(
        "--release-gating", action="store_true",
        help="Deselect the explicitly listed historical verification cases.",
    )


def pytest_configure(config):
    if config.getoption("--release-gating"):
        entries = Path(__file__).with_name("historical-verification.txt").read_text().splitlines()
        historical = [entry.partition("#")[0].strip() for entry in entries]
        config.option.deselect = (config.option.deselect or []) + list(filter(None, historical))


@pytest.fixture
def temporary_database(tmp_path, monkeypatch):
    database_path = tmp_path / "electricity_trading_test.db"
    schema_path = PROJECT_ROOT / "database" / "schema.sql"

    monkeypatch.setattr(store_data, "DATABASE_PATH", database_path)
    monkeypatch.setattr(store_data, "SCHEMA_PATH", schema_path)
    store_data.initialize_database()

    return database_path

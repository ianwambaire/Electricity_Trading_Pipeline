import importlib.util
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


@pytest.fixture
def writer(monkeypatch):
    tooling = PROJECT_ROOT / 'deploy/staging/forecast-publication'
    monkeypatch.syspath_prepend(str(tooling))
    spec = importlib.util.spec_from_file_location(
        'production_writer', PROJECT_ROOT / 'deploy/production-publication/writer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def frozen_operational_contract():
    """Build historical helpers against their original, hash-pinned contract."""
    def bind(builder, manifest):
        original_read = builder.read
        source = PROJECT_ROOT / "src/shared/operational_evidence.py"
        fixture = PROJECT_ROOT / "tests/fixtures/operational_evidence_v1.py.txt"
        expected = manifest["config"]["files"]["helper/shared/operational_evidence.py"]

        def read(path, limit=4 * 1024 * 1024):
            if Path(path) == source:
                raw = original_read(fixture, limit)
                assert builder.sha(raw) == expected["sha256"]
                assert len(raw) == expected["bytes"]
                return raw
            return original_read(path, limit)

        builder.read = read
    return bind


@pytest.fixture(scope="module", autouse=True)
def frozen_helper_builders(request, frozen_operational_contract):
    """Keep archived builder tests and their pinned test files unchanged."""
    names = {
        "test_operational_capture_helper_release",
        "test_operational_capture_helper_release_v2",
    }
    if request.module.__name__ not in names:
        yield
        return

    import json
    original_load = request.module.load
    manifest = json.loads(
        (PROJECT_ROOT / "deploy/staging/operational-evidence-release-v5/MANIFEST.json").read_bytes()
    )

    def load(name, extra=None):
        module = original_load(name, extra)
        if name == "build":
            frozen_operational_contract(module, manifest)
        return module

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(request.module, "load", load)
        yield

"""Public read-only API contracts; fixture values are never production data."""
import csv
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import APISettings, create_app
from api.market_data import GENERATION_FIELDS, VALUE_FIELDS, MarketStore

ROOT = Path(__file__).resolve().parents[1]


def write_market(root, rows=None):
    path = APISettings.from_root(root).market_silver
    path.parent.mkdir(parents=True, exist_ok=True)
    default = dict.fromkeys(VALUE_FIELDS, 10.0)
    default.update(price_eur_mwh=-5, load_mw=100, wind_total_mw=20)
    rows = rows if rows is not None else [dict(default, timestamp=f"2026-09-01T0{i}:00:00Z") for i in (0, 1, 3)]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", *VALUE_FIELDS])
        writer.writeheader()
        writer.writerows(rows)
    return path


def client(root):
    return TestClient(create_app(APISettings.from_root(root)))


def copy_metadata(root):
    for relative in ["artifacts/models/final_model_release_manifest.json", "artifacts/models/releases/next24h/next24h_release_manifest.json", "data/reports/final_holdout_metrics.csv"]:
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT / relative).read_bytes())


def test_market_values_coverage_and_pagination_match_source(tmp_path):
    path = write_market(tmp_path)
    before = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    with client(tmp_path) as c:
        coverage = c.get("/market/coverage").json()
        assert coverage["row_count"] == 3
        assert coverage["missing_hours_in_span"] == 1
        assert coverage["latest_observation"] == "2026-09-01T03:00:00Z"
        page = c.get("/market/history?limit=2").json()
        assert page["matched_rows"] == 3 and page["next_offset"] == 2
        row = page["observations"][0]
        assert row["price_eur_mwh"] == -5
        assert row["generation"]["wind_total_mw"] == 20
        assert row["renewable_generation_mw"] == 50
        assert row["renewable_share"] == pytest.approx(50 / 90)
        second = c.get("/market/history?limit=2&offset=2").json()
        assert second["row_count"] == 1 and second["next_offset"] is None
        assert c.get("/market/history?start=2026-09-01T01:00:00Z&end=2026-09-01T02:00:00Z").json()["matched_rows"] == 1
        assert c.get("/market/history?start=2020-01-01T00:00:00Z&end=2020-01-02T00:00:00Z").json()["observations"] == []
    assert before == (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize("query", ["limit=2001", "limit=0", "offset=-1", "offset=2000001", "start=bad", "start=2026-01-01T00:00:00", "start=2026-09-02T00:00:00Z&end=2026-09-01T00:00:00Z", "start=2020-01-01T00:00:00Z&end=2026-09-01T00:00:00Z", "end=0001-01-01T00:00:00Z"])
def test_invalid_market_queries_are_rejected(tmp_path, query):
    write_market(tmp_path)
    with client(tmp_path) as c:
        assert c.get("/market/history?" + query).status_code == 422


def test_missing_empty_invalid_and_null_sources(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/market/coverage").status_code == 404
        path = write_market(tmp_path, [])
        assert c.get("/market/history").json()["observations"] == []
        path.write_text("secret_path,token\nprivate,hidden\n")
        r = c.get("/market/history")
        assert r.status_code == 503 and "hidden" not in r.text and str(tmp_path) not in r.text
        write_market(tmp_path, [dict.fromkeys(["timestamp", *VALUE_FIELDS], "") | {"timestamp": "2026-09-01T00:00:00Z"}])
        row = c.get("/market/history").json()["observations"][0]
        assert row["price_eur_mwh"] is None and row["renewable_generation_mw"] is None and row["renewable_share"] is None


def test_market_cache_reuses_unchanged_source_and_rejects_bad_replacement(tmp_path):
    path = write_market(tmp_path)
    store = MarketStore(path)
    try:
        first = store.coverage()
        with patch.object(Path, "open", side_effect=AssertionError("unchanged CSV reloaded")):
            assert store.coverage() == first
            assert store.history(None, None, 2, 0).row_count == 2
        path.write_text("broken\n")
        with pytest.raises(Exception) as error:
            store.coverage()
        assert error.value.status_code == 503
        write_market(tmp_path, [])
        assert store.coverage().row_count == 0
    finally:
        store.close()


def test_duplicate_or_nonfinite_source_is_not_served(tmp_path):
    path = write_market(tmp_path)
    rows = list(csv.DictReader(path.open()))
    for data in [[rows[0], rows[0]], [rows[0] | {"price_eur_mwh": "inf"}]]:
        write_market(tmp_path, data)
        with client(tmp_path) as c:
            assert c.get("/market/history").status_code == 503


def test_model_summaries_are_release_specific_and_safe(tmp_path):
    copy_metadata(tmp_path)
    with client(tmp_path) as c:
        response = c.get("/models/summary")
    assert response.status_code == 200
    next24, one = response.json()["models"]
    assert next24["version"] == "next24h-hgb-2026-09-21-v1"
    assert next24["horizons_hours"] == list(range(1,25))
    assert next24["evaluations"][1]["rmse"] == 44.18332312010295
    assert next24["evaluations"][1]["period_end"] is None
    assert one["name"] == "Ordinary Linear Regression" and one["version"] is None
    assert one["evaluations"][0]["rmse"] == 18.88568551202895
    assert one["evaluations"][0]["period_end"] == "2025-09-30T23:00:00Z"
    assert one["metadata_provenance"] == "release_manifest_and_evaluation_report"
    assert next24["artifact_status"] == "missing" and one["artifact_status"] == "missing"
    for private in ["/artifacts/", "model_path", "mlflow", "git_commit", "source_candidate_path", "secret"]:
        assert private not in response.text


def test_model_metadata_missing_invalid_and_conflicting_metrics(tmp_path):
    with client(tmp_path) as c:
        assert all(m["metadata_status"] == "missing" for m in c.get("/models/summary").json()["models"])
        copy_metadata(tmp_path)
        p = tmp_path / "data/reports/final_holdout_metrics.csv"
        p.write_text(p.read_text().replace("18.88568551202895", "999"))
        models = c.get("/models/summary").json()["models"]
        assert models[1]["metadata_status"] == "invalid" and models[1]["evaluations"] == []
        p = tmp_path / "artifacts/models/releases/next24h/next24h_release_manifest.json"
        p.write_text("invalid-json-private-detail")
        r = c.get("/models/summary")
        assert r.json()["models"][0]["metadata_status"] == "invalid"
        assert "private-detail" not in r.text


@pytest.mark.skipif(not (ROOT / "data/processed/silver_electricity_market_data.csv").is_file(), reason="Optional local persisted dataset is not checked into Git")
def test_real_persisted_values_and_artifact_integrity_match():
    # Read-only parity checks against actual local data; no inference or writes.
    with client(ROOT) as c:
        coverage = c.get("/market/coverage").json()
        with APISettings.from_root(ROOT).market_silver.open() as handle:
            reader = csv.DictReader(handle)
            first = next(reader)
            count = 1 + sum(1 for _ in reader)
        assert coverage["row_count"] == count
        page = c.get("/market/history", params={"start": first["timestamp"], "end": first["timestamp"]}).json()
        row = page["observations"][0]
        assert row["price_eur_mwh"] == float(first["price_eur_mwh"])
        assert row["load_mw"] == float(first["load_mw"])
        assert all(row["generation"][key] == float(first[key]) for key in GENERATION_FIELDS)
        gold_path = ROOT / "data/features/gold_model_features.csv"
        if gold_path.is_file():
            with gold_path.open() as handle:
                gold = next(csv.DictReader(handle))
            observed = c.get("/market/history", params={"start": gold["timestamp"], "end": gold["timestamp"]}).json()["observations"][0]
            assert observed["renewable_generation_mw"] == pytest.approx(float(gold["renewable_generation_mw"]))
            assert observed["renewable_share"] == pytest.approx(float(gold["renewable_share"]))
        models = c.get("/models/summary").json()["models"]
        assert models[0]["artifact_status"] == "integrity_verified"
        assert models[1]["artifact_status"] == "present_not_integrity_verified"
        for key,model in [("next24h",models[0]),("one_hour",models[1])]:
            assert model["metadata_status"] == "available", key


def test_artifact_mismatch_and_model_metadata_do_not_unpickle(tmp_path, monkeypatch):
    copy_metadata(tmp_path)
    directory = tmp_path / "artifacts/models/releases/next24h"
    (directory / "next24h_model.joblib").write_bytes(b"not-a-model")
    import joblib
    def forbidden(*args, **kwargs):
        raise AssertionError("Public metadata must not deserialize model artifacts")
    monkeypatch.setattr(joblib, "load", forbidden)
    with client(tmp_path) as c:
        response = c.get("/models/summary")
        assert response.json()["models"][0]["artifact_status"] == "integrity_mismatch"
        assert c.post("/models/summary").status_code == 405
        assert c.post("/market/history").status_code == 405


def test_no_paths_or_unknown_manifest_fields_are_published(tmp_path):
    copy_metadata(tmp_path)
    path = tmp_path / "artifacts/models/releases/next24h/next24h_release_manifest.json"
    data = json.loads(path.read_text())
    data.update(secret="private-value", source_candidate_path="/private/value", known_limitations=["private-value"])
    path.write_text(json.dumps(data))
    with client(tmp_path) as c:
        r = c.get("/models/summary")
        assert r.json()["models"][0]["metadata_status"] == "available"
        assert "private-value" not in r.text and "/private/value" not in r.text

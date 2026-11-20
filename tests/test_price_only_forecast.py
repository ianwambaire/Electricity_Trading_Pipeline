from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from api.app import APISettings, create_app
from api.forecast_source import PublicationSelection
from shared.price_only_forecast import MODEL_RELEASE, build, load


def test_fallback_uses_complete_elapsed_prices_and_expires(tmp_path):
    issue = datetime(2026, 11, 12, 13, tzinfo=timezone.utc)
    now = issue + timedelta(minutes=5)
    timestamps = pd.date_range(issue - timedelta(days=14), periods=14 * 96 + 4, freq="15min")
    prices = pd.DataFrame({
        "timestamp": timestamps,
        "price_eur_mwh": [t.hour if t < issue else 1000 for t in timestamps],
        "source_resolution": "PT15M",
    })
    source = tmp_path / "prices.csv"
    prices.to_csv(source, index=False)

    report = build(source, now)
    expected = [float((issue.hour + horizon) % 24) for horizon in range(1, 25)]
    assert report["values"] == expected
    assert datetime.fromisoformat(report["latest_price_hour"]) == issue - timedelta(hours=1)

    snapshot = tmp_path / "forecast.json"
    snapshot.write_text(json.dumps(report))
    assert load(snapshot, now) == (issue, now, now + timedelta(minutes=15), expected)
    assert load(snapshot, now + timedelta(minutes=15)) is None

    before_rollover = issue + timedelta(minutes=55)
    snapshot.write_text(json.dumps(build(source, before_rollover)))
    after_rollover = issue + timedelta(hours=1, seconds=2)
    assert load(snapshot, after_rollover) == (
        issue, before_rollover, before_rollover + timedelta(minutes=15), expected
    )
    assert load(snapshot, before_rollover + timedelta(minutes=15)) is None

    prices.loc[prices.timestamp < issue - timedelta(hours=4)].to_csv(source, index=False)
    assert build(source, now) is None


@pytest.mark.parametrize("status,enabled,expected", [
    ("MISSING_PUBLICATION", True, 200),
    ("EXPIRED", True, 200),
    ("WITHHELD", True, 503),
    ("MISSING_PUBLICATION", False, 503),
])
def test_api_fallback_respects_primary_status(tmp_path, monkeypatch, status, enabled, expected):
    now = datetime(2026, 11, 12, 14, 2, tzinfo=timezone.utc)
    issue = now.replace(minute=0) - timedelta(hours=1)
    completed = issue + timedelta(minutes=55)
    snapshot = tmp_path / "current.json"
    snapshot.write_text(json.dumps({
        "issue_time": issue.isoformat(),
        "completed_at": completed.isoformat(),
        "latest_price_hour": (issue - timedelta(hours=1)).isoformat(),
        "values": list(range(24)),
    }))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("api.app.select_publication", lambda _: PublicationSelection(status))
    monkeypatch.setenv("POWERFLOW_PRICE_ONLY_FALLBACK", "true" if enabled else "false")
    monkeypatch.setenv("POWERFLOW_PRICE_ONLY_FALLBACK_PATH", str(snapshot))
    settings = replace(APISettings.from_root(tmp_path), next24_publication_root=tmp_path / "primary")
    app = create_app(settings)
    monkeypatch.setattr("api.app.datetime", Clock)
    with TestClient(app) as client:
        response = client.get("/forecast/next24")
        assert response.status_code == expected
        assert "no-store" in response.headers["Cache-Control"]
        if expected == 200:
            payload = response.json()
            assert payload["row_count"] == 24
            assert all(row["model_release"] == MODEL_RELEASE for row in payload["forecasts"])
            assert payload["publication"]["availability_policy"] == "PRICE_ONLY_FALLBACK_V1"
            assert datetime.fromisoformat(payload["publication"]["expires_at"]) == completed + timedelta(minutes=15)
            now = completed + timedelta(minutes=15)
            assert client.get("/forecast/next24").status_code == 503


def cached_prices(tmp_path, issue):
    timestamps = pd.date_range(issue - timedelta(days=14), periods=14 * 96, freq="15min")
    path = tmp_path / "prices.csv"
    pd.DataFrame({
        "timestamp": timestamps,
        "price_eur_mwh": [float(t.hour) for t in timestamps],
        "source_resolution": "PT15M",
    }).to_csv(path, index=False)
    return path


def test_cached_history_keeps_future_targets_during_extended_source_outage(tmp_path):
    from shared.price_only_forecast import build_cached_history, read_snapshot
    end = datetime(2026, 11, 12, 13, tzinfo=timezone.utc)
    generated = end + timedelta(days=3, minutes=5)
    report = build_cached_history(cached_prices(tmp_path, end), generated)
    snapshot = tmp_path / "current.json"
    snapshot.write_text(json.dumps(report))
    for now in (generated, generated + timedelta(days=30, hours=7)):
        result = read_snapshot(snapshot, now)
        issue, completed, expiry, values = result["forecast"]
        assert issue == now.replace(minute=0, second=0, microsecond=0)
        assert completed == now
        assert expiry == issue + timedelta(hours=1)
        assert values == [float((issue.hour + h) % 24) for h in range(1, 25)]
        assert all(issue + timedelta(hours=h) > now for h in range(1, 25))
        assert result["source_latest_at"] == end
        assert result["source_snapshot_at"] == generated
        assert result["source_age_seconds"] == (now - end).total_seconds()


@pytest.mark.parametrize("mutation", ["nan", "future", "source_future", "digest", "short", "samples"])
def test_cached_history_rejects_invalid_statistics(tmp_path, mutation):
    from shared.price_only_forecast import build_cached_history, read_snapshot
    now = datetime(2026, 11, 12, 13, 5, tzinfo=timezone.utc)
    report = build_cached_history(cached_prices(tmp_path, now.replace(minute=0)), now)
    if mutation == "nan":
        report["hourly_medians"][0] = float("nan")
    elif mutation == "future":
        report["calculated_at"] = (now + timedelta(seconds=1)).isoformat()
    elif mutation == "source_future":
        report["latest_price_hour"] = now.replace(minute=0).isoformat()
    elif mutation == "digest":
        report["source_sha256"] = "invalid"
    elif mutation == "short":
        report["hourly_medians"].pop()
    else:
        report["minimum_hour_samples"] = 0
    snapshot = tmp_path / "current.json"
    snapshot.write_text(json.dumps(report))
    assert read_snapshot(snapshot, now) is None


@pytest.mark.parametrize("status", ["MISSING_PUBLICATION", "EXPIRED", "WITHHELD", "VALID"])
def test_api_serves_labelled_latest_history_forecast(tmp_path, monkeypatch, status):
    from shared.price_only_forecast import build_cached_history
    now = datetime(2026, 11, 20, 14, 5, tzinfo=timezone.utc)
    source_end = now.replace(minute=0) - timedelta(days=2)
    snapshot = tmp_path / "current.json"
    snapshot.write_text(json.dumps(build_cached_history(cached_prices(tmp_path, source_end), now)))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    primary = {"forecasts": [{"target_time": (now - timedelta(hours=1)).isoformat()}]} if status == "VALID" else None
    monkeypatch.setattr("api.app.select_publication", lambda _: PublicationSelection(status, primary))
    settings = replace(APISettings.from_root(tmp_path),
                       next24_publication_root=tmp_path / "primary",
                       price_only_fallback_path=snapshot)
    app = create_app(settings)
    monkeypatch.setattr("api.app.datetime", Clock)
    with TestClient(app) as client:
        response = client.get("/forecast/next24")
        assert response.status_code == 200
        result = response.json()
        assert result["publication"]["availability_policy"] == "LATEST_PRICE_HISTORY_V1"
        assert datetime.fromisoformat(result["publication"]["source_latest_at"]) == source_end
        assert result["publication"]["source_age_seconds"] == (now - source_end).total_seconds()
        assert result["row_count"] == 24
        assert all(datetime.fromisoformat(row["target_time"]) > now for row in result["forecasts"])


def test_publisher_caches_fallback_independently_of_primary_freshness(tmp_path, monkeypatch, writer):
    from shared.price_only_forecast import read_snapshot
    now = datetime(2026, 11, 20, 14, 5, tzinfo=timezone.utc)
    source = cached_prices(tmp_path, now.replace(minute=0) - timedelta(days=2))
    root = tmp_path.resolve() / "published"
    root.mkdir()
    monkeypatch.setattr(writer, "read_input", lambda *_: source.read_bytes())
    monkeypatch.setattr(writer, "utcnow", lambda: now)
    assert writer.publish_fallback(tmp_path, root, 1000) == "UPDATED"
    assert read_snapshot(root / "fallback/current.json", now) is not None
    assert not (root / "forecast/current").exists()
    previous = (root / "fallback/current.json").read_bytes()
    monkeypatch.setattr(writer.price_only_forecast, "build_cached_history", lambda *_: None)
    assert writer.publish_fallback(tmp_path, root, 1000) == "NO_USABLE_HISTORY"
    assert (root / "fallback/current.json").read_bytes() == previous


def test_primary_forecast_with_24_future_hours_takes_precedence(tmp_path, monkeypatch):
    from shared.price_only_forecast import build_cached_history
    from test_forecast_publication import fixture as primary_fixture
    primary = primary_fixture()
    issue = datetime.fromisoformat(primary["forecasts"][0]["issue_time"].replace("Z", "+00:00"))
    now = issue + timedelta(minutes=30)
    snapshot = tmp_path / "current.json"
    snapshot.write_text(json.dumps(build_cached_history(cached_prices(tmp_path, issue), now)))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr("api.app.select_publication", lambda _: PublicationSelection("VALID", primary))
    settings = replace(APISettings.from_root(tmp_path),
                       next24_publication_root=tmp_path / "primary",
                       price_only_fallback_path=snapshot)
    app = create_app(settings)
    monkeypatch.setattr("api.app.datetime", Clock)
    with TestClient(app) as client:
        response = client.get("/forecast/next24")
        assert response.status_code == 200
        result = response.json()
        assert result["publication"]["availability_policy"] == "ISSUE_HORIZON_V1"
        assert len(result["forecasts"]) == 24
        for actual, expected in zip(result["forecasts"], primary["forecasts"]):
            assert actual["predicted_price_eur_mwh"] == expected["predicted_price_eur_mwh"]
            assert actual["model_release"] == expected["model_release"]
            assert datetime.fromisoformat(actual["target_time"].replace("Z", "+00:00")) == datetime.fromisoformat(expected["target_time"])


@pytest.mark.parametrize("path", [
    None,
    "/srv/powerflow/production-published/fallback/current.json",
    "/srv/powerflow/production-published/fallback/other.json",
    "/srv/powerflow/price-only-forecast/current.json",
    "/tmp/fallback/current.json",
    "/srv/powerflow/production-published/fallback/../other/current.json",
    "fallback/current.json",
])
def test_normal_production_entry_point_allows_only_isolated_fallback(monkeypatch, path):
    from api.security import SecuritySettings
    from api.runtime import RuntimeSettings
    monkeypatch.setenv("POWERFLOW_API_DATA_ROOT", "/srv/powerflow/production-published/data/current")
    monkeypatch.setenv("POWERFLOW_FORECAST_PUBLICATION_ROOT", "/srv/powerflow/production-published/forecast")
    monkeypatch.setenv("POWERFLOW_OPERATIONAL_PUBLICATION_ROOT", "/srv/powerflow/production-published/operations")
    monkeypatch.setenv("POWERFLOW_REALIZED_REPORT_ROOT", "/srv/powerflow/production-published/realized")
    monkeypatch.setenv("POWERFLOW_PRICE_ONLY_FALLBACK", "true" if path else "false")
    if path:
        monkeypatch.setenv("POWERFLOW_PRICE_ONLY_FALLBACK_PATH", path)
    else:
        monkeypatch.delenv("POWERFLOW_PRICE_ONLY_FALLBACK_PATH", raising=False)
    arguments = dict(
        security_settings=SecuritySettings(
            "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Fixture",
            frozenset({"fixtureclient"}),
        ),
        runtime_settings=RuntimeSettings("production", ("testserver",)),
    )
    if path not in (None, "/srv/powerflow/production-published/fallback/current.json"):
        with pytest.raises(ValueError, match="Production publication"):
            create_app(**arguments)
    else:
        with TestClient(create_app(**arguments)) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/auth/me").status_code == 401

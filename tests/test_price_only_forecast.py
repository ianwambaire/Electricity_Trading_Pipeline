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

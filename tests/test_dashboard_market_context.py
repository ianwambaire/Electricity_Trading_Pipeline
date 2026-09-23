import pandas as pd
import pytest

from dashboard_data import (
    MODEL_INPUT_CONTEXT_NOTE,
    build_market_context,
    build_model_input_context,
)


def _silver(periods=168):
    timestamps = pd.date_range("2026-09-01", periods=periods, freq="h", tz="UTC")
    steps = pd.Series(range(periods), dtype="float64")
    return pd.DataFrame({
        "timestamp": timestamps,
        "price_eur_mwh": steps + 10.0,
        "load_mw": steps + 40_000.0,
        "biomass_mw": 1_000.0,
        "lignite_mw": 5_000.0,
        "gas_mw": 4_000.0,
        "hard_coal_mw": 3_000.0,
        "hydro_mw": 2_000.0,
        "nuclear_mw": 0.0,
        "solar_mw": 3_000.0,
        "wind_total_mw": 4_000.0,
        "temperature_2m": 15.0,
        "relative_humidity_2m": 70.0,
        "wind_speed_10m": 12.0,
        "cloud_cover": 40.0,
        "shortwave_radiation": 120.0,
    })


def _forecast(issue, prices=None):
    prices = prices or list(range(1, 25))
    return pd.DataFrame({
        "forecast_issue_time": [issue] * 24,
        "target_timestamp": [issue + pd.Timedelta(hours=hour) for hour in range(1, 25)],
        "horizon_hours": list(range(1, 25)),
        "predicted_price_eur_mwh": prices,
        "model_release": ["next24h-test"] * 24,
    })


def test_market_context_separates_observed_and_forecast_metrics():
    silver = _silver()
    issue = silver["timestamp"].iloc[-1]
    prices = [-5.0, 250.0] + [50.0] * 22

    context = build_market_context(
        silver,
        _forecast(issue, prices),
        now=issue + pd.Timedelta(hours=2),
    )

    observed = context["observed"]
    forecast = context["forecast"]
    assert observed["timestamp"] == issue
    assert observed["price_eur_mwh"] == pytest.approx(177.0)
    assert observed["load_mw"] == pytest.approx(40_167.0)
    assert observed["renewable_generation_mw"] == pytest.approx(10_000.0)
    assert observed["renewable_share"] == pytest.approx(10 / 22)
    assert observed["temperature_2m"] == pytest.approx(15.0)
    assert forecast["average"] == pytest.approx(sum(prices) / 24)
    assert forecast["minimum"] == -5.0
    assert forecast["minimum_time"] == issue + pd.Timedelta(hours=1)
    assert forecast["maximum"] == 250.0
    assert forecast["maximum_time"] == issue + pd.Timedelta(hours=2)
    assert forecast["negative_hours"] == 1
    assert forecast["elevated_hours"] == 1
    assert forecast["forward_looking_rows"] == 22


def test_market_context_exact_observed_averages_and_utc_conversion():
    silver = _silver()
    silver["timestamp"] = silver["timestamp"].dt.tz_convert("Europe/Berlin")
    issue = pd.Timestamp(silver["timestamp"].iloc[-1]).tz_convert("UTC")

    context = build_market_context(silver, _forecast(issue), now=issue)

    assert context["observed"]["timestamp"].tzname() == "UTC"
    assert context["observed"]["previous_24h_price_average"] == pytest.approx(
        silver["price_eur_mwh"].tail(24).mean()
    )
    assert context["observed"]["seven_day_price_average"] == pytest.approx(
        silver["price_eur_mwh"].mean()
    )


def test_market_context_does_not_average_across_missing_hour():
    silver = _silver().drop(index=100).reset_index(drop=True)
    issue = silver["timestamp"].iloc[-1]

    context = build_market_context(silver, _forecast(issue), now=issue)

    assert context["observed"]["previous_24h_price_average"] is not None
    assert context["observed"]["seven_day_price_average"] is None


def test_market_context_empty_and_missing_values_are_safe():
    empty = build_market_context(pd.DataFrame(), pd.DataFrame())
    assert empty["observed"]["price_eur_mwh"] is None
    assert empty["forecast"]["status"] == "Unavailable"
    assert empty["forecast"]["rows"] == 0

    silver = _silver()
    silver.loc[silver.index[-1], "temperature_2m"] = float("nan")
    silver.loc[silver.index[-1], "solar_mw"] = float("nan")
    issue = silver["timestamp"].iloc[-1]
    context = build_market_context(silver, _forecast(issue), now=issue)
    assert context["observed"]["temperature_2m"] is None
    assert context["observed"]["renewable_generation_mw"] is None
    assert context["observed"]["renewable_share"] is None


def test_stale_forecast_is_retained_and_clearly_marked():
    silver = _silver()
    issue = silver["timestamp"].iloc[-1]
    context = build_market_context(
        silver,
        _forecast(issue),
        now=issue + pd.Timedelta(hours=4),
        maximum_age_hours=3,
    )
    assert context["forecast"]["status"] == "Stale"
    assert context["forecast"]["is_stale"] is True
    assert context["forecast"]["rows"] == 24


def test_model_input_context_requires_exact_issue_hour_and_continuous_windows():
    silver = _silver()
    issue = silver["timestamp"].iloc[-1]

    context = build_model_input_context(silver, issue)

    assert context["available"] is True
    assert context["issue_time"].tzname() == "UTC"
    assert context["load_mw"] == pytest.approx(40_167.0)
    assert context["wind_total_mw"] == pytest.approx(4_000.0)
    assert context["solar_mw"] == pytest.approx(3_000.0)
    assert context["renewable_share"] == pytest.approx(10 / 22)
    assert context["price_rolling_mean_24h"] == pytest.approx(
        silver["price_eur_mwh"].tail(24).mean()
    )
    assert context["price_rolling_std_24h"] == pytest.approx(
        silver["price_eur_mwh"].tail(24).std()
    )
    assert context["price_average_7d"] == pytest.approx(
        silver["price_eur_mwh"].mean()
    )
    assert context["temperature_2m"] == 15.0

    missing_issue = build_model_input_context(
        silver,
        issue + pd.Timedelta(hours=1),
    )
    assert missing_issue["available"] is False
    assert missing_issue["load_mw"] is None


def test_model_input_context_marks_broken_rolling_history_unavailable():
    silver = _silver().drop(index=160).reset_index(drop=True)
    issue = silver["timestamp"].iloc[-1]
    context = build_model_input_context(silver, issue)
    assert context["available"] is True
    assert context["price_rolling_mean_24h"] is None
    assert context["price_rolling_std_24h"] is None
    assert context["price_average_7d"] is None


def test_context_wording_is_descriptive_not_causal():
    assert "not causal explanations" in MODEL_INPUT_CONTEXT_NOTE
    assert "caused by" not in MODEL_INPUT_CONTEXT_NOTE.lower()
    assert "driven by" not in MODEL_INPUT_CONTEXT_NOTE.lower()

"""Observed market context; no UI, file cache or inference side effects."""
import math
import pandas as pd
from processing.build_silver_dataset import aggregate_hourly_prices

def _utc_timestamp(value) -> pd.Timestamp | None:
    if value is None or pd.isna(value):
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return (
        timestamp.tz_localize("UTC")
        if timestamp.tzinfo is None
        else timestamp.tz_convert("UTC")
    )

def _finite_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

def _prepare_observed_market(data: pd.DataFrame) -> pd.DataFrame:
    """Return a UTC-indexed, read-only view of trusted observed market rows."""
    if data.empty or "timestamp" not in data:
        return pd.DataFrame()
    prepared = data.copy()
    prepared["timestamp"] = pd.to_datetime(
        prepared["timestamp"], errors="coerce", utc=True
    )
    return (
        prepared.dropna(subset=["timestamp"])
        .sort_values("timestamp", kind="stable")
        .drop_duplicates("timestamp", keep="last")
        .set_index("timestamp", drop=False)
    )

def _exact_hourly_stat(
    data: pd.DataFrame,
    column: str,
    end: pd.Timestamp | None,
    hours: int,
    statistic: str = "mean",
) -> float | None:
    if data.empty or column not in data or end is None:
        return None
    required = pd.date_range(end=end, periods=hours, freq="h", tz="UTC")
    values = pd.to_numeric(data[column], errors="coerce").reindex(required)
    if values.isna().any():
        return None
    result = values.mean() if statistic == "mean" else values.std()
    return _finite_number(result)

def _renewable_metrics(row: pd.Series) -> tuple[float | None, float | None]:
    renewable_columns = ("solar_mw", "wind_total_mw", "biomass_mw", "hydro_mw")
    conventional_columns = ("lignite_mw", "gas_mw", "hard_coal_mw")
    renewables = [_finite_number(row.get(column)) for column in renewable_columns]
    conventional = [_finite_number(row.get(column)) for column in conventional_columns]
    if any(value is None for value in renewables + conventional):
        return None, None
    renewable_generation = sum(renewables)
    nuclear = _finite_number(row.get("nuclear_mw")) or 0.0
    denominator = renewable_generation + sum(conventional) + nuclear
    share = renewable_generation / denominator if denominator > 0 else None
    return renewable_generation, share

def summarize_clean_price_history(prices: pd.DataFrame) -> dict:
    """Summarize genuine complete hourly prices independently of joined Silver."""
    empty = {
        "latest_timestamp": None,
        "latest_price": None,
        "previous_24h_average": None,
        "seven_day_average": None,
    }
    if prices.empty or not {"timestamp", "price_eur_mwh"}.issubset(prices):
        return empty
    prepared = prices.copy()
    prepared["timestamp"] = pd.to_datetime(
        prepared["timestamp"], errors="coerce", utc=True
    )
    prepared = prepared.dropna(subset=["timestamp"])
    if prepared.empty or prepared["timestamp"].duplicated().any():
        return empty
    try:
        hourly = aggregate_hourly_prices(prepared.set_index("timestamp"))
    except (TypeError, ValueError):
        return empty
    if hourly.empty:
        return empty
    latest_timestamp = hourly.index[-1]
    return {
        "latest_timestamp": latest_timestamp,
        "latest_price": _finite_number(hourly["price_eur_mwh"].iloc[-1]),
        "previous_24h_average": _exact_hourly_stat(
            hourly, "price_eur_mwh", latest_timestamp, 24
        ),
        "seven_day_average": _exact_hourly_stat(
            hourly, "price_eur_mwh", latest_timestamp, 168
        ),
    }

def build_model_input_context(
    silver: pd.DataFrame,
    issue_time,
) -> dict:
    """Describe persisted issue-hour inputs; never substitute a different hour."""
    data = _prepare_observed_market(silver)
    issue = _utc_timestamp(issue_time)
    empty = {
        "available": False,
        "issue_time": issue,
        "load_mw": None,
        "wind_total_mw": None,
        "solar_mw": None,
        "renewable_share": None,
        "price_eur_mwh": None,
        "price_rolling_mean_24h": None,
        "price_rolling_std_24h": None,
        "price_average_7d": None,
        "temperature_2m": None,
        "relative_humidity_2m": None,
        "wind_speed_10m": None,
        "cloud_cover": None,
        "shortwave_radiation": None,
    }
    if data.empty or issue is None or issue not in data.index:
        return empty
    row = data.loc[issue]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]
    _, renewable_share = _renewable_metrics(row)
    values = {
        "available": True,
        "issue_time": issue,
        "renewable_share": renewable_share,
        "price_rolling_mean_24h": _exact_hourly_stat(
            data, "price_eur_mwh", issue, 24
        ),
        "price_rolling_std_24h": _exact_hourly_stat(
            data, "price_eur_mwh", issue, 24, statistic="std"
        ),
        "price_average_7d": _exact_hourly_stat(
            data, "price_eur_mwh", issue, 168
        ),
    }
    for column in (
        "load_mw", "wind_total_mw", "solar_mw", "price_eur_mwh",
        "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
        "cloud_cover", "shortwave_radiation",
    ):
        values[column] = _finite_number(row.get(column))
    return {**empty, **values}

import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st


EMPTY_DATASET_SUMMARY = {
    "available": False,
    "row_count": 0,
    "earliest_timestamp": None,
    "latest_timestamp": None,
    "columns": (),
}

MODEL_INPUT_CONTEXT_NOTE = (
    "Observed conditions associated with this forecast. These are model "
    "inputs and context, not causal explanations."
)


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


def forecast_freshness(
    forecast: pd.DataFrame,
    *,
    now: pd.Timestamp | None = None,
    maximum_age_hours: float = 3.0,
) -> dict:
    """Classify a validated forecast without hiding retained stale values."""
    summary = summarize_next24h_forecast(forecast, now=now)
    if summary is None:
        return {"status": "Unavailable", "age_hours": None, "is_stale": False}
    current = _utc_timestamp(pd.Timestamp.now(tz="UTC") if now is None else now)
    issue = _utc_timestamp(summary["issue_time"])
    age_hours = (current - issue).total_seconds() / 3600
    is_stale = age_hours < 0 or age_hours > maximum_age_hours
    return {
        "status": "Stale" if is_stale else "Fresh",
        "age_hours": age_hours,
        "is_stale": is_stale,
    }


def build_market_context(
    silver: pd.DataFrame,
    forecast: pd.DataFrame,
    *,
    now: pd.Timestamp | None = None,
    maximum_age_hours: float = 3.0,
) -> dict:
    """Build separate observed and forecast market context from existing data."""
    observed_data = _prepare_observed_market(silver)
    observed = {
        "timestamp": None,
        "price_eur_mwh": None,
        "load_mw": None,
        "wind_total_mw": None,
        "solar_mw": None,
        "renewable_generation_mw": None,
        "renewable_share": None,
        "temperature_2m": None,
        "previous_24h_price_average": None,
        "seven_day_price_average": None,
    }
    if not observed_data.empty:
        row = observed_data.iloc[-1]
        timestamp = observed_data.index[-1]
        renewable_generation, renewable_share = _renewable_metrics(row)
        observed.update({
            "timestamp": timestamp,
            "price_eur_mwh": _finite_number(row.get("price_eur_mwh")),
            "load_mw": _finite_number(row.get("load_mw")),
            "wind_total_mw": _finite_number(row.get("wind_total_mw")),
            "solar_mw": _finite_number(row.get("solar_mw")),
            "renewable_generation_mw": renewable_generation,
            "renewable_share": renewable_share,
            "temperature_2m": _finite_number(row.get("temperature_2m")),
            "previous_24h_price_average": _exact_hourly_stat(
                observed_data, "price_eur_mwh", timestamp, 24
            ),
            "seven_day_price_average": _exact_hourly_stat(
                observed_data, "price_eur_mwh", timestamp, 168
            ),
        })

    summary = summarize_next24h_forecast(forecast, now=now)
    freshness = forecast_freshness(
        forecast, now=now, maximum_age_hours=maximum_age_hours
    )
    forecast_context = {
        "issue_time": None,
        "average": None,
        "minimum": None,
        "minimum_time": None,
        "maximum": None,
        "maximum_time": None,
        "negative_hours": None,
        "elevated_hours": None,
        "rows": 0,
        "forward_looking_rows": 0,
        **freshness,
    }
    if summary:
        forecast_context.update({key: summary[key] for key in (
            "issue_time", "average", "minimum", "minimum_time", "maximum",
            "maximum_time", "negative_hours", "elevated_hours", "rows",
            "forward_looking_rows",
        )})
    return {"observed": observed, "forecast": forecast_context}


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


def file_mtime_ns(path: Path) -> int | None:
    """Return a stable cache version for a file without raising on missing paths."""
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return None


@st.cache_data(show_spinner=False)
def _load_csv_versioned(
    path_string: str,
    modification_time_ns: int | None,
    timestamp_columns: tuple[str, ...],
    sort_by: str | None,
) -> pd.DataFrame:
    if modification_time_ns is None:
        return pd.DataFrame()

    try:
        data = pd.read_csv(path_string)
    except (OSError, ValueError, pd.errors.ParserError):
        return pd.DataFrame()

    for column in timestamp_columns:
        if column in data.columns:
            data[column] = pd.to_datetime(data[column], errors="coerce", utc=True)

    if sort_by and sort_by in data.columns:
        data = data.sort_values(
            sort_by,
            kind="stable",
            na_position="last",
        ).reset_index(drop=True)

    return data


def load_dashboard_csv(
    path: Path,
    *,
    timestamp_columns: tuple[str, ...] = (),
    sort_by: str | None = None,
) -> pd.DataFrame:
    """Load a CSV until its nanosecond modification time changes."""
    path = Path(path)
    return _load_csv_versioned(
        str(path),
        file_mtime_ns(path),
        timestamp_columns,
        sort_by,
    )


@st.cache_data(show_spinner=False)
def _load_csv_summary_versioned(
    path_string: str,
    modification_time_ns: int | None,
    timestamp_column: str,
) -> dict:
    if modification_time_ns is None:
        return EMPTY_DATASET_SUMMARY.copy()

    try:
        columns = tuple(pd.read_csv(path_string, nrows=0).columns)
        if timestamp_column not in columns:
            return {
                **EMPTY_DATASET_SUMMARY,
                "columns": columns,
            }
        timestamps = pd.read_csv(path_string, usecols=[timestamp_column])
    except (OSError, ValueError, pd.errors.ParserError):
        return EMPTY_DATASET_SUMMARY.copy()

    parsed_timestamps = pd.to_datetime(
        timestamps[timestamp_column],
        errors="coerce",
        utc=True,
    )
    return {
        "available": not timestamps.empty,
        "row_count": len(timestamps),
        "earliest_timestamp": parsed_timestamps.min(),
        "latest_timestamp": parsed_timestamps.max(),
        "columns": columns,
    }


def load_csv_summary(path: Path, timestamp_column: str = "timestamp") -> dict:
    """Read only a CSV header and timestamp column for sidebar/status metadata."""
    path = Path(path)
    return _load_csv_summary_versioned(
        str(path),
        file_mtime_ns(path),
        timestamp_column,
    )


@st.cache_data(show_spinner=False)
def _csv_has_rows_versioned(
    path_string: str,
    modification_time_ns: int | None,
) -> bool:
    if modification_time_ns is None:
        return False
    try:
        return not pd.read_csv(path_string, nrows=1).empty
    except (OSError, ValueError, pd.errors.ParserError):
        return False


def csv_has_rows(path: Path) -> bool:
    """Check report availability without loading the complete CSV."""
    path = Path(path)
    return _csv_has_rows_versioned(str(path), file_mtime_ns(path))


def load_next24h_forecast_report(path: Path) -> tuple[pd.DataFrame, str | None]:
    """Read the latest forecast without treating an incomplete file as current."""
    data = load_dashboard_csv(
        path,
        timestamp_columns=("forecast_issue_time", "target_timestamp"),
        sort_by="horizon_hours",
    )
    required = (
        "forecast_issue_time", "target_timestamp", "horizon_hours",
        "predicted_price_eur_mwh", "model_release",
    )
    if data.empty:
        return data, "No next-24-hour production forecast is available yet."
    if not set(required).issubset(data.columns) or len(data) != 24:
        return pd.DataFrame(), "Next-24-hour forecast file has an invalid schema or row count."
    issues = data["forecast_issue_time"]
    targets = data["target_timestamp"]
    horizons = pd.to_numeric(data["horizon_hours"], errors="coerce")
    prices = pd.to_numeric(data["predicted_price_eur_mwh"], errors="coerce")
    if (
        issues.isna().any() or targets.isna().any()
        or issues.nunique() != 1 or data["model_release"].nunique() != 1
        or horizons.tolist() != list(range(1, 25))
        or targets.duplicated().any() or not targets.is_monotonic_increasing
        or not (targets == issues + pd.to_timedelta(horizons, unit="h")).all()
        or prices.isna().any()
    ):
        return pd.DataFrame(), "Next-24-hour forecast timestamps or values are invalid."
    return data.loc[:, required], None


def summarize_next24h_forecast(
    forecast: pd.DataFrame,
    *,
    now: pd.Timestamp | None = None,
) -> dict | None:
    """Summarize an already validated 24-row forecast without changing it."""
    if forecast.empty or len(forecast) != 24:
        return None
    prices = pd.to_numeric(forecast["predicted_price_eur_mwh"], errors="coerce")
    if prices.isna().any() or not all(math.isfinite(value) for value in prices):
        return None
    low = forecast.loc[prices.idxmin()]
    high = forecast.loc[prices.idxmax()]
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    current = current.tz_localize("UTC") if current.tzinfo is None else current.tz_convert("UTC")
    targets = pd.to_datetime(forecast["target_timestamp"], errors="coerce", utc=True)
    if targets.isna().any():
        return None
    return {
        "issue_time": forecast["forecast_issue_time"].iloc[0],
        "release_id": forecast["model_release"].iloc[0],
        "rows": len(forecast),
        "forward_looking_rows": int(targets.gt(current).sum()),
        "minimum": float(prices.min()),
        "minimum_time": low["target_timestamp"],
        "maximum": float(prices.max()),
        "maximum_time": high["target_timestamp"],
        "average": float(prices.mean()),
        "median": float(prices.median()),
        "first_to_last_change": float(prices.iloc[-1] - prices.iloc[0]),
        "negative_hours": int(prices.lt(0).sum()),
        "elevated_hours": int(prices.ge(200).sum()),
    }


def prediction_count_metrics(
    one_hour_predictions,
    next24h_forecast: pd.DataFrame,
) -> tuple[tuple[str, object], tuple[str, int]]:
    """Keep one-hour report rows distinct from the validated next24h report."""
    next24h_rows = len(next24h_forecast) if len(next24h_forecast) == 24 else 0
    return (
        ("New One-Hour Predictions", one_hour_predictions),
        ("Next24h Forecast Rows", next24h_rows),
    )


def downsample_time_series(
    data: pd.DataFrame,
    max_points: int = 4_000,
) -> pd.DataFrame:
    """Select deterministic, ordered chart points while retaining both endpoints."""
    if max_points < 2:
        raise ValueError("max_points must be at least 2")
    if len(data) <= max_points:
        return data

    step = math.ceil((len(data) - 1) / (max_points - 1))
    positions = list(range(0, len(data), step))
    if positions[-1] != len(data) - 1:
        positions.append(len(data) - 1)
    return data.iloc[positions]


def _read_final_release_metadata(
    manifest_path: Path,
    metrics_path: Path,
):
    manifest_path = Path(manifest_path)
    metrics_path = Path(metrics_path)
    if not manifest_path.exists():
        return None, f"Final release manifest not found at {manifest_path}."

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f"Could not read final release manifest: {exc}"

    try:
        model = manifest["model"]
        holdout = manifest["final_holdout"]
        holdout_metrics = holdout["metrics"]
        improvements = manifest["rmse_improvements"]
        metadata = {
            "model_name": model["selected_model"],
            "feature_group": model["selected_feature_group"],
            "feature_count": int(model["feature_count"]),
            "mae": float(holdout_metrics["mae"]),
            "rmse": float(holdout_metrics["rmse"]),
            "r2": float(holdout_metrics["r2"]),
            "holdout_start": holdout["target_date_range"]["start"],
            "holdout_end": holdout["target_date_range"]["end"],
            "holdout_rows": int(holdout["rows"]),
            "improvement_vs_persistence_pct": float(
                improvements["vs_persistence_pct"]
            ),
            "mlflow_run_id": manifest.get("mlflow_run_id"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Final release manifest has an invalid schema: {exc}"

    if metrics_path.exists():
        try:
            report = pd.read_csv(metrics_path)
            required = {
                "mae",
                "rmse",
                "r2",
                "holdout_start",
                "holdout_end",
                "rmse_improvement_vs_persistence_pct",
            }
            if len(report) == 1 and required.issubset(report.columns):
                row = report.iloc[0]
                metadata.update(
                    {
                        "mae": float(row["mae"]),
                        "rmse": float(row["rmse"]),
                        "r2": float(row["r2"]),
                        "holdout_start": row["holdout_start"],
                        "holdout_end": row["holdout_end"],
                        "improvement_vs_persistence_pct": float(
                            row["rmse_improvement_vs_persistence_pct"]
                        ),
                    }
                )
        except (OSError, ValueError, pd.errors.ParserError):
            pass

    return metadata, None


@st.cache_data(show_spinner=False)
def _load_final_release_metadata_versioned(
    manifest_path_string: str,
    manifest_mtime_ns: int | None,
    metrics_path_string: str,
    metrics_mtime_ns: int | None,
):
    del manifest_mtime_ns, metrics_mtime_ns
    return _read_final_release_metadata(
        Path(manifest_path_string),
        Path(metrics_path_string),
    )


def load_final_release_metadata(
    manifest_path: Path,
    metrics_path: Path,
):
    """Load release metadata until either source file changes."""
    manifest_path = Path(manifest_path)
    metrics_path = Path(metrics_path)
    return _load_final_release_metadata_versioned(
        str(manifest_path),
        file_mtime_ns(manifest_path),
        str(metrics_path),
        file_mtime_ns(metrics_path),
    )

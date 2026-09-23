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

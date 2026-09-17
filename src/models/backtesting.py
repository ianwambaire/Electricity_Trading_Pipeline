from dataclasses import dataclass

import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


TARGET_COLUMN = "target_price_next_hour"
PRICE_COLUMN = "price_eur_mwh"
TIMESTAMP_COLUMN = "timestamp"
BASELINE_OFFSETS_HOURS = {
    "Persistence Baseline": 1,
    "Daily Seasonal Naive": 24,
    "Weekly Seasonal Naive": 168,
}
BASELINE_NAMES = tuple(BASELINE_OFFSETS_HOURS)
SEASONAL_BASELINE_NAMES = {
    "Daily Seasonal Naive",
    "Weekly Seasonal Naive",
}


@dataclass(frozen=True)
class ExpandingWindowFold:
    validation_period: str
    train_indices: pd.Index
    validation_indices: pd.Index
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp


def forecast_timestamps(data: pd.DataFrame) -> pd.Series:
    timestamps = pd.to_datetime(data[TIMESTAMP_COLUMN], utc=True)
    if not timestamps.is_monotonic_increasing or not timestamps.is_unique:
        raise ValueError("Backtesting data must have unique chronological timestamps.")
    return timestamps + pd.Timedelta(hours=1)


def baseline_source_timestamps(data: pd.DataFrame) -> pd.DataFrame:
    target_times = forecast_timestamps(data)
    return pd.DataFrame(
        {
            name: target_times - pd.Timedelta(hours=offset)
            for name, offset in BASELINE_OFFSETS_HOURS.items()
        },
        index=data.index,
    )


def build_baseline_predictions(data: pd.DataFrame) -> pd.DataFrame:
    timestamps = pd.to_datetime(data[TIMESTAMP_COLUMN], utc=True)
    prices = pd.Series(
        pd.to_numeric(data[PRICE_COLUMN], errors="raise").to_numpy(),
        index=timestamps,
    )
    source_times = baseline_source_timestamps(data)

    return pd.DataFrame(
        {
            name: source_times[name].map(prices)
            for name in BASELINE_OFFSETS_HOURS
        },
        index=data.index,
    )


def build_expanding_window_folds(
    data: pd.DataFrame,
    validation_years: tuple[int, ...] = (2022, 2023, 2024),
    final_holdout_start: str = "2025-01-01",
) -> list[ExpandingWindowFold]:
    target_times = forecast_timestamps(data)
    holdout_start = pd.Timestamp(final_holdout_start, tz="UTC")
    folds = []

    for validation_year in validation_years:
        validation_start = pd.Timestamp(f"{validation_year}-01-01", tz="UTC")
        validation_stop = pd.Timestamp(f"{validation_year + 1}-01-01", tz="UTC")
        if validation_stop > holdout_start:
            raise ValueError("Development folds cannot overlap the final holdout.")

        train_mask = target_times < validation_start
        validation_mask = (
            (target_times >= validation_start)
            & (target_times < validation_stop)
            & (target_times < holdout_start)
        )
        train_indices = data.index[train_mask]
        validation_indices = data.index[validation_mask]
        if train_indices.empty or validation_indices.empty:
            raise ValueError(
                f"Insufficient rows for validation period {validation_year}."
            )

        train_times = target_times.loc[train_indices]
        validation_times = target_times.loc[validation_indices]
        folds.append(
            ExpandingWindowFold(
                validation_period=str(validation_year),
                train_indices=train_indices,
                validation_indices=validation_indices,
                train_start=train_times.min(),
                train_end=train_times.max(),
                validation_start=validation_times.min(),
                validation_end=validation_times.max(),
            )
        )

    return folds


def calculate_forecast_metrics(actual, predicted) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "rmse": float(mean_squared_error(actual, predicted) ** 0.5),
        "r2": float(r2_score(actual, predicted)),
    }


def calculate_rmse_improvement(
    model_rmse: float,
    baseline_rmse: float,
) -> float:
    if baseline_rmse <= 0:
        raise ValueError("Baseline RMSE must be positive.")
    return float((baseline_rmse - model_rmse) / baseline_rmse * 100.0)


def add_improvement_statistics(results: pd.DataFrame) -> pd.DataFrame:
    results = results.copy()
    results["rmse_improvement_vs_persistence_pct"] = float("nan")
    results["rmse_improvement_vs_best_seasonal_pct"] = float("nan")

    for validation_period, period_results in results.groupby("validation_period"):
        persistence_rmse = period_results.loc[
            period_results["model_name"] == "Persistence Baseline",
            "rmse",
        ].item()
        best_seasonal_rmse = period_results.loc[
            period_results["model_name"].isin(SEASONAL_BASELINE_NAMES),
            "rmse",
        ].min()
        ml_mask = (
            (results["validation_period"] == validation_period)
            & ~results["model_name"].isin(BASELINE_NAMES)
        )
        results.loc[ml_mask, "rmse_improvement_vs_persistence_pct"] = (
            results.loc[ml_mask, "rmse"].map(
                lambda value: calculate_rmse_improvement(value, persistence_rmse)
            )
        )
        results.loc[ml_mask, "rmse_improvement_vs_best_seasonal_pct"] = (
            results.loc[ml_mask, "rmse"].map(
                lambda value: calculate_rmse_improvement(value, best_seasonal_rmse)
            )
        )

    return results


def build_aggregate_statistics(results: pd.DataFrame) -> pd.DataFrame:
    aggregate = (
        results.groupby("model_name", sort=False)
        .agg(
            validation_periods=("validation_period", "count"),
            mean_mae=("mae", "mean"),
            mean_rmse=("rmse", "mean"),
            rmse_std=("rmse", lambda values: values.std(ddof=0)),
            min_rmse=("rmse", "min"),
            max_rmse=("rmse", "max"),
            mean_rmse_improvement_vs_persistence_pct=(
                "rmse_improvement_vs_persistence_pct",
                "mean",
            ),
            mean_rmse_improvement_vs_best_seasonal_pct=(
                "rmse_improvement_vs_best_seasonal_pct",
                "mean",
            ),
        )
        .reset_index()
    )
    return aggregate

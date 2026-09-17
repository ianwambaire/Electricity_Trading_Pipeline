from collections import OrderedDict

import numpy as np
import pandas as pd

if __package__:
    from .backtesting import (
        TARGET_COLUMN,
        TIMESTAMP_COLUMN,
        calculate_forecast_metrics,
        calculate_rmse_improvement,
        forecast_timestamps,
    )
else:
    from backtesting import (
        TARGET_COLUMN,
        TIMESTAMP_COLUMN,
        calculate_forecast_metrics,
        calculate_rmse_improvement,
        forecast_timestamps,
    )


FEATURE_GROUPS = OrderedDict(
    {
        "Time Only": [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
        ],
        "Time + Price History": [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "price_eur_mwh",
            "price_lag_1h",
            "price_lag_24h",
            "price_lag_168h",
            "price_rolling_mean_24h",
            "price_rolling_std_24h",
        ],
        "Time + Price + Load": [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "price_eur_mwh",
            "price_lag_1h",
            "price_lag_24h",
            "price_lag_168h",
            "price_rolling_mean_24h",
            "price_rolling_std_24h",
            "load_mw",
            "load_lag_1h",
            "load_lag_24h",
            "load_rolling_mean_24h",
        ],
        "Time + Price + Load + Generation": [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "price_eur_mwh",
            "price_lag_1h",
            "price_lag_24h",
            "price_lag_168h",
            "price_rolling_mean_24h",
            "price_rolling_std_24h",
            "load_mw",
            "load_lag_1h",
            "load_lag_24h",
            "load_rolling_mean_24h",
            "biomass_mw",
            "lignite_mw",
            "gas_mw",
            "hard_coal_mw",
            "hydro_mw",
            "nuclear_mw",
            "solar_mw",
            "wind_offshore_mw",
            "wind_onshore_mw",
            "wind_total_mw",
            "renewable_generation_mw",
            "renewable_share",
        ],
        "Full PowerFlow": [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "price_eur_mwh",
            "price_lag_1h",
            "price_lag_24h",
            "price_lag_168h",
            "price_rolling_mean_24h",
            "price_rolling_std_24h",
            "load_mw",
            "load_lag_1h",
            "load_lag_24h",
            "load_rolling_mean_24h",
            "biomass_mw",
            "lignite_mw",
            "gas_mw",
            "hard_coal_mw",
            "hydro_mw",
            "nuclear_mw",
            "solar_mw",
            "wind_offshore_mw",
            "wind_onshore_mw",
            "wind_total_mw",
            "renewable_generation_mw",
            "renewable_share",
            "temperature_2m",
            "relative_humidity_2m",
            "wind_speed_10m",
            "cloud_cover",
            "shortwave_radiation",
        ],
    }
)

REGIME_LABELS = (
    "Negative",
    "Normal",
    "High",
    "Extreme",
)


def validate_feature_groups(available_columns) -> None:
    available_features = set(available_columns) - {TIMESTAMP_COLUMN, TARGET_COLUMN}
    previous = set()

    for group_name, columns in FEATURE_GROUPS.items():
        current = set(columns)
        if len(columns) != len(current):
            raise ValueError(f"Feature group {group_name!r} contains duplicates.")
        if TARGET_COLUMN in current or TIMESTAMP_COLUMN in current:
            raise ValueError(f"Feature group {group_name!r} contains a forbidden column.")
        missing = current - available_features
        if missing:
            raise ValueError(
                f"Feature group {group_name!r} contains unavailable columns: "
                f"{sorted(missing)}"
            )
        if previous and not previous < current:
            raise ValueError("Feature groups must be strictly cumulative.")
        previous = current

    if previous != available_features:
        missing = available_features - previous
        extra = previous - available_features
        raise ValueError(
            "Full PowerFlow must contain every current model feature exactly once; "
            f"missing={sorted(missing)}, extra={sorted(extra)}."
        )


def build_ablation_aggregate(
    results: pd.DataFrame,
    persistence_mean_rmse: float,
) -> pd.DataFrame:
    aggregate = (
        results.groupby(["model_name", "feature_group"], sort=False)
        .agg(
            feature_count=("feature_count", "first"),
            validation_periods=("validation_period", "count"),
            mean_mae=("mae", "mean"),
            mean_rmse=("rmse", "mean"),
            rmse_std=("rmse", lambda values: values.std(ddof=0)),
        )
        .reset_index()
    )
    aggregate["improvement_vs_previous_feature_group_pct"] = np.nan
    aggregate["improvement_vs_time_only_pct"] = np.nan
    aggregate["improvement_vs_persistence_baseline_pct"] = aggregate[
        "mean_rmse"
    ].map(lambda value: calculate_rmse_improvement(value, persistence_mean_rmse))

    group_order = list(FEATURE_GROUPS)
    for model_name, model_rows in aggregate.groupby("model_name", sort=False):
        rmse_by_group = model_rows.set_index("feature_group")["mean_rmse"]
        time_only_rmse = rmse_by_group[group_order[0]]
        for position, group_name in enumerate(group_order):
            row_mask = (
                (aggregate["model_name"] == model_name)
                & (aggregate["feature_group"] == group_name)
            )
            current_rmse = rmse_by_group[group_name]
            aggregate.loc[row_mask, "improvement_vs_time_only_pct"] = (
                calculate_rmse_improvement(current_rmse, time_only_rmse)
            )
            if position:
                previous_rmse = rmse_by_group[group_order[position - 1]]
                aggregate.loc[
                    row_mask,
                    "improvement_vs_previous_feature_group_pct",
                ] = calculate_rmse_improvement(current_rmse, previous_rmse)

    return aggregate


def assign_price_regimes(targets: pd.Series) -> pd.Series:
    numeric_targets = pd.to_numeric(targets, errors="raise")
    regimes = pd.cut(
        numeric_targets,
        bins=[-np.inf, 0.0, 100.0, 200.0, np.inf],
        labels=REGIME_LABELS,
        right=False,
    )
    if regimes.isna().any():
        raise ValueError("Every target must belong to exactly one price regime.")
    return regimes


def build_regime_performance(predictions: pd.DataFrame) -> pd.DataFrame:
    required = {
        "model_name",
        "feature_group",
        "validation_period",
        "actual",
        "predicted",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Prediction data is missing columns: {sorted(missing)}")

    evaluated = predictions.copy()
    evaluated["price_regime"] = assign_price_regimes(evaluated["actual"])
    rows = []

    def append_regimes(group, validation_period):
        for regime in REGIME_LABELS:
            regime_rows = group[group["price_regime"] == regime]
            row = {
                "model_name": group["model_name"].iloc[0],
                "feature_group": group["feature_group"].iloc[0],
                "validation_period": validation_period,
                "price_regime": regime,
                "observation_count": len(regime_rows),
                "mae": np.nan,
                "rmse": np.nan,
                "mean_absolute_error": np.nan,
                "mean_signed_error_bias": np.nan,
            }
            if not regime_rows.empty:
                errors = regime_rows["predicted"] - regime_rows["actual"]
                metrics = calculate_forecast_metrics(
                    regime_rows["actual"],
                    regime_rows["predicted"],
                )
                row.update(
                    {
                        "mae": metrics["mae"],
                        "rmse": metrics["rmse"],
                        "mean_absolute_error": float(errors.abs().mean()),
                        "mean_signed_error_bias": float(errors.mean()),
                    }
                )
            rows.append(row)

    yearly_groups = evaluated.groupby(
        ["model_name", "feature_group", "validation_period"],
        sort=False,
        observed=True,
    )
    for (_, _, validation_period), group in yearly_groups:
        append_regimes(group, validation_period)

    all_period_groups = evaluated.groupby(
        ["model_name", "feature_group"],
        sort=False,
        observed=True,
    )
    for _, group in all_period_groups:
        append_regimes(group, "All Development Folds")

    return pd.DataFrame(rows)


def build_yearly_price_regimes(
    data: pd.DataFrame,
    final_holdout_start: str = "2025-01-01",
) -> pd.DataFrame:
    target_times = forecast_timestamps(data)
    holdout_start = pd.Timestamp(final_holdout_start, tz="UTC")
    development = pd.DataFrame(
        {
            "year": target_times.dt.year,
            "target": pd.to_numeric(data[TARGET_COLUMN], errors="raise"),
        },
        index=data.index,
    ).loc[target_times < holdout_start]

    rows = []
    for year, group in development.groupby("year", sort=True):
        targets = group["target"]
        rows.append(
            {
                "year": int(year),
                "count": len(targets),
                "mean": float(targets.mean()),
                "median": float(targets.median()),
                "std": float(targets.std()),
                "min": float(targets.min()),
                "max": float(targets.max()),
                "negative_price_count": int((targets < 0).sum()),
                "prices_ge_200_count": int((targets >= 200).sum()),
            }
        )
    return pd.DataFrame(rows)

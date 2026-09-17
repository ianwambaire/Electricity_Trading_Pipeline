import pandas as pd
from sklearn.model_selection import TimeSeriesSplit


COMPARISON_COLUMNS = [
    "model_name",
    "tuning_status",
    "cv_rmse",
    "cv_rmse_std",
    "cv_rmse_min",
    "cv_rmse_max",
    "test_mae",
    "test_rmse",
    "test_r2",
    "selected",
    "mae",
    "rmse",
    "r2",
]

CV_DIAGNOSTIC_COLUMNS = [
    "model_name",
    "fold",
    "fold_rmse",
    "mean_cv_rmse",
    "std_cv_rmse",
    "min_fold_rmse",
    "max_fold_rmse",
    "training_start_timestamp",
    "training_end_timestamp",
    "validation_start_timestamp",
    "validation_end_timestamp",
    "train_row_count",
    "validation_row_count",
]


def chronological_holdout_split(
    data: pd.DataFrame,
    target_column: str,
    timestamp_column: str = "timestamp",
    train_fraction: float = 0.8,
):
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1.")
    if not data[timestamp_column].is_monotonic_increasing:
        raise ValueError("Data must be sorted chronologically before splitting.")

    features = data.drop(columns=[timestamp_column, target_column])
    target = data[target_column]
    split_index = int(len(data) * train_fraction)

    if split_index == 0 or split_index == len(data):
        raise ValueError("Dataset is too small for the requested holdout split.")

    return (
        features.iloc[:split_index],
        features.iloc[split_index:],
        target.iloc[:split_index],
        target.iloc[split_index:],
    )


def build_time_series_cv(n_splits: int = 3) -> TimeSeriesSplit:
    return TimeSeriesSplit(n_splits=n_splits)


def summarize_cv_rmse(fold_rmse: list[float]) -> dict[str, float]:
    if not fold_rmse:
        raise ValueError("At least one fold RMSE value is required.")

    scores = pd.Series(fold_rmse, dtype="float64")
    return {
        "cv_rmse": float(scores.mean()),
        "cv_rmse_std": float(scores.std(ddof=0)),
        "cv_rmse_min": float(scores.min()),
        "cv_rmse_max": float(scores.max()),
    }


def build_fold_diagnostics(
    model_name: str,
    fold_rmse: list[float],
    timestamps: pd.Series,
    cross_validator: TimeSeriesSplit,
) -> list[dict]:
    timestamps = pd.to_datetime(timestamps, utc=True).reset_index(drop=True)
    splits = list(cross_validator.split(pd.DataFrame(index=timestamps.index)))

    if len(fold_rmse) != len(splits):
        raise ValueError("Fold RMSE count must match the cross-validation splits.")

    summary = summarize_cv_rmse(fold_rmse)
    diagnostics = []
    for fold_number, ((train_indices, validation_indices), rmse) in enumerate(
        zip(splits, fold_rmse),
        start=1,
    ):
        diagnostics.append(
            {
                "model_name": model_name,
                "fold": fold_number,
                "fold_rmse": float(rmse),
                "mean_cv_rmse": summary["cv_rmse"],
                "std_cv_rmse": summary["cv_rmse_std"],
                "min_fold_rmse": summary["cv_rmse_min"],
                "max_fold_rmse": summary["cv_rmse_max"],
                "training_start_timestamp": timestamps.iloc[
                    train_indices[0]
                ].isoformat(),
                "training_end_timestamp": timestamps.iloc[
                    train_indices[-1]
                ].isoformat(),
                "validation_start_timestamp": timestamps.iloc[
                    validation_indices[0]
                ].isoformat(),
                "validation_end_timestamp": timestamps.iloc[
                    validation_indices[-1]
                ].isoformat(),
                "train_row_count": len(train_indices),
                "validation_row_count": len(validation_indices),
            }
        )

    return diagnostics


def build_cv_diagnostics_dataframe(results: list[dict]) -> pd.DataFrame:
    rows = [
        diagnostic
        for result in results
        for diagnostic in result["fold_diagnostics"]
    ]
    return pd.DataFrame(rows, columns=CV_DIAGNOSTIC_COLUMNS)


def select_best_result(results: list[dict]) -> dict:
    if not results:
        raise ValueError("At least one model result is required.")
    return min(results, key=lambda result: (result["cv_rmse"], result["model_name"]))


def build_comparison_dataframe(results: list[dict], selected_model: str) -> pd.DataFrame:
    rows = []

    for result in results:
        rows.append(
            {
                "model_name": result["model_name"],
                "tuning_status": result["tuning_status"],
                "cv_rmse": result["cv_rmse"],
                "cv_rmse_std": result["cv_rmse_std"],
                "cv_rmse_min": result["cv_rmse_min"],
                "cv_rmse_max": result["cv_rmse_max"],
                "test_mae": result["test_mae"],
                "test_rmse": result["test_rmse"],
                "test_r2": result["test_r2"],
                "selected": result["model_name"] == selected_model,
                # Backward-compatible aliases used by the Streamlit dashboard.
                "mae": result["test_mae"],
                "rmse": result["test_rmse"],
                "r2": result["test_r2"],
            }
        )

    return pd.DataFrame(rows, columns=COMPARISON_COLUMNS)

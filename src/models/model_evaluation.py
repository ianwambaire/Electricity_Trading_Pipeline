import pandas as pd
from sklearn.model_selection import TimeSeriesSplit


COMPARISON_COLUMNS = [
    "model_name",
    "tuning_status",
    "cv_rmse",
    "test_mae",
    "test_rmse",
    "test_r2",
    "selected",
    "mae",
    "rmse",
    "r2",
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

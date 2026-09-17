import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import (
    ElasticNet,
    HuberRegressor,
    Lasso,
    LinearRegression,
    Ridge,
)
from sklearn.model_selection import ParameterGrid
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

if __package__:
    from .backtesting import (
        TARGET_COLUMN,
        build_expanding_window_folds,
        calculate_forecast_metrics,
        calculate_rmse_improvement,
        forecast_timestamps,
    )
    from .research_evaluation import FEATURE_GROUPS
else:
    from backtesting import (
        TARGET_COLUMN,
        build_expanding_window_folds,
        calculate_forecast_metrics,
        calculate_rmse_improvement,
        forecast_timestamps,
    )
    from research_evaluation import FEATURE_GROUPS


RANDOM_STATE = 42
FINAL_HOLDOUT_START = "2025-01-01"
LINEAR_MODEL_NAMES = (
    "Ordinary Linear Regression",
    "Ridge Regression",
    "Lasso Regression",
    "Elastic Net",
    "Huber Regressor",
)


@dataclass(frozen=True)
class FocusedCandidate:
    name: str
    feature_group: str
    estimator: Pipeline
    parameter_grid: dict
    simplicity_rank: int
    include_untuned_reference: bool = False


def scaled_pipeline(estimator) -> Pipeline:
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            ("model", estimator),
        ]
    )


def unscaled_pipeline(estimator) -> Pipeline:
    return Pipeline([("model", estimator)])


def build_focused_candidates() -> list[FocusedCandidate]:
    return [
        FocusedCandidate(
            "Ordinary Linear Regression",
            "Full PowerFlow",
            scaled_pipeline(LinearRegression()),
            {},
            1,
        ),
        FocusedCandidate(
            "Ridge Regression",
            "Full PowerFlow",
            scaled_pipeline(Ridge()),
            {"model__alpha": [0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0]},
            2,
        ),
        FocusedCandidate(
            "Lasso Regression",
            "Full PowerFlow",
            scaled_pipeline(Lasso(max_iter=20_000, selection="cyclic")),
            {"model__alpha": [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0]},
            3,
        ),
        FocusedCandidate(
            "Elastic Net",
            "Full PowerFlow",
            scaled_pipeline(
                ElasticNet(max_iter=20_000, selection="cyclic", random_state=RANDOM_STATE)
            ),
            {
                "model__alpha": [0.0001, 0.001, 0.01, 0.1, 1.0],
                "model__l1_ratio": [0.1, 0.25, 0.5, 0.75, 0.9],
            },
            4,
        ),
        FocusedCandidate(
            "Huber Regressor",
            "Full PowerFlow",
            scaled_pipeline(HuberRegressor(max_iter=500)),
            {
                "model__epsilon": [1.35, 1.75],
                "model__alpha": [0.0001, 0.01],
            },
            5,
        ),
        FocusedCandidate(
            "Random Forest",
            "Time + Price History",
            unscaled_pipeline(
                RandomForestRegressor(random_state=RANDOM_STATE, n_jobs=-1)
            ),
            {
                "model__n_estimators": [200, 400],
                "model__max_depth": [12, None],
                "model__min_samples_leaf": [1, 4],
                "model__max_features": [1.0],
            },
            6,
            True,
        ),
        FocusedCandidate(
            "Gradient Boosting",
            "Time + Price + Load + Generation",
            unscaled_pipeline(GradientBoostingRegressor(random_state=RANDOM_STATE)),
            {
                "model__n_estimators": [100, 200],
                "model__learning_rate": [0.03, 0.05],
                "model__max_depth": [2, 3],
            },
            7,
            True,
        ),
        FocusedCandidate(
            "XGBoost",
            "Time + Price History",
            unscaled_pipeline(
                XGBRegressor(
                    objective="reg:squarederror",
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                )
            ),
            {
                "model__n_estimators": [300, 500],
                "model__learning_rate": [0.03, 0.05],
                "model__max_depth": [2, 3],
                "model__subsample": [0.8],
                "model__colsample_bytree": [0.8],
            },
            8,
            True,
        ),
    ]


def build_focused_development_folds(data: pd.DataFrame):
    return build_expanding_window_folds(
        data,
        validation_years=(2022, 2023, 2024),
        final_holdout_start=FINAL_HOLDOUT_START,
    )


def validate_candidate_features(candidates, available_columns) -> None:
    available = set(available_columns) - {"timestamp", TARGET_COLUMN}
    for candidate in candidates:
        features = FEATURE_GROUPS[candidate.feature_group]
        if TARGET_COLUMN in features or "timestamp" in features:
            raise ValueError(f"{candidate.name} contains a forbidden feature.")
        missing = set(features) - available
        if missing:
            raise ValueError(
                f"{candidate.name} is missing configured features: {sorted(missing)}"
            )


def parameter_configurations(candidate: FocusedCandidate) -> list[dict]:
    configurations = list(ParameterGrid(candidate.parameter_grid or {}))
    if candidate.include_untuned_reference:
        return [{}, *configurations]
    return configurations


def configuration_key(summary: dict) -> tuple:
    return (
        summary["mean_rmse"],
        summary["rmse_std"],
        summary["mean_mae"],
        summary["selected_hyperparameters"],
    )


def summarize_configuration(fold_rows: list[dict]) -> dict:
    frame = pd.DataFrame(fold_rows)
    return {
        "mean_mae": float(frame["mae"].mean()),
        "mean_rmse": float(frame["rmse"].mean()),
        "rmse_std": float(frame["rmse"].std(ddof=0)),
        "min_rmse": float(frame["rmse"].min()),
        "max_rmse": float(frame["rmse"].max()),
    }


def evaluate_parameter_configuration(
    data: pd.DataFrame,
    folds,
    candidate: FocusedCandidate,
    parameters: dict,
    configuration_id: str,
):
    features = FEATURE_GROUPS[candidate.feature_group]
    fold_rows = []
    prediction_frames = []

    for fold in folds:
        train_data = data.loc[fold.train_indices]
        validation_data = data.loc[fold.validation_indices]
        model = clone(candidate.estimator).set_params(**parameters)
        model.fit(train_data[features], train_data[TARGET_COLUMN])
        predicted = model.predict(validation_data[features])
        metrics = calculate_forecast_metrics(
            validation_data[TARGET_COLUMN],
            predicted,
        )
        fold_rows.append(
            {
                "configuration_id": configuration_id,
                "model_name": candidate.name,
                "feature_group": candidate.feature_group,
                "feature_count": len(features),
                "selected_hyperparameters": json.dumps(parameters, sort_keys=True),
                "validation_period": fold.validation_period,
                "train_start": fold.train_start.isoformat(),
                "train_end": fold.train_end.isoformat(),
                "validation_start": fold.validation_start.isoformat(),
                "validation_end": fold.validation_end.isoformat(),
                "train_rows": len(train_data),
                "validation_rows": len(validation_data),
                **metrics,
            }
        )
        prediction_frames.append(
            pd.DataFrame(
                {
                    "configuration_id": configuration_id,
                    "model_name": candidate.name,
                    "feature_group": candidate.feature_group,
                    "validation_period": fold.validation_period,
                    "actual": validation_data[TARGET_COLUMN].to_numpy(),
                    "predicted": predicted,
                }
            )
        )

    summary = {
        "configuration_id": configuration_id,
        "model_name": candidate.name,
        "feature_group": candidate.feature_group,
        "feature_count": len(features),
        "selected_hyperparameters": json.dumps(parameters, sort_keys=True),
        "simplicity_rank": candidate.simplicity_rank,
        **summarize_configuration(fold_rows),
    }
    return fold_rows, summary, pd.concat(prediction_frames, ignore_index=True)


def add_persistence_improvement(
    aggregate: pd.DataFrame,
    persistence_mean_rmse: float,
) -> pd.DataFrame:
    result = aggregate.copy()
    result["improvement_vs_persistence_baseline_pct"] = result["mean_rmse"].map(
        lambda value: calculate_rmse_improvement(value, persistence_mean_rmse)
    )
    return result


def select_best_family_configurations(aggregate: pd.DataFrame) -> pd.DataFrame:
    selected_indices = []
    for _, group in aggregate.groupby("model_name", sort=False):
        ordered = group.sort_values(
            [
                "mean_rmse",
                "rmse_std",
                "mean_mae",
                "selected_hyperparameters",
            ],
            kind="stable",
        )
        selected_indices.append(ordered.index[0])
    return aggregate.loc[selected_indices].copy().reset_index(drop=True)


def select_development_winner(family_results: pd.DataFrame) -> dict:
    if family_results.empty:
        raise ValueError("At least one family result is required.")
    ranked = family_results.copy()
    ranked["extreme_2022_rmse"] = ranked["extreme_2022_rmse"].fillna(np.inf)
    winner = ranked.sort_values(
        [
            "mean_rmse",
            "rmse_std",
            "extreme_2022_rmse",
            "mean_mae",
            "simplicity_rank",
            "model_name",
        ],
        kind="stable",
    ).iloc[0]
    return winner.to_dict()


def build_coefficient_diagnostics(
    data: pd.DataFrame,
    candidates: list[FocusedCandidate],
    selected_family_results: pd.DataFrame,
) -> pd.DataFrame:
    target_times = forecast_timestamps(data)
    development = data.loc[
        target_times < pd.Timestamp(FINAL_HOLDOUT_START, tz="UTC")
    ]
    candidate_by_name = {candidate.name: candidate for candidate in candidates}
    rows = []

    for result in selected_family_results.to_dict(orient="records"):
        if result["model_name"] not in LINEAR_MODEL_NAMES:
            continue
        candidate = candidate_by_name[result["model_name"]]
        features = FEATURE_GROUPS[candidate.feature_group]
        parameters = json.loads(result["selected_hyperparameters"])
        model = clone(candidate.estimator).set_params(**parameters)
        model.fit(development[features], development[TARGET_COLUMN])
        coefficients = model.named_steps["model"].coef_

        correlations = development[features].corr().abs()
        np.fill_diagonal(correlations.values, np.nan)
        maximum_correlations = correlations.max(axis=1)

        for feature, coefficient in zip(features, coefficients):
            rows.append(
                {
                    "model_name": candidate.name,
                    "feature_group": candidate.feature_group,
                    "selected_hyperparameters": result["selected_hyperparameters"],
                    "feature": feature,
                    "standardized_coefficient": float(coefficient),
                    "absolute_standardized_coefficient": float(abs(coefficient)),
                    "coefficient_sign": (
                        "positive"
                        if coefficient > 0
                        else "negative" if coefficient < 0 else "zero"
                    ),
                    "max_absolute_feature_correlation": float(
                        maximum_correlations[feature]
                    ),
                }
            )

    diagnostics = pd.DataFrame(rows)
    if not diagnostics.empty:
        diagnostics["coefficient_magnitude_rank"] = (
            diagnostics.groupby("model_name")["absolute_standardized_coefficient"]
            .rank(method="dense", ascending=False)
            .astype(int)
        )
    return diagnostics

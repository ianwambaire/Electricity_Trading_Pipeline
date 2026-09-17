from pathlib import Path

import joblib
import pandas as pd

if __package__:
    from .final_evaluation import FINAL_FEATURES
else:
    from final_evaluation import FINAL_FEATURES


FINAL_MODEL_PATH = Path("artifacts/models/final_gold_model.joblib")
FINAL_FEATURES_PATH = Path("artifacts/models/final_gold_model_features.joblib")


def validate_release_feature_order(features) -> list[str]:
    ordered_features = list(features)
    expected = list(FINAL_FEATURES)
    if len(ordered_features) != 31:
        raise ValueError(
            f"Frozen model requires exactly 31 features; found {len(ordered_features)}."
        )
    if ordered_features != expected:
        raise ValueError(
            "Frozen model feature order does not match the final release definition."
        )
    if len(set(ordered_features)) != len(ordered_features):
        raise ValueError("Frozen model feature list contains duplicate columns.")
    return ordered_features


def load_final_model_release(
    model_path: Path = FINAL_MODEL_PATH,
    features_path: Path = FINAL_FEATURES_PATH,
):
    model_path = Path(model_path)
    features_path = Path(features_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Frozen final model not found at {model_path}.")
    if not features_path.exists():
        raise FileNotFoundError(
            f"Frozen final model feature list not found at {features_path}."
        )

    model = joblib.load(model_path)
    features = validate_release_feature_order(joblib.load(features_path))
    return model, features


def prepare_prediction_features(
    data: pd.DataFrame,
    features,
) -> pd.DataFrame:
    ordered_features = validate_release_feature_order(features)
    missing = [column for column in ordered_features if column not in data.columns]
    if missing:
        raise ValueError(
            "Gold dataset is missing frozen-model features: " + ", ".join(missing)
        )

    prediction_features = data.loc[:, ordered_features]
    if prediction_features.columns.tolist() != ordered_features:
        raise ValueError("Unable to preserve frozen model feature ordering.")
    if prediction_features.isna().any().any():
        missing_columns = prediction_features.columns[
            prediction_features.isna().any()
        ].tolist()
        raise ValueError(
            "Frozen-model prediction features contain missing values: "
            + ", ".join(missing_columns)
        )
    return prediction_features


def predict_with_final_model(data: pd.DataFrame, model, features):
    prediction_features = prepare_prediction_features(data, features)
    return model.predict(prediction_features)

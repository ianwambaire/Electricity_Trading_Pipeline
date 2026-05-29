from pathlib import Path

import joblib
import pandas as pd


MODEL_PATH = Path("models/electricity_price_model.pkl")
FEATURES_PATH = Path("models/model_features.pkl")
OUTPUT_PATH = Path("data/reports/feature_importance.csv")


def generate_feature_importance():
    if not MODEL_PATH.exists():
        raise FileNotFoundError("Model not found. Run python3 src/train_model.py first.")

    if not FEATURES_PATH.exists():
        raise FileNotFoundError("Feature list not found. Run python3 src/train_model.py first.")

    model = joblib.load(MODEL_PATH)
    feature_columns = joblib.load(FEATURES_PATH)

    if not hasattr(model, "feature_importances_"):
        raise ValueError("Selected model does not support feature importance.")

    importance_df = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": model.feature_importances_,
        }
    )

    importance_df = importance_df.sort_values("importance", ascending=False)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    importance_df.to_csv(OUTPUT_PATH, index=False)

    print("\nFeature Importance")
    print(importance_df)
    print(f"\nFeature importance saved to {OUTPUT_PATH}")

    return importance_df


if __name__ == "__main__":
    generate_feature_importance()
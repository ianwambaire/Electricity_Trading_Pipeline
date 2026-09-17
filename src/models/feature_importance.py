from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .final_model_runtime import load_final_model_release
else:
    from final_model_runtime import load_final_model_release


CSV_OUTPUT_PATH = Path("data/reports/feature_importance.csv")
PLOT_OUTPUT_PATH = Path("data/reports/feature_importance.png")


def build_linear_feature_importance(model, features) -> pd.DataFrame:
    estimator = model.named_steps.get("model") if hasattr(model, "named_steps") else model
    if not hasattr(estimator, "coef_"):
        raise TypeError(
            "Frozen final model does not expose linear coefficients for importance."
        )
    coefficients = estimator.coef_
    if len(coefficients) != len(features):
        raise ValueError("Model coefficient count does not match frozen feature count.")

    importance = pd.DataFrame(
        {
            "feature": features,
            "importance": abs(coefficients),
            "signed_coefficient": coefficients,
        }
    )
    return importance.sort_values("importance", ascending=False)


def main():
    model, features = load_final_model_release()
    importance = build_linear_feature_importance(model, features)
    CSV_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    importance.to_csv(CSV_OUTPUT_PATH, index=False)

    top_features = importance.head(15).sort_values("importance")
    plt.figure(figsize=(10, 6))
    plt.barh(top_features["feature"], top_features["importance"])
    plt.xlabel("Absolute standardized coefficient")
    plt.ylabel("Feature")
    plt.title("Final Linear Model Feature Influence")
    plt.tight_layout()
    plt.savefig(PLOT_OUTPUT_PATH)
    plt.close()

    print(f"Saved coefficient importance to {CSV_OUTPUT_PATH}")
    print(f"Saved plot to {PLOT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()

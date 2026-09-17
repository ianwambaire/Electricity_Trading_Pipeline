import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .final_model_runtime import load_final_model_release, predict_with_final_model
else:
    from final_model_runtime import load_final_model_release, predict_with_final_model


DATA_PATH = Path("data/features/gold_model_features.csv")
MANIFEST_PATH = Path("artifacts/models/final_model_release_manifest.json")
CSV_OUTPUT_PATH = Path("data/reports/actual_vs_predicted.csv")
PLOT_OUTPUT_PATH = Path("data/reports/actual_vs_predicted.png")
TARGET_COLUMN = "target_price_next_hour"


def load_release_holdout_period(manifest_path: Path = MANIFEST_PATH):
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Final release manifest not found at {manifest_path}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        period = manifest["final_holdout"]["target_date_range"]
        return pd.Timestamp(period["start"]), pd.Timestamp(period["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Final release manifest has an invalid holdout period.") from exc


def create_prediction_output(
    data: pd.DataFrame,
    model,
    features,
    holdout_start,
    holdout_end,
) -> pd.DataFrame:
    prepared = data.copy()
    prepared["timestamp"] = pd.to_datetime(prepared["timestamp"], utc=True)
    prepared = prepared.sort_values("timestamp").reset_index(drop=True)
    target_timestamps = prepared["timestamp"] + pd.Timedelta(hours=1)
    mask = (target_timestamps >= pd.Timestamp(holdout_start)) & (
        target_timestamps <= pd.Timestamp(holdout_end)
    )
    holdout = prepared.loc[mask].copy()
    if holdout.empty:
        raise ValueError("Gold dataset contains no rows in the final release period.")
    if TARGET_COLUMN not in holdout.columns:
        raise ValueError(f"Gold dataset is missing target column {TARGET_COLUMN!r}.")

    predictions = predict_with_final_model(holdout, model, features)
    return pd.DataFrame(
        {
            "timestamp": target_timestamps.loc[mask].to_numpy(),
            "actual_price": holdout[TARGET_COLUMN].to_numpy(),
            "predicted_price": predictions,
        }
    )


def main():
    data = pd.read_csv(DATA_PATH)
    model, features = load_final_model_release()
    holdout_start, holdout_end = load_release_holdout_period()
    results = create_prediction_output(
        data,
        model,
        features,
        holdout_start,
        holdout_end,
    )

    CSV_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(CSV_OUTPUT_PATH, index=False)

    plot_data = results.tail(500)
    plt.figure(figsize=(14, 6))
    plt.plot(plot_data["timestamp"], plot_data["actual_price"], label="Actual Price")
    plt.plot(
        plot_data["timestamp"],
        plot_data["predicted_price"],
        label="Predicted Price",
    )
    plt.xlabel("Forecast Target Timestamp")
    plt.ylabel("Electricity Price (EUR/MWh)")
    plt.title("Final Model: Actual vs Predicted Electricity Prices")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOT_OUTPUT_PATH)
    plt.close()

    print(f"Saved prediction results to {CSV_OUTPUT_PATH}")
    print(f"Saved plot to {PLOT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()

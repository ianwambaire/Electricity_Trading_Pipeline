import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .final_model_runtime import load_final_model_release, predict_with_final_model
else:
    from final_model_runtime import load_final_model_release, predict_with_final_model

from ingestion.incremental_utils import append_csv_safely, latest_stored_timestamp


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


def _save_prediction_plot(results: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
    plt.savefig(output_path)
    plt.close()


def run_prediction_report(
    mode: str = "historical",
    *,
    data_path: Path = DATA_PATH,
    csv_output_path: Path = CSV_OUTPUT_PATH,
    plot_output_path: Path = PLOT_OUTPUT_PATH,
) -> int:
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be 'historical' or 'incremental'.")

    data = pd.read_csv(data_path)
    model, features = load_final_model_release()
    holdout_start, holdout_end = load_release_holdout_period()

    if mode == "incremental":
        latest_prediction = latest_stored_timestamp(csv_output_path)
        prediction_start = (
            holdout_start
            if latest_prediction is None
            else latest_prediction + pd.Timedelta(nanoseconds=1)
        )
        target_timestamps = pd.to_datetime(data["timestamp"], utc=True) + pd.Timedelta(
            hours=1
        )
        if target_timestamps.empty or target_timestamps.max() < prediction_start:
            print("No newly eligible Gold rows are available for prediction.")
            return 0
        prediction_end = target_timestamps.max()
    else:
        prediction_start = holdout_start
        prediction_end = holdout_end

    results = create_prediction_output(
        data,
        model,
        features,
        prediction_start,
        prediction_end,
    )

    csv_output_path = Path(csv_output_path)
    if mode == "incremental":
        append_result = append_csv_safely(csv_output_path, results)
        prediction_count = append_result.new_rows
        combined_results = pd.read_csv(csv_output_path)
    else:
        csv_output_path.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(csv_output_path, index=False)
        prediction_count = len(results)
        combined_results = results

    _save_prediction_plot(combined_results, Path(plot_output_path))

    print(
        f"Saved prediction results to {csv_output_path} "
        f"({prediction_count} rows generated in {mode} mode)."
    )
    print(f"Saved plot to {plot_output_path}")
    return prediction_count


def parse_args():
    parser = argparse.ArgumentParser(description="Generate frozen-model predictions.")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        default="historical",
    )
    return parser.parse_args()


def main():
    arguments = parse_args()
    run_prediction_report(arguments.mode)


if __name__ == "__main__":
    main()

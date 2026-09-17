import json
from pathlib import Path

import pandas as pd


def load_final_release_metadata(
    manifest_path: Path,
    metrics_path: Path,
):
    manifest_path = Path(manifest_path)
    metrics_path = Path(metrics_path)
    if not manifest_path.exists():
        return None, f"Final release manifest not found at {manifest_path}."

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, f"Could not read final release manifest: {exc}"

    try:
        model = manifest["model"]
        holdout = manifest["final_holdout"]
        holdout_metrics = holdout["metrics"]
        improvements = manifest["rmse_improvements"]
        metadata = {
            "model_name": model["selected_model"],
            "feature_group": model["selected_feature_group"],
            "feature_count": int(model["feature_count"]),
            "mae": float(holdout_metrics["mae"]),
            "rmse": float(holdout_metrics["rmse"]),
            "r2": float(holdout_metrics["r2"]),
            "holdout_start": holdout["target_date_range"]["start"],
            "holdout_end": holdout["target_date_range"]["end"],
            "holdout_rows": int(holdout["rows"]),
            "improvement_vs_persistence_pct": float(
                improvements["vs_persistence_pct"]
            ),
            "mlflow_run_id": manifest.get("mlflow_run_id"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"Final release manifest has an invalid schema: {exc}"

    if metrics_path.exists():
        try:
            report = pd.read_csv(metrics_path)
            required = {
                "mae",
                "rmse",
                "r2",
                "holdout_start",
                "holdout_end",
                "rmse_improvement_vs_persistence_pct",
            }
            if len(report) == 1 and required.issubset(report.columns):
                row = report.iloc[0]
                metadata.update(
                    {
                        "mae": float(row["mae"]),
                        "rmse": float(row["rmse"]),
                        "r2": float(row["r2"]),
                        "holdout_start": row["holdout_start"],
                        "holdout_end": row["holdout_end"],
                        "improvement_vs_persistence_pct": float(
                            row["rmse_improvement_vs_persistence_pct"]
                        ),
                    }
                )
        except (OSError, ValueError, pd.errors.ParserError):
            pass

    return metadata, None

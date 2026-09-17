# PowerFlow artifacts

This directory is the local output location for current model artifacts.

The primary training script generates:

- `artifacts/models/best_gold_model.joblib` — the model selected using the lowest training-only time-series cross-validation RMSE;
- `artifacts/models/gold_model_features.joblib` — the ordered feature list required by that model; and
- `artifacts/models/training_manifest.json` — dataset identity, source range, split sizes, CV configuration, selected hyperparameters, final metrics, MLflow run ID, and Git commit SHA when available.

These binary files are reproducible outputs of the training pipeline and are intentionally excluded from Git. MLflow also stores serialized models and environment metadata in the local `mlruns/` or `mlartifacts/` stores.

## Artifact roles

- **Candidate artifacts:** each of the four evaluated models is tracked in its own MLflow run. Tree-based candidates use training-only `TimeSeriesSplit` tuning; Linear Regression remains untuned.
- **Development artifacts:** `best_gold_model.joblib` and `gold_model_features.joblib` remain available for historical development reproducibility but are no longer used by the primary prediction pipeline.
- **Release metadata:** `training_manifest.json` links the selected model to the exact gold dataset using its SHA-256 identifier.
- **Final evaluated release:** `final_gold_model.joblib`, `final_gold_model_features.joblib`, and `final_model_release_manifest.json` contain the frozen Ordinary Linear Regression release and its one-time 2025 holdout evidence. These are the active artifacts used by prediction reporting and the dashboard.
- **External releases:** Colab can direct the same three selected-model files and the comparison CSV to a configurable Google Drive release folder.

The trainer accepts `--data-path`, `--output-dir`, `--comparison-path`, and
`--mlflow-tracking-uri`. Their defaults preserve the existing local paths.

## Storage policy

- **GitHub:** training code, configuration, documentation, and lightweight metadata.
- **Local storage:** current development models and MLflow working artifacts.
- **Google Drive:** selected release models, milestone artifacts, and MLflow archives or backups that need longer-term retention or sharing.

Do not place credentials in model metadata or artifact filenames. No automatic Google Drive upload or formal production model registry is currently implemented.

See [`docs/google_drive_workflow.md`](../docs/google_drive_workflow.md) for the recommended external folder layout and manual release workflow.

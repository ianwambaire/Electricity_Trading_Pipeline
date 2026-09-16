# PowerFlow artifacts

This directory is the local output location for current model artifacts.

The primary training script generates:

- `artifacts/models/best_gold_model.joblib` — the model with the lowest chronological test RMSE;
- `artifacts/models/gold_model_features.joblib` — the ordered feature list required by that model.

These binary files are reproducible outputs of the training pipeline and are intentionally excluded from Git. MLflow also stores serialized models and environment metadata in the local `mlruns/` or `mlartifacts/` stores.

## Storage policy

- **GitHub:** training code, configuration, documentation, and lightweight metadata.
- **Local storage:** current development models and MLflow working artifacts.
- **Google Drive:** selected release models, milestone artifacts, and MLflow archives or backups that need longer-term retention or sharing.

Do not place credentials in model metadata or artifact filenames. No automatic Google Drive upload or formal production model registry is currently implemented.

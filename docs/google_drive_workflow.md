# Google Drive and Colab workflow

Google Drive is optional archival and release storage. PowerFlow does not use
the Drive API, store Drive credentials, or require Drive for local development.

## Recommended external layout

```text
PowerFlow/
├── datasets/
│   ├── snapshots/          Reviewed gold or source-data snapshots
│   └── archives/           Older large dataset exports
├── models/
│   └── releases/           Selected model release folders
├── experiments/
│   └── mlflow-archives/    Archived MLflow databases/artifact stores
└── backups/                Final project or artifact backups
```

Each model release should use a descriptive folder such as
`models/releases/2026-09-entsoe-baseline/`. The trainer writes these files into
the configured output folder:

- `best_gold_model.joblib`
- `gold_model_features.joblib`
- `training_manifest.json`

The comparison CSV can be directed into the same release folder with
`--comparison-path`. The manifest identifies the exact gold file by SHA-256,
records its source date range and row count, and links the selected model to its
metrics, MLflow run, and Git commit when available.

## Colab usage

Open `notebooks/colab_training.ipynb` in Google Colab and edit its configuration
cell. The notebook can mount Drive using Colab's normal interactive mount, but
mounting is disabled by default.

Set:

- `USE_GOOGLE_DRIVE` to `True` only when Drive storage is wanted;
- `GOLD_DATA_PATH` to a supplied gold CSV or a file under
  `datasets/snapshots/`;
- `RELEASE_NAME` to the desired release folder name; and
- `MLFLOW_TRACKING_URI` when a non-default tracking destination is needed.

The notebook invokes `src/models/train_gold_model.py`; it does not contain a
second training implementation. The four models, hyperparameters,
chronological 80/20 split, experiment name, and lowest-RMSE selection remain
the same as local training.

## Manual archive guidance

Drive synchronization is deliberately manual. After reviewing a run:

1. Confirm the release folder contains the model, feature list, comparison CSV,
   and manifest.
2. Compare the manifest dataset hash with the intended gold snapshot.
3. Optionally archive `mlflow.db`, `mlruns/`, or `mlartifacts/` under
   `experiments/mlflow-archives/`.
4. Keep credentials, `.env`, and email/API secrets out of Drive release
   folders.

Do not treat a Drive folder as the live local workspace. Local pipeline runs
continue to use repository-relative data and artifact paths by default.

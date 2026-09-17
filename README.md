# PowerFlow

PowerFlow is an end-to-end electricity-market data and machine-learning project for exploring German-Luxembourg day-ahead prices, system load, generation mix, weather conditions, price forecasts, and anomalous market events.

The primary pipeline collects historical ENTSO-E and Open-Meteo data, builds silver and gold datasets, validates them, compares four regression models, tracks experiments with MLflow, and produces CSV artifacts consumed by a Streamlit dashboard.

## Problem

Electricity prices are influenced by demand, conventional and renewable generation, weather, seasonality, and recent price behavior. PowerFlow creates a reproducible workflow for:

- collecting these inputs from public APIs;
- aligning quarter-hourly and hourly observations;
- producing model-ready forecasting features;
- comparing forecasting models using a chronological holdout set;
- identifying unusual price/load observations; and
- presenting the generated results in an interactive dashboard.

PowerFlow is currently a historical analytics and forecasting project. It is not a live trading system, market-execution engine, or production model-serving service.

## Architecture

```text
ENTSO-E API                    Open-Meteo Archive API
(DE_LU price/load/generation)  (Berlin weather)
             \                 /
              data/raw/
                  |
       Silver cleaning and alignment
                  |
 data/processed/silver_electricity_market_data.csv
                  |
     Gold feature engineering and target creation
                  |
      data/features/gold_model_features.csv
                  |
 Linear Regression | Random Forest | Gradient Boosting | XGBoost
                  |
       Lowest training-only time-series CV RMSE selected
                  |
    MLflow tracking + local model/report artifacts
                  |
           Streamlit dashboard
```

Prefect defines the stage order, retries ingestion tasks, runs silver and gold validation, records pipeline success or failure in SQLite, writes operational logs, and invokes the existing email failure notification when configured.

## Primary ENTSO-E pipeline

The active flow is `PowerFlow ENTSO-E Pipeline` in `src/scheduled_pipeline.py`. It runs these stages sequentially:

1. Fetch ENTSO-E day-ahead price, load, and generation data.
2. Fetch Open-Meteo historical weather data.
3. Build the silver dataset.
4. Validate the silver dataset.
5. Build the gold feature dataset.
6. Validate the gold dataset.
7. Train and compare four forecasting models.
8. Generate the actual-versus-predicted report.
9. Detect market anomalies.
10. Generate feature importance.

The Prefect deployment is intentionally unscheduled because the ingestion performs a configured historical backfill rather than a recurring incremental update. Legacy EIA/California scripts are retained under `src/legacy/` for reference but are not part of the primary Prefect flow.

## Technologies

- Python and pandas for ingestion and transformation
- ENTSO-E Transparency Platform API via `entsoe-py`
- Open-Meteo Archive API
- scikit-learn and XGBoost
- MLflow with a local SQLite tracking store
- Prefect 3 for orchestration
- Streamlit and Plotly for the dashboard
- SQLite for pipeline and data-quality history
- Matplotlib for generated report images
- Docker and Docker Compose for local services

## Repository structure

```text
.
├── artifacts/               Generated current-model artifacts and policy notes
├── data/                    Raw, silver, gold, reports, backups, and sample data
├── database/
│   └── schema.sql           Tracked SQLite schema
├── docs/                    External storage and workflow guidance
├── models/                  Legacy locally generated model files
├── notebooks/               Optional Google Colab training entry point
├── src/
│   ├── ingestion/           ENTSO-E and Open-Meteo ingestion
│   ├── processing/          Silver and gold dataset construction
│   ├── models/              Training, prediction reports, anomalies, importance
│   ├── legacy/              Retained EIA-era pipeline and old dashboard
│   ├── notifications/       Failure email notification
│   ├── orchestration/       Local ENTSO-E flow entry point
│   ├── utils/               File/console logging
│   ├── dashboard.py         Current CSV-backed Streamlit dashboard
│   ├── scheduled_pipeline.py
│   ├── store_data.py        SQLite run and quality history
│   └── validate_data.py     Legacy, silver, and gold validation
├── docker-compose.yml
├── prefect.yaml
├── pytest.ini
├── requirements-dev.txt
├── tests/                   Lightweight offline tests for current behavior
└── requirements.txt
```

See [`data/README.md`](data/README.md) and [`artifacts/README.md`](artifacts/README.md) for storage details.

## Development setup

The Docker image uses Python 3.12. A local virtual environment with Python 3.12 is recommended.

```bash
git clone https://github.com/ianwambaire/Electricity_Trading_Pipeline.git
cd Electricity_Trading_Pipeline

python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For local test development, install the additional test dependency:

```bash
python -m pip install -r requirements-dev.txt
```

On Windows PowerShell, activate the environment with:

```powershell
venv\Scripts\Activate.ps1
```

## Environment variables

Create a local environment file from the safe template:

```bash
cp .env.example .env
```

Then replace the placeholders locally. Never commit `.env`.

| Variable | Purpose |
|---|---|
| `ENTSOE_API_KEY` | Required by the primary ENTSO-E ingestion stage |
| `POWERFLOW_HISTORY_START_DATE` | Optional inclusive history start; defaults to `2019-01-01` |
| `POWERFLOW_HISTORY_END_DATE` | Optional inclusive history end; defaults to `2025-09-30` |
| `EIA_API_KEY` | Used only by retained legacy EIA ingestion scripts |
| `ALERT_EMAIL_SENDER` | Optional Gmail sender for failure notifications |
| `ALERT_EMAIL_PASSWORD` | Optional Gmail app password |
| `ALERT_EMAIL_RECEIVER` | Optional failure-notification recipient |

If the email variables are absent, the existing notification function skips sending email.

## Running PowerFlow

Run commands from the repository root with the virtual environment activated.

### 1. Start Prefect

In one terminal:

```bash
prefect server start --host 127.0.0.1
```

In a second terminal:

```bash
source venv/bin/activate
export PREFECT_API_URL=http://127.0.0.1:4200/api
```

### 2. Run the full ENTSO-E pipeline

```bash
python src/orchestration/run_entsoe_pipeline.py
```

The command invokes the same Prefect flow referenced by `prefect.yaml`. It requires API access and can take several minutes. Model training can create substantial local MLflow artifacts.

Individual dataset validation can be run without writing quality results:

```bash
python src/validate_data.py silver --no-log
python src/validate_data.py gold --no-log
```

Run the lightweight offline test suite with:

```bash
python -m pytest
```

The suite uses temporary databases and generated in-memory samples. It does not
call external APIs, retrain models, or modify the active datasets and database.

### 3. Run the Streamlit dashboard

The dashboard reads generated silver, gold, prediction, anomaly, and feature-importance CSVs. Run the pipeline first when those ignored files are not present.

```bash
streamlit run src/dashboard.py
```

Open `http://localhost:8501`.

### 4. Run the MLflow UI

```bash
mlflow server \
  --backend-store-uri sqlite:///mlflow.db \
  --host 127.0.0.1 \
  --port 5000
```

Open `http://localhost:5000`. The primary trainer writes to the `electricity-price-forecasting-entsoe` experiment.

### 5. Create a Prefect deployment

The deployment uses the existing `electricity-pool` work pool and has no schedule. Because its pull step clones GitHub `main`, deployment runs only see committed and pushed code.

```bash
prefect work-pool create --type process electricity-pool
prefect deploy --name powerflow-entsoe-pipeline
prefect worker start --pool electricity-pool
```

The work-pool creation command is needed only when the pool does not already exist. API keys must be available in the worker environment.

### Docker services

```bash
docker compose up --build
```

Docker Compose starts the dashboard on port `8501`, MLflow on host port `5001`, and a Prefect server on port `4200`. It does not start a Prefect worker or automatically execute the pipeline.

## Data sources

### ENTSO-E Transparency Platform

The primary ingestion script requests the Germany-Luxembourg bidding zone (`DE_LU`). The shared default historical range is `2019-01-01` through `2025-09-30`, inclusive, using UTC boundaries, and can be overridden with command-line arguments or the `POWERFLOW_HISTORY_START_DATE` and `POWERFLOW_HISTORY_END_DATE` environment variables. ENTSO-E requests use continuous, non-overlapping six-month windows to remain below the client's annual query boundary. The default ends before the Single Day-Ahead Coupling switched from hourly to 15-minute market time units on `2025-10-01`; extending beyond that date requires an explicit hourly price-aggregation decision that is outside the current processing logic.

- day-ahead electricity prices;
- actual electricity load; and
- generation by production type.

Germany's nuclear series has no populated ENTSO-E observations after `2023-04-15 23:45 Europe/Berlin`. The first null hour begins at local midnight on `2023-04-16`, equivalent to `2023-04-15 22:00 UTC`; this explains the two null hourly observations that appear before `2023-04-16` when judged by UTC calendar date. The pipeline preserves the feature and applies its documented zero-generation treatment from that local shutdown boundary rather than dropping it.

### Open-Meteo

The primary weather ingestion uses the same configurable UTC range and six-month chunks for hourly historical observations at the Berlin coordinates. Open-Meteo is requested in UTC so the repeated autumn local hour remains two distinct real hours and DST cannot create gaps in the joined timeline:

- temperature;
- relative humidity;
- wind speed;
- cloud cover; and
- shortwave radiation.

The repository also retains an earlier California EIA/Open-Meteo pipeline, but it is not the primary PowerFlow flow.

## Data layers

### Raw

`data/raw/` contains direct ENTSO-E and Open-Meteo extracts. ENTSO-E load and generation inputs may be quarter-hourly; they are converted to UTC before hourly aggregation. Silver validation requires unique, strictly increasing timestamps at exact one-hour UTC intervals.

### Silver

`data/processed/silver_electricity_market_data.csv` contains an hourly, timestamp-aligned join of price, load, selected generation categories, and weather variables.

### Gold

`data/features/gold_model_features.csv` adds calendar fields, price/load lags, rolling statistics, renewable-generation measures, renewable share, and the next-hour price target. Rows created with incomplete lag, rolling, or target values are removed.

## Modeling

The current trainer compares:

- Linear Regression
- Random Forest Regressor
- Gradient Boosting Regressor
- XGBoost Regressor

Rows are ordered by timestamp and split chronologically: the first 80% is used
for model development and the final 20% is kept as the final holdout test set.
The training portion uses three-fold `TimeSeriesSplit` evaluation without
shuffling. Linear Regression remains an untuned baseline; Random Forest,
Gradient Boosting, and XGBoost each use a six-candidate randomized search over a
small parameter space. The holdout is evaluated only after training-only tuning
is complete. The model family with the lowest cross-validation RMSE is selected
from the development partition; final holdout metrics are reporting-only.

### Evaluation metrics

- **MAE — Mean Absolute Error:** average absolute forecast error.
- **RMSE — Root Mean Squared Error:** error measure that penalizes larger misses more heavily; cross-validation RMSE is used for model-family selection, while holdout RMSE is reported only for final evaluation.
- **R² — Coefficient of determination:** proportion of target variance explained by the model on the test set.

MLflow records tuning status, best parameters, CV RMSE, final test metrics,
training/testing row counts, dataset version, Git SHA, and one serialized model
artifact per candidate run. Local CSV reports record the four-model comparison
and prediction results.

### Expanding-window backtesting

Before tuned model selection, the standalone backtest compares three forecasting
baselines and the four untuned model families across calendar-year validation
periods. Period boundaries use the timestamp of the forecast target, not merely
the feature row timestamp:

- train through 2021 and validate on 2022;
- expand training through 2022 and validate on 2023; and
- expand training through 2023 and validate on 2024.

Targets from `2025-01-01` onward remain excluded as the final chronological
holdout. Run the backtest independently of the Prefect training pipeline:

```bash
PYTHONPATH=src python src/models/run_backtest.py
```

The command writes `data/reports/backtest_model_comparison.csv` and
`data/reports/backtest_model_aggregate.csv`. It fits untuned models only and
does not run `RandomizedSearchCV`.

For research diagnostics, run the cumulative feature-ablation and market-regime
experiment separately:

```bash
PYTHONPATH=src python src/models/run_feature_ablation.py
```

It uses the same expanding 2022–2024 development folds, excludes all 2025
targets, and fits the same untuned model configurations. Generated reports cover
feature-group performance, negative/normal/high/extreme price regimes, and
development-period target distributions by year.

### Dataset and model version metadata

Every completed training cycle writes
`artifacts/models/training_manifest.json`. The manifest records:

- the exact gold dataset SHA-256 and deterministic
  `gold-sha256-<digest>` version;
- the gold source date range and row count;
- feature, chronological training, and test row counts;
- the selected model and its MAE, RMSE, and R²;
- the selection method, CV method and split count, and selected hyperparameters;
- the selected model's MLflow run ID; and
- the current Git commit SHA when Git metadata is available.

The dataset version hashes the existing gold CSV; it does not create another
dataset copy. The existing selected-model paths remain unchanged for local
pipeline compatibility. MLflow runs hold candidate models, while the manifest
connects the selected local artifact to its data and experiment metadata.

Run only the existing training stage with default local paths:

```bash
PYTHONPATH=src python src/models/train_gold_model.py
```

Optional path arguments support supplied gold datasets and release folders:

```bash
PYTHONPATH=src python src/models/train_gold_model.py \
  --data-path /path/to/gold_model_features.csv \
  --output-dir /path/to/model-release \
  --comparison-path /path/to/model-release/gold_model_comparison.csv \
  --mlflow-tracking-uri sqlite:///mlflow.db
```

The models, hyperparameters, chronological 80/20 split, MLflow experiment
name, and lowest-time-series-CV-RMSE selection are identical in both commands.

### Optional Colab training

[`notebooks/colab_training.ipynb`](notebooks/colab_training.ipynb) clones or
updates the repository, installs its dependencies, optionally mounts Google
Drive, validates a supplied gold dataset path, and invokes the existing trainer.
Drive is disabled by default and is never required for local development.

Configure the notebook's `SUPPLIED_GOLD_DATA_PATH`, `USE_GOOGLE_DRIVE`,
`DRIVE_PROJECT_ROOT`, and `RELEASE_NAME` values before running it top-to-bottom.
See [`docs/google_drive_workflow.md`](docs/google_drive_workflow.md) for the
recommended manual archive and release layout.

## Storage and version control

PowerFlow separates reviewable source assets from reproducible runtime outputs.

| Location | Intended contents |
|---|---|
| GitHub | Source code, configuration, schema, documentation, `.env.example`, and small representative sample data |
| Local storage | Active raw/silver/gold data, SQLite databases, MLflow working data, generated reports, logs, virtual environments, and current development artifacts |
| Google Drive | Archived large datasets, dated snapshots, selected release models, MLflow archives/backups, and final artifact backups |

Secrets and generated/heavy files are excluded through `.gitignore`. `database/schema.sql`, configuration files, and dependency definitions remain tracked.

### Intentionally untracked generated files

A fresh clone normally will not contain:

- `.env`;
- `database/electricity_trading.db` and `mlflow.db`;
- `mlruns/` and `mlartifacts/`;
- `data/raw/`, `data/processed/`, `data/features/`, `data/final/`, `data/reports/`, `data/external/`, and `data/backups/` outputs;
- `artifacts/models/*.joblib` and `models/*.pkl`;
- generated CSV/PNG reports;
- `logs/`; or
- local virtual environments and caches.

The pipeline regenerates its active data and model products. Large snapshots or selected release artifacts may be archived outside Git in Google Drive.

The recommended Drive hierarchy is:

```text
PowerFlow/
├── datasets/
│   ├── snapshots/
│   └── archives/
├── models/
│   └── releases/
├── experiments/
│   └── mlflow-archives/
└── backups/
```

Drive upload and synchronization remain manual; no Drive API credentials or
personal Drive paths are stored in the repository.

## Current status

- ENTSO-E and Open-Meteo ingestion share a configurable historical range, defaulting to `2019-01-01` through `2025-09-30`.
- Silver and gold construction and validation are implemented.
- Four-model comparison, MLflow tracking, best-model selection, reporting, anomaly detection, and feature importance are implemented.
- Training produces deterministic dataset identity and selected-model manifest metadata.
- Optional Colab training reuses the active trainer and can write reviewed release artifacts to a configurable Drive folder.
- The current Streamlit dashboard reads the generated ENTSO-E CSV products.
- The Prefect flow and unscheduled deployment configuration are defined; a Prefect API server is required to execute the flow.
- SQLite stores pipeline-run and data-quality history.
- Legacy EIA/SQLite pipeline files remain in the repository but are not deleted or used by the primary Prefect orchestration.
- Generated datasets and artifacts remain local and are intentionally excluded from Git.

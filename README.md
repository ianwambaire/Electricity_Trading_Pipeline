# PowerFlow

PowerFlow is an end-to-end electricity-market data and machine-learning project for exploring German-Luxembourg day-ahead prices, system load, generation mix, weather conditions, price forecasts, and anomalous market events.

The primary pipeline collects historical ENTSO-E and Open-Meteo data, builds and validates silver and gold datasets, verifies the frozen final model release, and produces prediction and analytics artifacts consumed by a Streamlit dashboard. Model-development experiments remain available as separate commands but are no longer part of the recurring Prefect flow.

## Problem

Electricity prices are influenced by demand, conventional and renewable generation, weather, seasonality, and recent price behavior. PowerFlow creates a reproducible workflow for:

- collecting these inputs from public APIs;
- aligning quarter-hourly and hourly observations;
- producing model-ready forecasting features;
- comparing forecasting models using a chronological holdout set;
- identifying unusual price/load observations; and
- presenting the generated results in an interactive dashboard.

PowerFlow is a historical analytics and forecasting project with incremental source updates. It is not a live trading system, market-execution engine, or low-latency model-serving service.

## Architecture

```text
ENTSO-E API                    Open-Meteo Archive API
(DE_LU price/load/generation)  (Berlin weather)
             \                 /
              local data/raw/ ── optional durable sync ── S3 raw/
                  |
       Silver cleaning and alignment
                  |
 data/processed/silver_electricity_market_data.csv
                  |
     Gold feature engineering and target creation
                  |
      data/features/gold_model_features.csv
                  |
 Frozen StandardScaler → Ordinary Linear Regression release
                  |
       Prediction and analytics reports
                  |
           Streamlit dashboard
                  |
       S3 silver/, gold/, reports/, models/releases/
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
7. Verify the frozen final model and its ordered 31-feature contract.
8. Generate the actual-versus-predicted report.
9. Detect market anomalies.
10. Generate feature importance.

The flow supports `historical` mode for a reproducible full rebuild and `incremental` mode for operational updates. Incremental ingestion advances each raw source from its own latest stored UTC timestamp, atomically appends non-conflicting observations, and treats publication-delay no-ops as successful runs. Silver and Gold are then rebuilt from the complete raw history so lag and rolling features remain correct across the old/new boundary. The deployment runs incremental mode hourly in UTC. Legacy EIA/California scripts are retained under `src/legacy/` for reference but are not part of the primary Prefect flow.

## Technologies

- Python and pandas for ingestion and transformation
- ENTSO-E Transparency Platform API via `entsoe-py`
- Open-Meteo Archive API
- scikit-learn and XGBoost
- MLflow with a local SQLite tracking store
- Prefect 3 for orchestration
- Streamlit and Plotly for the dashboard
- SQLite for pipeline and data-quality history
- Amazon S3 via boto3 for optional durable artifact storage
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
├── requirements-prod.txt    Minimal Python 3.14 EC2 runtime dependencies
├── tests/                   Lightweight offline tests for current behavior
└── requirements.txt
```

See [`data/README.md`](data/README.md) and [`artifacts/README.md`](artifacts/README.md) for storage details.

## Development setup

Local development and the EC2 runtime use Python 3.14. The existing Docker image
currently remains on Python 3.12.

```bash
git clone https://github.com/ianwambaire/Electricity_Trading_Pipeline.git
cd Electricity_Trading_Pipeline

python3.14 -m venv venv
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

### EC2 production installation

Production hosts do not need the research, model-selection, MLflow, notebook, or
XGBoost stack. On the Amazon Linux 2023 EC2 host, install the minimal Python 3.14
runtime instead. The production dependency set pins Prefect 3.7.5:

```bash
python3.14 -m venv .venv-prod
source .venv-prod/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r requirements-prod.txt
python scripts/check_production_imports.py
```

The production set supports Prefect orchestration, both ingestion sources,
Silver/Gold processing, frozen scikit-learn inference, S3 synchronization,
reports, anomaly detection, feature importance, Streamlit, SQLite metadata, and
optional SMTP alerts. It intentionally excludes XGBoost and therefore does not
pull CUDA or NCCL packages. `pyarrow` is not a direct PowerFlow dependency; pip
may install it transitively for Streamlit.

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
| `POWERFLOW_STORAGE_BACKEND` | `local` (default) or `s3` |
| `POWERFLOW_S3_BUCKET` | Required in S3 mode; durable PowerFlow bucket name |
| `AWS_REGION` | AWS region; defaults to `us-east-1` |
| `PREFECT_SERVER_DATABASE_CONNECTION_URL` | Prefect's PostgreSQL URL; use `postgresql+asyncpg://` and a URL-encoded password |
| `POWERFLOW_LOCAL_STORAGE_ROOT` | Optional root used by the standalone local storage adapter; defaults to `.` |
| `EIA_API_KEY` | Used only by retained legacy EIA ingestion scripts |
| `ALERT_EMAIL_SENDER` | Optional Gmail sender for failure notifications |
| `ALERT_EMAIL_PASSWORD` | Optional Gmail app password |
| `ALERT_EMAIL_RECEIVER` | Optional failure-notification recipient |

If the email variables are absent, the existing notification function skips sending email.

AWS credentials are never stored in PowerFlow configuration. S3 mode uses boto3's
standard credential provider chain, so local runs can use an AWS profile or environment,
and a future EC2 host can use an instance role. Never add access keys to `.env` or Git.

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

The default is the operational incremental mode. The equivalent explicit command is:

```bash
python src/orchestration/run_entsoe_pipeline.py --mode incremental
```

Local mode remains the default and performs no cloud calls:

```bash
POWERFLOW_STORAGE_BACKEND=local python src/orchestration/run_entsoe_pipeline.py --mode incremental
```

S3 mode keeps the same local working files and business logic, then uploads only
successfully written/validated artifacts at each stage:

```bash
POWERFLOW_STORAGE_BACKEND=s3 \
POWERFLOW_S3_BUCKET=powerflow-data-ian-2026-870755688674-us-east-1-an \
AWS_REGION=us-east-1 \
python src/orchestration/run_entsoe_pipeline.py --mode incremental
```

`--storage-backend local|s3` is available as a one-run override. Uploads use a
temporary object followed by a server-side copy, carry a SHA-256 content marker,
and skip unchanged objects. An upload failure fails the affected pipeline stage,
is recorded in run/data-quality metadata, and does not alter the valid local file.

Verify bucket read/write/delete access with a disposable monitoring object:

```bash
POWERFLOW_STORAGE_BACKEND=s3 python src/storage/check_s3.py
```

Idempotently migrate existing artifacts (missing optional artifacts are skipped):

```bash
POWERFLOW_STORAGE_BACKEND=s3 python src/storage/sync_existing.py
# Or selected groups:
POWERFLOW_STORAGE_BACKEND=s3 python src/storage/sync_existing.py raw silver gold
```

The durable object layout is:

| Local artifact | S3 object |
|---|---|
| `data/raw/entsoe/prices.csv` | `raw/entsoe/prices/prices.csv` |
| `data/raw/entsoe/load.csv` | `raw/entsoe/load/load.csv` |
| `data/raw/entsoe/generation.csv` | `raw/entsoe/generation/generation.csv` |
| `data/raw/weather/open_meteo_weather.csv` | `raw/weather/open_meteo_weather.csv` |
| Silver / Gold CSVs | `silver/silver_electricity_market_data.csv`, `gold/gold_model_features.csv` |
| Prediction reports | `reports/predictions/` |
| Anomaly reports | `reports/anomalies/` |
| Feature-importance monitoring reports | `reports/monitoring/` |
| Frozen model, feature list, manifest, optional final reports | `models/releases/` |

Run a reproducible full rebuild with the configured historical range using:

```bash
python src/orchestration/run_entsoe_pipeline.py --mode historical
```

Historical start/end overrides remain available with `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`. Both modes invoke the same Prefect flow referenced by `prefect.yaml`, use the frozen release artifacts, and never rerun model tuning or the one-time final holdout evaluation.

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

### 5. Persistent EC2 production deployment

Production runs execute directly from
`/home/ec2-user/Electricity_Trading_Pipeline`. The Prefect deployment deliberately
has no git-clone pull step: raw, Silver, Gold, `.env`, SQLite, and frozen model
files persist in that checkout and are excluded from Git. Its process-worker job
sets this same directory explicitly, runs incremental mode with the S3 backend,
has a concurrency limit of one, and is scheduled hourly at minute zero in UTC.

The application operational database remains
`database/electricity_trading.db` (SQLite). PostgreSQL 15 stores only Prefect's
internal orchestration state. Install and initialize it on Amazon Linux 2023
before installing the PowerFlow services:

```bash
sudo dnf install -y postgresql15 postgresql15-server postgresql15-contrib
sudo postgresql-setup --initdb --unit postgresql
sudo systemctl enable --now postgresql.service
sudo systemctl status postgresql.service
```

Run `postgresql-setup` only for a new, uninitialized PostgreSQL data directory.
Keep PostgreSQL local to the instance: set `listen_addresses = 'localhost'` in
`/var/lib/pgsql/data/postgresql.conf`, and ensure the matching entries in
`/var/lib/pgsql/data/pg_hba.conf` use password authentication only on loopback
(place specific rules before broader host rules):

```text
host    prefect    prefect    127.0.0.1/32    scram-sha-256
host    prefect    prefect    ::1/128         scram-sha-256
```

Create the dedicated role, database, and required `pg_trgm` extension without
placing a password in shell history:

```bash
sudo -u postgres psql
```

Then enter the following in `psql`; `\password` prompts securely:

```text
CREATE ROLE prefect LOGIN;
\password prefect
CREATE DATABASE prefect OWNER prefect;
\connect prefect
CREATE EXTENSION IF NOT EXISTS pg_trgm;
\quit
```

After any PostgreSQL configuration edit, restart and confirm that port 5432 is
listening only on loopback:

```bash
sudo systemctl restart postgresql.service
sudo ss -ltnp | grep ':5432'
```

Do not add an EC2 security-group or host-firewall inbound rule for port 5432.

After pulling reviewed code, install the production dependencies and protect the
environment file:

```bash
cd /home/ec2-user/Electricity_Trading_Pipeline
python3.14 -m venv .venv-prod
source .venv-prod/bin/activate
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r requirements-prod.txt
chmod 600 .env
python scripts/check_production_imports.py
```

Add the Prefect database setting to `.env` using the password entered above.
Special characters in the password must be URL-encoded; never paste the real
value into a tracked file:

```dotenv
PREFECT_SERVER_DATABASE_CONNECTION_URL=postgresql+asyncpg://prefect:URL_ENCODED_PASSWORD@127.0.0.1:5432/prefect
PREFECT_API_URL=http://127.0.0.1:4200/api
```

PowerFlow S3 settings belong in the same protected `.env`. AWS credentials do
not: boto3 and the AWS CLI obtain short-lived credentials from the EC2 instance
role.

Bootstrap missing working datasets and frozen release files from S3. This is
idempotent and preserves every existing file by default:

```bash
chmod +x scripts/bootstrap_ec2_data.sh scripts/setup_prefect_ec2.sh
./scripts/bootstrap_ec2_data.sh
```

Use `./scripts/bootstrap_ec2_data.sh --force` only for an intentional restore
from the current durable S3 copies. Downloads are written to temporary files and
renamed only after the AWS CLI succeeds. Authentication comes from the EC2 IAM
role; no AWS key is stored by the script.

Install the supplied services, start the loopback-only Prefect server, and apply
the Prefect work pool/deployment before starting the worker. The Prefect server
unit explicitly requires `postgresql.service` and also waits for PostgreSQL to
accept loopback connections before it starts:

```bash
sudo install -o root -g root -m 0644 deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable postgresql.service powerflow-prefect-server.service \
  powerflow-prefect-worker.service powerflow-streamlit.service
sudo systemctl start powerflow-prefect-server.service
./scripts/setup_prefect_ec2.sh
sudo systemctl start powerflow-prefect-worker.service powerflow-streamlit.service
```

The setup script waits for `http://127.0.0.1:4200/api/health`, creates the
`electricity-pool` process pool only when absent, and reapplies
`powerflow-entsoe-pipeline` safely. Run it again after changing `prefect.yaml`.

Inspect service state and live logs with:

```bash
sudo systemctl status powerflow-prefect-server.service \
  powerflow-prefect-worker.service powerflow-streamlit.service
sudo journalctl -u powerflow-prefect-server.service -f
sudo journalctl -u powerflow-prefect-worker.service -f
sudo journalctl -u powerflow-streamlit.service -f
```

Verify the local databases, API, work pool, and deployment without exposing the
database password:

```bash
sudo systemctl is-active postgresql.service powerflow-prefect-server.service \
  powerflow-prefect-worker.service powerflow-streamlit.service
sudo -u postgres psql -d prefect -tAc \
  "SELECT current_database(), current_setting('listen_addresses');"
sudo -u postgres psql -d prefect -tAc \
  "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm';"
curl --fail --silent http://127.0.0.1:4200/api/health
.venv-prod/bin/prefect config view | grep DATABASE_CONNECTION_URL
.venv-prod/bin/prefect work-pool inspect electricity-pool
.venv-prod/bin/prefect deployment inspect \
  'PowerFlow ENTSO-E Pipeline/powerflow-entsoe-pipeline'
```

The Prefect configuration command masks secret settings. Its database connection
must resolve to PostgreSQL; the API health response should be `true`.

Prefect is bound only to `127.0.0.1:4200`. Streamlit listens on port `8501` on
all interfaces; allow inbound TCP 8501 in the EC2 security group only from the
intended operator/network, then open `http://EC2_PUBLIC_IP:8501`.

For routine service operations:

```bash
sudo systemctl restart powerflow-prefect-server.service \
  powerflow-prefect-worker.service powerflow-streamlit.service
sudo systemctl stop powerflow-prefect-worker.service powerflow-streamlit.service
sudo systemctl start powerflow-prefect-worker.service powerflow-streamlit.service
```

To stop the EC2 host cleanly, use `sudo shutdown -h now` and then stop/start the
instance through AWS. After a reboot, the enabled services start automatically.
Verify them with `systemctl status`; rerun `bootstrap_ec2_data.sh` only when local
working files are missing, and rerun `setup_prefect_ec2.sh` only when the pool or
deployment needs to be restored or updated.

Before the final reboot-persistence test, audit resource usage and IAM-backed S3
access. These reads do not modify production objects:

```bash
df -h
free -h
swapon --show
aws sts get-caller-identity
for prefix in raw silver gold reports models/releases; do
  aws s3 ls "s3://powerflow-data-ian-2026-870755688674-us-east-1-an/${prefix}/" \
    --recursive --human-readable --summarize
done
```

Once configuration is final, reboot with `sudo reboot`, reconnect, and rerun the
service, API, Prefect, disk, memory, swap, and S3 read-only checks above. Review
recent errors with `journalctl -p warning --since boot` and the three PowerFlow
service logs. Source-continuity warnings are expected operational warnings; do
not fill missing upstream intervals or force a run by changing the data.

### Docker services

```bash
docker compose up --build
```

Docker Compose starts the dashboard on port `8501`, MLflow on host port `5001`, and a Prefect server on port `4200`. It does not start a Prefect worker or automatically execute the pipeline.

## Data sources

### ENTSO-E Transparency Platform

The primary ingestion script requests the Germany-Luxembourg bidding zone (`DE_LU`). Historical mode defaults to `2019-01-01` through `2025-09-30`, inclusive, using UTC boundaries, and can be overridden with command-line arguments or the `POWERFLOW_HISTORY_START_DATE` and `POWERFLOW_HISTORY_END_DATE` environment variables. Incremental mode starts each raw request immediately after that source's latest timestamp and stops at the latest completed UTC hour. ENTSO-E requests use continuous, non-overlapping six-month windows. Since day-ahead prices moved to 15-minute market time units on `2025-10-01`, Silver uses the arithmetic mean of all four available quarter-hour prices for each UTC hour and excludes incomplete post-transition hours.

- day-ahead electricity prices;
- actual electricity load; and
- generation by production type.

Germany's nuclear series has no populated ENTSO-E observations after `2023-04-15 23:45 Europe/Berlin`. The first null hour begins at local midnight on `2023-04-16`, equivalent to `2023-04-15 22:00 UTC`; this explains the two null hourly observations that appear before `2023-04-16` when judged by UTC calendar date. The pipeline preserves the feature and applies its documented zero-generation treatment from that local shutdown boundary rather than dropping it.

### Open-Meteo

The primary weather ingestion uses the same configurable UTC range and six-month chunks for hourly historical observations at the Berlin coordinates. Incremental requests use a conservative five-day archive publication delay; an hourly pipeline run with no newly published weather data succeeds without rewriting stored files. Open-Meteo is requested in UTC so the repeated autumn local hour remains two distinct real hours and DST cannot create gaps in the joined timeline:

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

The focused development-tuning experiment evaluates regularized and robust
linear models alongside the strongest feature configuration for each tree-model
family:

```bash
PYTHONPATH=src python src/models/run_focused_tuning.py
```

Scaling is contained inside each linear model's scikit-learn pipeline and is fit
only on the applicable expanding training window. Hyperparameters and the final
development winner are selected using aggregate 2022–2024 RMSE. Targets from
2025 remain untouched. Coefficient diagnostics use standardized coefficients
and report feature correlation as a warning against causal interpretation.

After the model design is frozen, the one-time release command trains Ordinary
Linear Regression with the Full PowerFlow feature set on targets before 2025 and
evaluates the 2025 final holdout:

```bash
PYTHONPATH=src python src/models/run_final_holdout_evaluation.py
```

The command writes separate final-release reports and artifacts and refuses to
run again once `artifacts/models/final_model_release_manifest.json` exists. The
2025 results are for final reporting only and are not used for tuning, feature
selection, or model-family selection.

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

- ENTSO-E and Open-Meteo support both the configurable historical rebuild and source-watermarked incremental ingestion.
- Silver and gold construction and validation are implemented.
- Model-development comparisons and MLflow tracking are retained as separate research workflows; the primary pipeline now uses the frozen final Ordinary Linear Regression release for prediction and coefficient-based feature influence reporting.
- Training produces deterministic dataset identity and selected-model manifest metadata.
- Optional Colab training reuses the active trainer and can write reviewed release artifacts to a configurable Drive folder.
- The current Streamlit dashboard reads the generated ENTSO-E CSV products.
- The Prefect deployment runs the incremental flow hourly in UTC; a Prefect API server and worker are required to execute deployments.
- SQLite stores pipeline-run and data-quality history.
- Legacy EIA/SQLite pipeline files remain in the repository but are not deleted or used by the primary Prefect orchestration.
- Generated datasets and artifacts remain local and are intentionally excluded from Git.

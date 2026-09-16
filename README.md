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
       Lowest chronological test RMSE selected
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

The Prefect deployment is intentionally unscheduled because the current ingestion scripts use fixed historical date ranges. Legacy EIA/California scripts remain in the repository for reference but are not part of the primary Prefect flow.

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
├── models/                  Legacy locally generated model files
├── src/
│   ├── ingestion/           ENTSO-E and Open-Meteo ingestion
│   ├── processing/          Silver and gold dataset construction
│   ├── models/              Training, prediction reports, anomalies, importance
│   ├── notifications/       Failure email notification
│   ├── orchestration/       Local ENTSO-E flow entry point
│   ├── utils/               File/console logging
│   ├── dashboard.py         Current CSV-backed Streamlit dashboard
│   ├── scheduled_pipeline.py
│   ├── store_data.py        SQLite run and quality history
│   └── validate_data.py     Legacy, silver, and gold validation
├── docker-compose.yml
├── prefect.yaml
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

The primary ingestion script currently requests the Germany-Luxembourg bidding zone (`DE_LU`) for fixed historical dates from January 2022 through January 2025:

- day-ahead electricity prices;
- actual electricity load; and
- generation by production type.

### Open-Meteo

The primary weather ingestion requests hourly historical observations for Berlin from January 2022 through December 2024:

- temperature;
- relative humidity;
- wind speed;
- cloud cover; and
- shortwave radiation.

The repository also retains an earlier California EIA/Open-Meteo pipeline, but it is not the primary PowerFlow flow.

## Data layers

### Raw

`data/raw/` contains direct ENTSO-E and Open-Meteo extracts. ENTSO-E load and generation inputs may be quarter-hourly.

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

Rows are ordered by timestamp and split chronologically: the first 80% is used for training and the final 20% for testing. The model with the lowest test RMSE is saved as the best model.

### Evaluation metrics

- **MAE — Mean Absolute Error:** average absolute forecast error.
- **RMSE — Root Mean Squared Error:** error measure that penalizes larger misses more heavily; used for best-model selection.
- **R² — Coefficient of determination:** proportion of target variance explained by the model on the test set.

MLflow records model parameters, training/testing row counts, metrics, and serialized model artifacts. Local CSV reports record the four-model comparison and prediction results.

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

## Current status

- ENTSO-E and Open-Meteo ingestion are implemented for the fixed historical range.
- Silver and gold construction and validation are implemented.
- Four-model comparison, MLflow tracking, best-model selection, reporting, anomaly detection, and feature importance are implemented.
- The current Streamlit dashboard reads the generated ENTSO-E CSV products.
- The Prefect flow and unscheduled deployment configuration are defined; a Prefect API server is required to execute the flow.
- SQLite stores pipeline-run and data-quality history.
- Legacy EIA/SQLite pipeline files remain in the repository but are not deleted or used by the primary Prefect orchestration.
- Generated datasets and artifacts remain local and are intentionally excluded from Git.

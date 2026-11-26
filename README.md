[Open the deployed PowerFlow application](https://powerflowenergy.dev)

# PowerFlow: Electricity Market Analytics and Price Forecasting

PowerFlow brings electricity-market data, weather, price forecasts, and operational monitoring into one application. It focuses on the **Germany-Luxembourg bidding zone (DE_LU)** and helps analysts explore market conditions, inspect unusual events, and assess forecast reliability.

The project combines a reproducible Python data pipeline with machine-learning models, a read-only FastAPI service, and a React dashboard. A Streamlit dashboard is also retained. Prices are expressed in **EUR/MWh**, and pipeline timestamps use **UTC**.

## Problem and purpose

Electricity-price analysis requires demand, generation, weather, and price observations to be aligned across different publication schedules and time resolutions. Missing intervals and delayed inputs can also make a forecast appear more current than its underlying data.

PowerFlow addresses this practical problem by collecting and validating these sources, producing consistent hourly features, evaluating forecasts against simple baselines, and showing data freshness alongside results. Its contribution is an integrated, inspectable analytics workflow for this market.

### Objectives

1. Collect and align electricity prices, load, generation, and weather in a validated hourly dataset.
2. Engineer forecasting features and compare models using chronological evaluation that protects future observations from training.
3. Present market trends, forecasts, anomalies, and model evidence through an accessible dashboard.
4. Track pipeline health, source freshness, and realized forecast errors to support informed human review.

### Scope

The system supports market research and decision support. Trade execution, automated bidding, and profitability evaluation are outside its scope. Results apply to the studied market and evaluation periods; they do not establish performance in other markets.

## What the application provides

| Area | Purpose |
|---|---|
| Market overview | Summarize price, demand, generation, and recent market conditions |
| Forecasting | Inspect the next 24 hourly price predictions and separate historical one-hour evaluation |
| Market analytics | Explore historical prices, load, generation, and weather |
| Anomaly detection | Review flagged unusual market observations |
| Model insights | Inspect model identity, evaluation metrics, and feature influence |
| Pipeline operations | Review source freshness, quality checks, run history, and incidents |
| Account access | Use configured Cognito sign-in and server-verified roles for protected features |

Availability depends on configured access and the reports present in the deployment. Missing or stale inputs are identified explicitly; a retained forecast is not evidence of a fresh forecast.

## How it works

```text
ENTSO-E: DE_LU prices, load, generation     Open-Meteo: Berlin weather
                       \                    /
                            Raw data
                               |
                  Silver: cleaned hourly observations
                               |
                  Gold: features and next-hour target
                               |
              Frozen models and forecasting reports
                               |
                FastAPI -> React dashboard
                       -> Streamlit dashboard

       Prefect: orchestration | SQLite: operational history
                   Amazon S3: durable storage
```

1. **Ingest:** Retrieve historical data or append newly published observations using a separate timestamp watermark for each source.
2. **Clean and validate:** Align observations in UTC, check duplicates and hourly continuity, and build the Silver dataset. Complete sets of four quarter-hour prices are averaged into hourly prices after the October 2025 market transition.
3. **Engineer features:** Build 31 model inputs covering calendar patterns, recent prices and load, lagged values, rolling statistics, generation, renewable share, and weather.
4. **Predict and report:** Verify frozen model releases, generate forecasts, detect anomalies, and record feature influence and realized errors.
5. **Serve and monitor:** Expose reports through FastAPI and dashboards while recording pipeline runs, quality checks, incidents, and stage durations.

The Prefect deployment is configured for incremental execution at **45 minutes past each hour, UTC**. Routine inference does not retrain the models. Research and model-selection commands run separately.

## Data and methodology

**Market data:** ENTSO-E prices, actual load, and generation by production type for DE_LU. The default historical rebuild covers 1 January 2019 to 30 September 2025; dates are configurable.

**Weather:** Open-Meteo historical hourly weather at Berlin coordinates: temperature, relative humidity, wind speed, cloud cover, and shortwave radiation. This single location is a simplified representation of weather across the market.

**Data layers:** Raw extracts are retained under `data/raw/`, aligned observations under `data/processed/`, engineered features under `data/features/`, and generated outputs under `data/reports/`. See the [data guide](data/README.md) and [artifact policy](artifacts/README.md).

### Forecasting models

| Model release | Role | Evaluation approach |
|---|---|---|
| Ordinary Linear Regression with scaling | Frozen one-hour forecast and historical evaluation | Expanding development folds for 2022-2024; final holdout in 2025 |
| Histogram Gradient Boosting with 24 direct outputs | Separate next-24-hour forecast | Training targets before January 2026; validation before May 2026; test issue times from May 2026 |

Development workflows also compare Random Forest, Gradient Boosting, and XGBoost. Model selection uses development data; final holdout results are reserved for reporting. The 24-hour workflow matches targets by their exact future UTC timestamps and prevents labels from crossing split boundaries.

Operational 24-hour inference checks recent market history and obtains matching issue-hour weather from Open-Meteo's Forecast API. It records weather provenance separately from historical observations. Future weather at horizons +1 to +24 is not used. If required inputs are missing or stale, issuance is withheld and the previous valid report is preserved with its original timestamps.

### Recorded evaluation results

The frozen one-hour release was evaluated on **6,552 hourly targets from 1 January to 30 September 2025**, after training on targets before 2025.

| Approach | MAE (EUR/MWh) | RMSE (EUR/MWh) | R² |
|---|---:|---:|---:|
| Ordinary Linear Regression | 10.79 | 18.89 | 0.879 |
| Persistence: repeat the known price | 14.44 | 23.54 | 0.813 |
| Daily seasonal naive | 26.03 | 40.52 | 0.445 |

The model reduced RMSE by **19.76% against persistence** on this holdout. The separate 24-hour release records test MAE of **31.12 EUR/MWh** and RMSE of **44.18 EUR/MWh**, compared with persistence RMSE of **88.01 EUR/MWh**. These releases use different horizons and test periods, so their scores should be interpreted separately.

MAE measures average absolute error; RMSE gives greater weight to large errors; R² measures explained target variation. Values come from the generated `final_holdout_metrics.csv`, `final_holdout_baselines.csv`, and `next24h_release_manifest.json`. Generated reports and model binaries may be absent from a fresh clone. These are recorded offline evaluation results, not a claim about current production accuracy.

## Technology

- **Data and models:** Python 3.14, pandas, scikit-learn, XGBoost, MLflow.
- **Application:** React, TypeScript, Vite, Tailwind CSS, Recharts, FastAPI; retained Streamlit and Plotly dashboard.
- **Operations:** Prefect 3, SQLite, Amazon S3, EC2, Nginx, and Cognito.
- **Development:** pytest, frontend tests, GitHub Actions, and Docker Compose.

## Run locally

### 1. Install and configure

```bash
git clone https://github.com/ianwambaire/Electricity_Trading_Pipeline.git
cd Electricity_Trading_Pipeline
python3.14 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

On Windows PowerShell, activate with `venv\Scripts\Activate.ps1`.

Set `ENTSOE_API_KEY` in `.env` before ingestion. Use the template for optional S3 storage, alerts, and authentication settings. Keep credentials out of version control. The React application also needs the public Cognito configuration described in the [frontend guide](frontend/README.md); public client settings do not replace backend authorization.

A fresh clone does not include working datasets, operational databases, or every trained model. Ingestion needs network access and an ENTSO-E key. The recurring flow also requires the approved frozen models and feature contracts described in the [artifact policy](artifacts/README.md). Restore approved release artifacts before running inference; collecting data alone does not create those releases.

### 2. Prepare data and run the pipeline

Start Prefect in one terminal:

```bash
source venv/bin/activate
prefect server start --host 127.0.0.1
```

In another terminal with the virtual environment active:

```bash
export PREFECT_API_URL=http://127.0.0.1:4200/api
python src/orchestration/run_entsoe_pipeline.py --mode historical
```

The historical command uses the configured date range. For subsequent updates:

```bash
python src/orchestration/run_entsoe_pipeline.py --mode incremental
```

Local storage is the default. Optional `--start-date`, `--end-date`, and `--storage-backend local|s3` arguments are documented in the [technical reference](docs/technical_reference.md).

### 3. Start the application

Run the read-only API from the repository root:

```bash
PYTHONPATH=src python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Use the [API authentication guide](docs/api_authentication.md) to configure protected endpoints. In a separate terminal:

```bash
cd frontend
npm ci
npm run dev -- --host localhost --port 5175 --strictPort
```

Open [localhost:5175](http://localhost:5175). The development server proxies `/api` requests to FastAPI. Reports must exist for their corresponding views to show data.

To use the retained Streamlit dashboard instead:

```bash
streamlit run src/dashboard.py
```

## Testing

Run backend checks from the repository root with the virtual environment active:

```bash
python -m pytest -q --release-gating
```

Run frontend checks from `frontend/`:

```bash
npm test
npm run lint
npm run build
```

Tests cover data and forecast contracts, freshness handling, API behavior, authorization, and interface behavior. The [CI workflow](.github/workflows/ci.yml) defines checks for pushes and pull requests to `main`, including isolated runtime checks and protected model hashes. CI configuration alone does not establish that a particular deployment passed; inspect the relevant workflow run and release evidence.

## Deployment and reproducibility

The application URL is [powerflowenergy.dev](https://powerflowenergy.dev). The repository includes EC2/Nginx deployment configuration, separate API and orchestration dependencies, and backup and recovery procedures.

- [API deployment](docs/api_ec2_deployment.md): installation, service configuration, HTTPS routing, validation, and rollback.
- [Production recovery](docs/production_recovery_runbook.md): backups, restoration, and presentation evidence.
- [API authentication](docs/api_authentication.md): identity settings and server-side access rules.
- [Technical reference](docs/technical_reference.md): extended pipeline, storage, model-development, and operational commands retained from the previous README.

Use `main` as the final release source and record the deployed commit or release tag with the submitted evidence. This README does not assert a currently deployed Git commit. Model manifests provide a separate record of model identity, feature order, dataset metadata, and evaluation. The research, API, and orchestration dependency files support their respective environments; consult the deployment guide before installing production services.

## Repository layout

```text
frontend/             React application and frontend tests
src/api/              Read-only FastAPI service
src/ingestion/        ENTSO-E and Open-Meteo collection
src/processing/       Silver and Gold dataset construction
src/models/           Research, frozen-model inference, and reports
src/monitoring/       Operational monitoring
src/scheduled_pipeline.py  Primary Prefect flow
data/                 Data layers, samples, and generated reports
artifacts/            Model releases, manifests, and artifact policy
database/             SQLite schema
tests/                Backend and pipeline tests
docs/                 Setup, security, deployment, and recovery guides
deploy/               Deployment configuration and review records
notebooks/            Optional Colab training workflow
```

Legacy EIA/California code remains under `src/legacy/` for reference. It is separate from the active DE_LU pipeline.

## Limitations and future work

Forecast errors are larger during extreme-price events. Source gaps and publication delays can prevent fresh issuance. Operational issue-hour weather differs from the historical weather used in development, and Berlin weather provides limited geographic coverage. Feature influence describes model associations rather than causal effects.

Future work should evaluate extreme-price performance, wider weather coverage, and issue-time weather forecasts under controlled chronological comparisons. Longer production monitoring should assess realized error and weather-source calibration before any model replacement. Model review and promotion remain controlled steps.

## Access and licence

The hosted workspace uses configured account access; no shared credentials are published here. Reviewers need repository access, an authorized application account where required, and approved data/model artifacts to reproduce the full system. No repository-wide licence file is currently included; reuse permissions should be clarified with the author. Upstream data remains subject to its providers' terms.

## Author Oversight and Use of AI-Assisted Tools

OpenAI Codex assisted with restructuring and refining this README. Project descriptions and numerical results were checked against repository code, configuration, reports, and model manifests. The project author remains responsible for reviewing the documentation and the submitted work.

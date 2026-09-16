import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from prefect import flow, task

from notifications.email_alert import send_failure_alert
from store_data import initialize_database, log_pipeline_run
from utils.logger import get_logger
from validate_data import (
    GOLD_DATA_PATH,
    SILVER_DATA_PATH,
    validate_gold_data,
    validate_silver_data,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def _ensure_runtime_directories():
    for relative_path in [
        "data/raw/entsoe",
        "data/raw/weather",
        "data/processed",
        "data/features",
        "data/reports",
        "artifacts/models",
    ]:
        (PROJECT_ROOT / relative_path).mkdir(parents=True, exist_ok=True)


def _run_script(stage_name: str, script_path: str):
    logger.info("Starting stage: %s", stage_name)

    environment = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path
        if not existing_python_path
        else os.pathsep.join([source_path, existing_python_path])
    )
    environment.setdefault("MPLBACKEND", "Agg")

    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / script_path)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )

    logger.info("Completed stage: %s", stage_name)


@task(name="Fetch ENTSO-E electricity data", retries=2, retry_delay_seconds=10)
def entsoe_ingestion_task():
    _run_script("ENTSO-E ingestion", "src/ingestion/fetch_entsoe_data.py")


@task(name="Fetch Open-Meteo weather data", retries=2, retry_delay_seconds=10)
def weather_ingestion_task():
    _run_script("Open-Meteo weather ingestion", "src/ingestion/fetch_weather_data.py")


@task(name="Build silver dataset")
def build_silver_task():
    _run_script("Silver dataset creation", "src/processing/build_silver_dataset.py")


@task(name="Validate silver dataset")
def validate_silver_task() -> int:
    logger.info("Starting stage: Silver dataset validation")
    data = pd.read_csv(SILVER_DATA_PATH, low_memory=False)

    if not validate_silver_data(data):
        raise ValueError("ENTSO-E silver dataset validation failed.")

    logger.info("Completed stage: Silver dataset validation (%s rows)", len(data))
    return len(data)


@task(name="Build gold dataset")
def build_gold_task():
    _run_script("Gold dataset creation", "src/processing/build_gold_dataset.py")


@task(name="Validate gold dataset")
def validate_gold_task() -> int:
    logger.info("Starting stage: Gold dataset validation")
    data = pd.read_csv(GOLD_DATA_PATH, low_memory=False)

    if not validate_gold_data(data):
        raise ValueError("ENTSO-E gold dataset validation failed.")

    logger.info("Completed stage: Gold dataset validation (%s rows)", len(data))
    return len(data)


@task(name="Train and select forecasting model")
def train_model_task():
    _run_script("Four-model training", "src/models/train_gold_model.py")


@task(name="Generate actual-vs-predicted report")
def prediction_report_task():
    _run_script(
        "Actual-vs-predicted report generation",
        "src/models/prediction_visualization.py",
    )


@task(name="Detect market anomalies")
def anomaly_detection_task():
    _run_script("Anomaly detection", "src/models/anomaly_detection.py")


@task(name="Generate feature importance report")
def feature_importance_task():
    _run_script("Feature importance generation", "src/models/feature_importance.py")


@flow(name="PowerFlow ENTSO-E Pipeline", log_prints=True)
def powerflow_entsoe_pipeline():
    stage_name = "Runtime directory initialization"
    records_processed = 0

    logger.info("PowerFlow ENTSO-E pipeline started.")

    try:
        _ensure_runtime_directories()

        stage_name = "ENTSO-E ingestion"
        entsoe_ingestion_task()

        stage_name = "Open-Meteo weather ingestion"
        weather_ingestion_task()

        stage_name = "Silver dataset creation"
        build_silver_task()

        stage_name = "Silver dataset validation"
        records_processed = validate_silver_task()

        stage_name = "Gold dataset creation"
        build_gold_task()

        stage_name = "Gold dataset validation"
        records_processed = validate_gold_task()

        stage_name = "Four-model training"
        train_model_task()

        stage_name = "Actual-vs-predicted report generation"
        prediction_report_task()

        stage_name = "Anomaly detection"
        anomaly_detection_task()

        stage_name = "Feature importance generation"
        feature_importance_task()

        stage_name = "Pipeline run-history logging"
        initialize_database()
        log_pipeline_run(
            status="SUCCESS",
            records_processed=records_processed,
            message="PowerFlow ENTSO-E pipeline completed successfully.",
        )
        logger.info(
            "PowerFlow ENTSO-E pipeline completed successfully (%s gold rows).",
            records_processed,
        )

    except Exception as error:
        message = (
            f"PowerFlow ENTSO-E pipeline failed during '{stage_name}': {error}"
        )
        logger.exception(message)

        try:
            initialize_database()
            log_pipeline_run(
                status="FAILED",
                records_processed=records_processed,
                message=message,
            )
        except Exception:
            logger.exception("Unable to record the failed pipeline run in SQLite.")

        send_failure_alert(
            subject="PowerFlow ENTSO-E Pipeline Failed",
            message=(
                f"Failed stage: {stage_name}\n\n"
                f"Error details:\n{error}\n\n"
                f"Records processed before failure: {records_processed}\n\n"
                "Check logs/pipeline.log and Prefect for details."
            ),
        )
        raise


if __name__ == "__main__":
    powerflow_entsoe_pipeline()

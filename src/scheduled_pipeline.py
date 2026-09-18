import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from prefect import flow, task

from ingestion.fetch_entsoe_data import fetch_entsoe_data, latest_generation_timestamp
from ingestion.fetch_weather_data import fetch_open_meteo_weather
from ingestion.incremental_utils import latest_stored_timestamp
from models.final_model_runtime import load_final_model_release
from models.prediction_visualization import run_prediction_report
from notifications.email_alert import send_failure_alert
from store_data import (
    initialize_database,
    log_data_quality_result,
    log_pipeline_run,
)
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
def entsoe_ingestion_task(mode: str, start_date=None, end_date=None):
    logger.info("Starting stage: ENTSO-E %s ingestion", mode)
    metadata = fetch_entsoe_data(start_date, end_date, mode=mode)
    logger.info("Completed stage: ENTSO-E %s ingestion", mode)
    return metadata


@task(name="Fetch Open-Meteo weather data", retries=2, retry_delay_seconds=10)
def weather_ingestion_task(mode: str, start_date=None, end_date=None):
    logger.info("Starting stage: Open-Meteo %s ingestion", mode)
    metadata = fetch_open_meteo_weather(start_date, end_date, mode=mode)
    logger.info("Completed stage: Open-Meteo %s ingestion", mode)
    return metadata


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


@task(name="Verify frozen final model release")
def verify_final_model_release_task() -> int:
    logger.info("Starting stage: Frozen final model verification")
    _, features = load_final_model_release(
        PROJECT_ROOT / "artifacts/models/final_gold_model.joblib",
        PROJECT_ROOT / "artifacts/models/final_gold_model_features.joblib",
    )
    logger.info(
        "Completed stage: Frozen final model verification (%s features)",
        len(features),
    )
    return len(features)


@task(name="Generate actual-vs-predicted report")
def prediction_report_task(mode: str) -> int:
    logger.info("Starting stage: Actual-vs-predicted report generation")
    count = run_prediction_report(mode)
    logger.info(
        "Completed stage: Actual-vs-predicted report generation (%s new rows)",
        count,
    )
    return count


@task(name="Detect market anomalies")
def anomaly_detection_task():
    _run_script("Anomaly detection", "src/models/anomaly_detection.py")


@task(name="Generate feature importance report")
def feature_importance_task():
    _run_script("Feature importance generation", "src/models/feature_importance.py")


def _latest_timestamp(relative_path: str):
    path = PROJECT_ROOT / relative_path
    if relative_path.endswith("data/raw/entsoe/generation.csv"):
        return latest_generation_timestamp(path)
    return latest_stored_timestamp(path)


def _raw_row_counts():
    paths = {
        "prices": PROJECT_ROOT / "data/raw/entsoe/prices.csv",
        "load": PROJECT_ROOT / "data/raw/entsoe/load.csv",
        "generation": PROJECT_ROOT / "data/raw/entsoe/generation.csv",
        "weather": PROJECT_ROOT / "data/raw/weather/open_meteo_weather.csv",
    }
    counts = {}
    for source, path in paths.items():
        if not path.exists():
            counts[source] = 0
            continue
        timestamps = pd.read_csv(path, usecols=["timestamp"])["timestamp"]
        counts[source] = int(
            pd.to_datetime(timestamps, errors="coerce", utc=True).notna().sum()
        )
    return counts


def _raw_watermark():
    timestamps = [
        _latest_timestamp("data/raw/entsoe/prices.csv"),
        _latest_timestamp("data/raw/entsoe/load.csv"),
        _latest_timestamp("data/raw/entsoe/generation.csv"),
        _latest_timestamp("data/raw/weather/open_meteo_weather.csv"),
    ]
    available = [timestamp for timestamp in timestamps if timestamp is not None]
    return min(available) if available else None


def _entsoe_unresolved_gaps(entsoe_metadata):
    return {
        dataset_name: dataset_metadata["unresolved_gap"]
        for dataset_name, dataset_metadata in entsoe_metadata.get(
            "datasets", {}
        ).items()
        if dataset_metadata.get("unresolved_gap") is not None
    }


def _record_gap_warnings(unresolved_gaps):
    if not unresolved_gaps:
        return
    initialize_database()
    for dataset_name, gap in unresolved_gaps.items():
        log_data_quality_result(
            check_name=f"entsoe_incremental_continuity:{dataset_name}",
            status="WARNING",
            message=json.dumps(gap, sort_keys=True),
        )


def _operational_metadata(
    mode,
    new_rows,
    predictions,
    status,
    unresolved_gaps=None,
):
    raw_timestamps = {
        "prices": _latest_timestamp("data/raw/entsoe/prices.csv"),
        "load": _latest_timestamp("data/raw/entsoe/load.csv"),
        "generation": _latest_timestamp("data/raw/entsoe/generation.csv"),
        "weather": _latest_timestamp("data/raw/weather/open_meteo_weather.csv"),
    }
    available_raw = [value for value in raw_timestamps.values() if value is not None]
    raw_watermark = min(available_raw) if available_raw else None

    def formatted(value):
        return value.isoformat() if value is not None else None

    return {
        "mode": mode,
        "run_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "latest_raw_timestamp": formatted(raw_watermark),
        "latest_raw_by_source": {
            key: formatted(value) for key, value in raw_timestamps.items()
        },
        "latest_complete_price_hour": (
            raw_timestamps["prices"].floor("h").isoformat()
            if raw_timestamps["prices"] is not None
            else None
        ),
        "latest_silver_timestamp": formatted(
            _latest_timestamp("data/processed/silver_electricity_market_data.csv")
        ),
        "latest_gold_timestamp": formatted(
            _latest_timestamp("data/features/gold_model_features.csv")
        ),
        "new_rows_ingested": int(new_rows),
        "predictions_generated": int(predictions),
        "unresolved_source_gaps": unresolved_gaps or {},
        "status": status,
    }


@flow(name="PowerFlow ENTSO-E Pipeline", log_prints=True)
def powerflow_entsoe_pipeline(
    mode: str = "incremental",
    start_date: str | None = None,
    end_date: str | None = None,
):
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be 'historical' or 'incremental'.")
    if mode == "incremental" and (start_date is not None or end_date is not None):
        raise ValueError("start_date/end_date are supported only in historical mode.")

    stage_name = "Runtime directory initialization"
    records_processed = 0
    new_rows_ingested = 0
    predictions_generated = 0
    raw_rows_before = {}
    unresolved_gaps = {}
    raw_watermark_before = None

    logger.info("PowerFlow ENTSO-E pipeline started in %s mode.", mode)

    try:
        _ensure_runtime_directories()
        raw_rows_before = _raw_row_counts()
        raw_watermark_before = _raw_watermark()

        stage_name = "ENTSO-E ingestion"
        entsoe_metadata = entsoe_ingestion_task(mode, start_date, end_date)
        unresolved_gaps = _entsoe_unresolved_gaps(entsoe_metadata)
        _record_gap_warnings(unresolved_gaps)

        stage_name = "Open-Meteo weather ingestion"
        weather_metadata = weather_ingestion_task(mode, start_date, end_date)
        raw_rows_after = _raw_row_counts()
        if mode == "incremental":
            new_rows_ingested = sum(
                max(0, raw_rows_after[source] - raw_rows_before[source])
                for source in raw_rows_after
            )
        else:
            new_rows_ingested = int(entsoe_metadata["new_rows"]) + int(
                weather_metadata["new_rows"]
            )

        raw_watermark_after = _raw_watermark()
        complete_watermark_advanced = (
            raw_watermark_after is not None
            and (
                raw_watermark_before is None
                or raw_watermark_after > raw_watermark_before
            )
        )
        if mode == "incremental" and not complete_watermark_advanced:
            stage_name = "Pipeline run-history logging"
            initialize_database()
            metadata = _operational_metadata(
                mode,
                new_rows_ingested,
                0,
                "SUCCESS",
                unresolved_gaps,
            )
            metadata["message"] = (
                "No complete aligned raw hour advanced; derived datasets "
                "were left unchanged."
            )
            log_pipeline_run(
                status="SUCCESS",
                records_processed=new_rows_ingested,
                message=json.dumps(metadata, sort_keys=True),
            )
            logger.info(metadata["message"])
            return metadata

        stage_name = "Silver dataset creation"
        build_silver_task()

        stage_name = "Silver dataset validation"
        records_processed = validate_silver_task()

        stage_name = "Gold dataset creation"
        build_gold_task()

        stage_name = "Gold dataset validation"
        records_processed = validate_gold_task()

        stage_name = "Frozen final model verification"
        verify_final_model_release_task()

        stage_name = "Actual-vs-predicted report generation"
        predictions_generated = prediction_report_task(mode)

        stage_name = "Anomaly detection"
        anomaly_detection_task()

        stage_name = "Feature importance generation"
        feature_importance_task()

        stage_name = "Pipeline run-history logging"
        initialize_database()
        metadata = _operational_metadata(
            mode,
            new_rows_ingested,
            predictions_generated,
            "SUCCESS",
            unresolved_gaps,
        )
        metadata["message"] = "PowerFlow ENTSO-E pipeline completed successfully."
        log_pipeline_run(
            status="SUCCESS",
            records_processed=records_processed,
            message=json.dumps(metadata, sort_keys=True),
        )
        logger.info(
            "PowerFlow ENTSO-E pipeline completed successfully (%s gold rows).",
            records_processed,
        )

    except Exception as error:
        if mode == "incremental" and raw_rows_before:
            try:
                current_raw_rows = _raw_row_counts()
                new_rows_ingested = sum(
                    max(0, current_raw_rows[source] - raw_rows_before[source])
                    for source in current_raw_rows
                )
            except Exception:
                logger.exception(
                    "Unable to calculate raw-row changes for the failed run."
                )
        message = (
            f"PowerFlow ENTSO-E pipeline failed during '{stage_name}': {error}"
        )
        logger.exception(message)

        try:
            initialize_database()
            metadata = _operational_metadata(
                mode,
                new_rows_ingested,
                predictions_generated,
                "FAILED",
                unresolved_gaps,
            )
            metadata["failed_stage"] = stage_name
            metadata["message"] = message
            log_pipeline_run(
                status="FAILED",
                records_processed=records_processed,
                message=json.dumps(metadata, sort_keys=True),
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


def parse_args():
    parser = argparse.ArgumentParser(description="Run the PowerFlow Prefect flow.")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        default="incremental",
    )
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    powerflow_entsoe_pipeline(
        mode=arguments.mode,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
    )

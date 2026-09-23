import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from prefect import flow, task

from ingestion.fetch_entsoe_data import fetch_entsoe_data, latest_generation_timestamp
from ingestion.fetch_weather_data import fetch_open_meteo_weather
from ingestion.incremental_utils import latest_stored_timestamp
from models.final_model_runtime import load_final_model_release
from models.next24h_monitoring import update_next24h_monitoring
from models.next24h_production import (
    ForecastUnavailableError,
    load_next24h_release,
    run_next24h_forecast,
)
from models.prediction_visualization import run_prediction_report
from notifications.email_alert import (
    DEFAULT_ALERT_COOLDOWN_HOURS,
    alert_cooldown_hours,
    failure_fingerprint,
    sanitize_failure_message,
    send_failure_alert,
)
from store_data import (
    failure_alert_cooldown_active,
    incident_is_active,
    initialize_database,
    log_data_quality_result,
    log_incident,
    log_pipeline_run,
    log_stage_timing,
)
from storage import StorageConfig, StorageSync
from utils.logger import get_logger
from validate_data import (
    GOLD_DATA_PATH,
    SILVER_DATA_PATH,
    validate_gold_data,
    validate_silver_data,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_incident(*args, **kwargs) -> bool:
    """Observability failure must not replace the pipeline's primary outcome."""
    try:
        initialize_database()
        return log_incident(*args, **kwargs)
    except Exception:
        logger.exception("Unable to record PowerFlow operational incident.")
        return False


def _send_incident_failure_alert(
    *,
    component: str,
    category: str,
    subject: str,
    message: str,
    fingerprint_message: str | None = None,
) -> str:
    """Send a new/expired incident alert without hiding repeated occurrences."""
    safe_message = sanitize_failure_message(message)
    fingerprint = failure_fingerprint(
        component,
        category,
        fingerprint_message if fingerprint_message is not None else safe_message,
    )
    try:
        cooldown = alert_cooldown_hours()
    except ValueError:
        cooldown = DEFAULT_ALERT_COOLDOWN_HOURS
        logger.warning(
            "Invalid POWERFLOW_ALERT_COOLDOWN_HOURS; using %.0f hours.",
            cooldown,
        )
    try:
        initialize_database()
        cooldown_active = failure_alert_cooldown_active(fingerprint, cooldown)
    except Exception:
        logger.exception("Unable to evaluate failure-alert cooldown; alert will be attempted.")
        cooldown_active = False
    if cooldown_active:
        logger.info("Duplicate failure alert suppressed; cooldown active")
        _record_incident(
            "INFO",
            "email alerts",
            "failure_alert_suppressed",
            "RECORDED",
            "Duplicate failure alert suppressed; cooldown active.",
            {"fingerprint": fingerprint, "cooldown_hours": cooldown},
            dedupe_minutes=0,
        )
        return "SUPPRESSED"

    result = send_failure_alert(subject, safe_message)
    if result == "SENT":
        logger.info("Failure alert sent")
        _record_incident(
            "INFO", "email alerts", "failure_alert_sent", "RECORDED",
            "Failure alert sent.",
            {"fingerprint": fingerprint, "cooldown_hours": cooldown},
            dedupe_minutes=0,
        )
    elif result == "FAILED":
        _record_incident(
            "ERROR", "email alerts", "email_alert_failed", "ACTIVE",
            "Failure alert email could not be delivered.",
            {"fingerprint": fingerprint},
            dedupe_minutes=0,
        )
    return result


def _timed_stage(run_id: str | None, stage_name: str, operation, *args, **kwargs):
    if run_id is None:
        return operation(*args, **kwargs)
    started_at = _utc_now()
    started_clock = time.perf_counter()
    status = "SUCCESS"
    try:
        return operation(*args, **kwargs)
    except ForecastUnavailableError:
        status = "WITHHELD"
        raise
    except Exception:
        status = "FAILED"
        raise
    finally:
        try:
            log_stage_timing(
                run_id, stage_name, started_at, _utc_now(),
                time.perf_counter() - started_clock, status,
            )
        except Exception:
            logger.exception("Unable to record timing for %s.", stage_name)


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


@task(name="Verify next24h production release")
def verify_next24h_release_task() -> str:
    _, _, manifest = load_next24h_release()
    return manifest["release_id"]


@task(name="Generate next24h production forecast")
def next24h_forecast_task() -> tuple[str, bool, dict]:
    forecast, changed = run_next24h_forecast()
    return forecast["forecast_issue_time"].iloc[0], changed, forecast.attrs["provenance"]


@task(name="Monitor next24h realized forecast errors")
def next24h_monitoring_task() -> tuple[int, int]:
    return update_next24h_monitoring()


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
        _record_incident(
            "WARNING", "ENTSO-E", "source_gap", "ACTIVE",
            f"ENTSO-E {dataset_name} has {gap.get('missing_count', 'unknown')} missing source intervals.",
            {
                "source": dataset_name,
                "first_unresolved_timestamp": gap.get("first_unresolved_timestamp"),
                "missing_count": gap.get("missing_count"),
                "affected_hours": gap.get("affected_hours", []),
            },
        )


def _record_protected_generation_conflicts(generation_metadata, storage_state) -> int:
    count = int(generation_metadata.get("protected_conflicts", 0))
    by_column = generation_metadata.get("protected_conflicts_by_column", {})
    storage_state["generation_protected_conflicts"] = count
    storage_state["generation_protected_conflicts_by_column"] = by_column
    if not count:
        return 0
    details = {
        "count": count,
        "affected_columns": sorted(by_column),
        "by_column": by_column,
        "first_timestamp": generation_metadata.get(
            "protected_conflict_first_timestamp"
        ),
        "last_timestamp": generation_metadata.get(
            "protected_conflict_last_timestamp"
        ),
    }
    warning = (
        f"Ignored {count} protected historical ENTSO-E revision(s) outside "
        "the permitted revision window; stored value retained."
    )
    logger.warning(warning)
    storage_state["warnings"].append(warning)
    _record_incident(
        "WARNING",
        "ENTSO-E generation",
        "protected_historical_revision",
        "ACTIVE",
        warning,
        details,
    )
    return count


def _sync_storage_group(synchronizer, storage_state, group, stage_name):
    try:
        result = synchronizer.sync_group(group)
    except Exception as error:
        storage_state["s3_sync_status"] = "FAILED"
        storage_state["failed_upload_stage"] = stage_name
        warning = f"{stage_name}: {error}"
        storage_state["warnings"].append(warning)
        try:
            initialize_database()
            log_data_quality_result(
                check_name=f"s3_sync:{group}",
                status="FAILED",
                message=warning,
            )
        except Exception:
            logger.exception("Unable to record S3 synchronization failure.")
        raise
    storage_state["objects_uploaded"].extend(result.uploaded)
    storage_state["objects_unchanged"].extend(result.unchanged)
    if synchronizer.config.backend == "s3":
        storage_state["s3_sync_status"] = "SUCCESS"
    return result


def _run_next24h_stages(storage_sync, storage_state, run_id: str | None = None):
    release_id = _timed_stage(
        run_id, "Next24h model verification", verify_next24h_release_task
    )
    storage_state["next24h_model_release"] = release_id
    _sync_storage_group(
        storage_sync, storage_state, "next24h_release", "Next24h model release S3 synchronization"
    )
    try:
        issue_time, changed, provenance = _timed_stage(
            run_id, "Next24h forecast generation", next24h_forecast_task
        )
    except ForecastUnavailableError as error:
        warning = sanitize_failure_message(f"Next24h forecast unavailable: {error}")
        storage_state["next24h_forecast_status"] = "UNAVAILABLE"
        storage_state["warnings"].append(warning)
        initialize_database()
        log_data_quality_result("next24h_forecast_freshness", "WARNING", warning)
        _record_incident(
            "WARNING", "next24h forecast", "forecast_withheld", "ACTIVE",
            warning,
            {"run_id": run_id},
            dedupe_minutes=0,
        )
        _send_incident_failure_alert(
            component="next24h forecast",
            category=type(error).__name__,
            subject="PowerFlow next24h forecast withheld",
            message=warning,
        )
    else:
        storage_state["next24h_forecast_status"] = (
            "GENERATED" if changed else "UNCHANGED"
        )
        storage_state["next24h_forecast_issue_time"] = str(issue_time)
        storage_state["next24h_weather_source"] = provenance["weather_source"]
        storage_state["next24h_weather_acquired_at_utc"] = provenance["weather_acquired_at_utc"]
        try:
            if incident_is_active("next24h forecast", "forecast_withheld"):
                _record_incident(
                    "INFO", "next24h forecast", "forecast_withheld", "RESOLVED",
                    "Next24h forecasting resumed with complete current inputs.",
                )
                log_data_quality_result(
                    "next24h_forecast_freshness", "PASSED",
                    "Next24h forecast issuance resumed with fresh complete inputs.",
                )
        except Exception:
            logger.exception("Unable to inspect prior forecast withholding state.")
        _sync_storage_group(
            storage_sync, storage_state, "next24h_forecasts", "Next24h forecast S3 synchronization"
        )
    realized_count, metric_count = _timed_stage(
        run_id, "Next24h monitoring", next24h_monitoring_task
    )
    storage_state["next24h_realized_pairs"] = realized_count
    storage_state["next24h_performance_rows"] = metric_count
    if (
        (PROJECT_ROOT / "data/reports/next24h_forecast_history.csv").exists()
        and (PROJECT_ROOT / "data/reports/next24h_realized_errors.csv").exists()
    ):
        _sync_storage_group(
            storage_sync, storage_state, "next24h_monitoring", "Next24h monitoring S3 synchronization"
        )


def _operational_metadata(
    mode,
    new_rows,
    predictions,
    status,
    unresolved_gaps=None,
    storage_state=None,
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

    storage_state = storage_state or {
        "storage_backend": "local",
        "s3_bucket": None,
        "s3_sync_status": "NOT_REQUIRED",
        "objects_uploaded": [],
        "objects_unchanged": [],
        "failed_upload_stage": None,
        "warnings": [],
    }
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
        **storage_state,
        "status": status,
    }


def _skip_derived_rebuild(
    mode: str,
    complete_watermark_advanced: bool,
    new_rows_ingested: int,
    source_cells_repaired: int,
    source_cells_revised: int = 0,
) -> bool:
    return (
        mode == "incremental"
        and not complete_watermark_advanced
        and new_rows_ingested == 0
        and source_cells_repaired == 0
        and source_cells_revised == 0
    )


@flow(name="PowerFlow ENTSO-E Pipeline", log_prints=True)
def powerflow_entsoe_pipeline(
    mode: str = "incremental",
    start_date: str | None = None,
    end_date: str | None = None,
    storage_backend: str | None = None,
):
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be 'historical' or 'incremental'.")
    if mode == "incremental" and (start_date is not None or end_date is not None):
        raise ValueError("start_date/end_date are supported only in historical mode.")

    run_id = uuid.uuid4().hex
    total_started_at = _utc_now()
    total_started_clock = time.perf_counter()
    total_status = "FAILED"
    stage_name = "Runtime directory initialization"
    records_processed = 0
    new_rows_ingested = 0
    predictions_generated = 0
    raw_rows_before = {}
    unresolved_gaps = {}
    raw_watermark_before = None

    load_dotenv(PROJECT_ROOT / ".env")
    storage_config = StorageConfig.from_env(storage_backend)
    storage_sync = StorageSync(storage_config, PROJECT_ROOT)
    storage_state = {
        "run_id": run_id,
        "storage_backend": storage_config.backend,
        "s3_bucket": storage_config.s3_bucket,
        "s3_sync_status": "PENDING" if storage_config.backend == "s3" else "NOT_REQUIRED",
        "objects_uploaded": [],
        "objects_unchanged": [],
        "failed_upload_stage": None,
        "warnings": [],
    }

    logger.info("PowerFlow ENTSO-E pipeline started in %s mode.", mode)

    try:
        _ensure_runtime_directories()
        initialize_database()
        raw_rows_before = _raw_row_counts()
        raw_watermark_before = _raw_watermark()

        stage_name = "ENTSO-E ingestion"
        entsoe_metadata = _timed_stage(
            run_id, "ENTSO-E ingestion", entsoe_ingestion_task,
            mode, start_date, end_date,
        )
        generation_metadata = entsoe_metadata.get("datasets", {}).get(
            "generation by type", {}
        )
        source_cells_repaired = int(entsoe_metadata.get("repaired_cells", 0))
        source_cells_revised = int(entsoe_metadata.get("revised_cells", 0))
        generation_cells_repaired = int(
            generation_metadata.get("repaired_cells", 0)
        )
        generation_cells_revised = int(
            generation_metadata.get("revised_cells", 0)
        )
        storage_state["generation_cells_repaired"] = generation_cells_repaired
        storage_state["generation_cells_revised"] = generation_cells_revised
        storage_state["generation_repaired_by_column"] = generation_metadata.get(
            "repaired_by_column", {}
        )
        storage_state["generation_revised_by_column"] = generation_metadata.get(
            "revised_by_column", {}
        )
        _record_protected_generation_conflicts(generation_metadata, storage_state)
        for event_type, count, by_column in (
            ("generation_repair", generation_cells_repaired,
             storage_state["generation_repaired_by_column"]),
            ("generation_revision", generation_cells_revised,
             storage_state["generation_revised_by_column"]),
        ):
            if count:
                verb = "repaired missing cells" if event_type == "generation_repair" else "accepted recent source revisions"
                _record_incident(
                    "INFO", "ENTSO-E generation", event_type, "RECORDED",
                    f"ENTSO-E generation {verb}: {count}.",
                    {"cell_count": count, "by_column": by_column},
                )
        unresolved_gaps = _entsoe_unresolved_gaps(entsoe_metadata)
        _record_gap_warnings(unresolved_gaps)
        storage_state["warnings"].extend(
            f"Unresolved ENTSO-E source gap: {dataset_name}"
            for dataset_name in unresolved_gaps
        )

        stage_name = "ENTSO-E raw S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "raw_entsoe", stage_name)

        stage_name = "Open-Meteo weather ingestion"
        weather_metadata = _timed_stage(
            run_id, "Weather ingestion", weather_ingestion_task,
            mode, start_date, end_date,
        )

        stage_name = "Open-Meteo raw S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "raw_weather", stage_name)
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
        if _skip_derived_rebuild(
            mode, complete_watermark_advanced,
            new_rows_ingested, source_cells_repaired, source_cells_revised,
        ):
            stage_name = "Next24h release and forecast processing"
            _run_next24h_stages(storage_sync, storage_state, run_id)
            stage_name = "Pipeline run-history logging"
            initialize_database()
            metadata = _operational_metadata(
                mode,
                new_rows_ingested,
                0,
                "SUCCESS",
                unresolved_gaps,
                storage_state,
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
            total_status = "SUCCESS"
            return metadata

        stage_name = "Silver dataset creation"
        _timed_stage(run_id, "Silver build", build_silver_task)

        stage_name = "Silver dataset validation"
        records_processed = _timed_stage(
            run_id, "Silver validation", validate_silver_task
        )

        stage_name = "Silver S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "silver", stage_name)

        stage_name = "Gold dataset creation"
        _timed_stage(run_id, "Gold build", build_gold_task)

        stage_name = "Gold dataset validation"
        records_processed = _timed_stage(
            run_id, "Gold validation", validate_gold_task
        )

        stage_name = "Gold S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "gold", stage_name)

        stage_name = "Frozen final model verification"
        _timed_stage(run_id, "One-hour model verification", verify_final_model_release_task)

        stage_name = "Frozen model release S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "model_release", stage_name)

        stage_name = "Actual-vs-predicted report generation"
        predictions_generated = _timed_stage(
            run_id, "Actual-vs-predicted report", prediction_report_task, mode
        )

        stage_name = "Prediction report S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "predictions", stage_name)

        stage_name = "Next24h release and forecast processing"
        _run_next24h_stages(storage_sync, storage_state, run_id)

        stage_name = "Anomaly detection"
        _timed_stage(run_id, "Anomaly detection", anomaly_detection_task)

        stage_name = "Anomaly report S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "anomalies", stage_name)

        stage_name = "Feature importance generation"
        _timed_stage(run_id, "Feature importance", feature_importance_task)

        stage_name = "Monitoring report S3 synchronization"
        _sync_storage_group(storage_sync, storage_state, "monitoring", stage_name)

        stage_name = "Pipeline run-history logging"
        initialize_database()
        metadata = _operational_metadata(
            mode,
            new_rows_ingested,
            predictions_generated,
            "SUCCESS",
            unresolved_gaps,
            storage_state,
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
        total_status = "SUCCESS"
        return metadata

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
        safe_error = sanitize_failure_message(str(error))
        message = sanitize_failure_message(
            f"PowerFlow ENTSO-E pipeline failed during '{stage_name}': {safe_error}"
        )
        logger.exception(message)

        failure_type = "pipeline_stage_failed"
        if "validation" in stage_name.lower():
            failure_type = "data_quality_validation_failed"
        elif "model" in stage_name.lower() and "verification" in stage_name.lower():
            failure_type = "model_verification_failed"
        elif "ingestion" in stage_name.lower():
            failure_type = "ingestion_failed"
        _record_incident(
            "ERROR", "pipeline", failure_type, "ACTIVE",
            f"Pipeline stage failed: {stage_name}.",
            {"run_id": run_id, "stage": stage_name},
        )

        try:
            initialize_database()
            metadata = _operational_metadata(
                mode,
                new_rows_ingested,
                predictions_generated,
                "FAILED",
                unresolved_gaps,
                storage_state,
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

        _send_incident_failure_alert(
            component="pipeline",
            category=f"{failure_type}:{type(error).__name__}",
            subject="PowerFlow ENTSO-E Pipeline Failed",
            message=(
                f"Failed stage: {stage_name}\n\n"
                f"Error details:\n{safe_error}\n\n"
                f"Records processed before failure: {records_processed}\n\n"
                "Check logs/pipeline.log and Prefect for details."
            ),
            fingerprint_message=f"{stage_name}: {safe_error}",
        )
        raise
    finally:
        try:
            log_stage_timing(
                run_id, "Total pipeline", total_started_at, _utc_now(),
                time.perf_counter() - total_started_clock, total_status,
            )
        except Exception:
            logger.exception("Unable to record total pipeline duration.")


def parse_args():
    parser = argparse.ArgumentParser(description="Run the PowerFlow Prefect flow.")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        default="incremental",
    )
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--storage-backend", choices=["local", "s3"])
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    powerflow_entsoe_pipeline(
        mode=arguments.mode,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        storage_backend=arguments.storage_backend,
    )

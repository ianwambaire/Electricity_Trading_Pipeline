"""Allowlisted operational summary. Never publish raw metadata or free text."""
from __future__ import annotations

import csv
import json
import sqlite3
from .database import read_snapshot
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from .market_data import PublicModel


class SourceSummary(PublicModel):
    source: str
    availability: Literal["available", "missing", "invalid", "empty"]
    rows: int | None
    latest_observation: datetime | None
    freshness: str


class QualityCheck(PublicModel):
    timestamp: datetime | None
    check: str
    status: str


class ProductSummary(PublicModel):
    product: str
    status: Literal["available", "missing", "pending_authentication", "restricted"]


class OperationsSummary(PublicModel):
    assessed_at: datetime
    health: str
    explanation: str
    health_rules: str
    latest_run_status: str | None
    latest_run_time: datetime | None
    latest_success_time: datetime | None
    latest_complete_market_hour: datetime | None
    forecast_status: str | None
    forecast_reason: str | None
    forecast_reason_provenance: str = "Public-safe category from latest recorded status/reason; raw operational text is restricted."
    s3_sync_status: str | None
    recent_checks_passed: int | None
    recent_checks_failed: int | None
    recent_checks_warning: int | None
    continuity_warning_sources: int | None
    quality_history: list[QualityCheck]
    sources: list[SourceSummary]
    products: list[ProductSummary]
    incident_evidence: str
    timing_evidence: str
    completeness_note: str = "Raw source watermarks do not establish required-field completeness. Silver coverage describes recorded hours, not present-day input availability."


def _time(value):
    try:
        if not isinstance(value, str):
            return None
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _code(value, choices):
    return value if isinstance(value, str) and value in choices else None


@lru_cache(maxsize=12)
def _csv_summary(path, version):
    if version[1] > 512 * 1024 * 1024:
        raise ValueError("Source size limit")
    count, latest = 0, None
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "timestamp" not in (reader.fieldnames or []):
            raise ValueError("Missing timestamp")
        for row in reader:
            count += 1
            value = _time(row.get("timestamp"))
            if count > 2_000_000 or value is None:
                raise ValueError("Invalid source")
            latest = max(latest, value) if latest else value
    after = path.stat()
    if version != (after.st_mtime_ns, after.st_size):
        raise ValueError("Source changed")
    return count, latest


def operations_summary(settings, forecast_issue=None, forecast_invalid=False):
    # These presentation helpers do not execute jobs, write files, or resolve
    # secrets. Do not call alert_configuration_status from a public endpoint.
    from shared.operational_health import assess_operational_health, source_freshness_state, latest_quality_state
    import pandas as pd

    now = datetime.now(timezone.utc)
    root = settings.public_metadata_root
    if root is None:
        raise HTTPException(503, "Operational summary is not configured.")
    sources = []
    core = {}
    for label, relative, kind in [
        ("Electricity prices", "data/raw/entsoe/prices.csv", "market"),
        ("Electricity load", "data/raw/entsoe/load.csv", "market"),
        ("Generation", "data/raw/entsoe/generation.csv", "market"),
        ("Historical weather", "data/raw/weather/open_meteo_weather.csv", "historical_weather"),
        ("Silver", "data/processed/silver_electricity_market_data.csv", "silver"),
        ("Gold", "data/features/gold_model_features.csv", "gold"),
    ]:
        path = root / relative
        availability, count, latest = "missing", None, None
        try:
            if path.is_file():
                stat = path.stat()
                count, latest = _csv_summary(path, (stat.st_mtime_ns, stat.st_size))
                availability = "available" if count else "empty"
        except (OSError, ValueError, csv.Error):
            availability = "invalid"
        sources.append(SourceSummary(source=label, availability=availability, rows=count, latest_observation=latest,
                                     freshness=source_freshness_state(latest, source_kind=kind, now=now)))
        if kind == "market":
            core[label] = latest
    run = None
    success = None
    checks = None
    tables = set()
    if settings.operational_database.is_file():
        try:
            with read_snapshot(settings.operational_database) as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "pipeline_runs" in tables:
                    run = connection.execute("SELECT run_time, status, message FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
                    success_row = connection.execute("SELECT run_time FROM pipeline_runs WHERE UPPER(status)='SUCCESS' ORDER BY id DESC LIMIT 1").fetchone()
                    success = _time(success_row[0]) if success_row else None
                if "data_quality_results" in tables:
                    checks = connection.execute("SELECT check_time, check_name, status FROM data_quality_results ORDER BY id DESC LIMIT 20").fetchall()
        except sqlite3.Error:
            raise HTTPException(503, "Operational summary is temporarily unavailable.") from None
    try:
        metadata = json.loads(run[2]) if run and isinstance(run[2], str) else {}
        if not isinstance(metadata, dict):
            metadata = {}
    except (ValueError, TypeError):
        metadata = {}
    run_status = _code(run[1], {"SUCCESS", "FAILED", "FAILURE", "ERROR", "RUNNING"}) if run else None
    forecast = _code(metadata.get("next24h_forecast_status"), {"WITHHELD", "UNAVAILABLE", "GENERATED", "UNCHANGED"})
    withheld = forecast in {"WITHHELD", "UNAVAILABLE"}
    reason = None
    if withheld:
        raw_reason = str(metadata.get("next24h_forecast_reason", "")).lower()
        reason = "Required recent Biomass observations are unavailable." if "biomass" in raw_reason else "Forecast withheld: required recent market or weather inputs are unavailable. Detailed reason is not available in this public summary."
    quality = pd.DataFrame(checks or [], columns=["check_time", "check_name", "status"])
    statuses = quality["status"].astype(str).str.upper()
    counts = {"passed": int(statuses.isin(["PASSED", "SUCCESS"]).sum()), "failed": int(statuses.isin(["FAILED", "FAILURE", "ERROR"]).sum()), "warning": int(statuses.eq("WARNING").sum())} if checks is not None else None
    gaps = metadata.get("unresolved_source_gaps")
    gap_count = len(gaps) if isinstance(gaps, dict) else None
    from .model_summaries import model_summaries
    releases = model_summaries(root).models
    required = all(model.metadata_status == "available" and model.artifact_status in {"integrity_verified", "present_not_integrity_verified"} for model in releases)
    health = assess_operational_health(latest_run_status=run_status, latest_success_time=success, core_source_timestamps=core,
                                      forecast_issue_time=forecast_issue, forecast_withheld=withheld, quality_state=latest_quality_state(quality),
                                      unresolved_gap_count=gap_count or 0, required_artifacts_available=required, now=now)
    if health["label"] == "Healthy" and (checks is None or gap_count is None or forecast_invalid):
        health = {"label": "Warning", "reason": "Required quality, continuity, or forecast evidence is unavailable; healthy status cannot be established."}
    names = {"ENTSO-E Silver Required Columns Check": "Silver schema", "ENTSO-E Gold Required Columns Check": "Gold schema", "ENTSO-E Silver Null Check": "Silver missing values", "ENTSO-E Gold Null Check": "Gold missing values", "next24h_forecast_freshness": "Forecast freshness"}
    history = [QualityCheck(timestamp=_time(row[0]), check=names.get(row[1], "Validation check"), status=_code(str(row[2]).upper(), {"PASSED", "SUCCESS", "FAILED", "FAILURE", "ERROR", "WARNING"}) or "UNKNOWN") for row in (checks or [])]
    products = [ProductSummary(product=label, status="available" if (root/relative).is_file() else "missing") for label,relative in [
        ("Silver observations", "data/processed/silver_electricity_market_data.csv"), ("Gold features", "data/features/gold_model_features.csv"),
        ("One-hour release metadata", "artifacts/models/final_model_release_manifest.json"), ("24-hour release metadata", "artifacts/models/releases/next24h/next24h_release_manifest.json"),
        ("One-hour evaluation", "data/reports/final_holdout_metrics.csv"), ("One-hour predictions", "data/reports/actual_vs_predicted.csv"),
        ("24-hour predictions", "data/reports/next24h_forecast.csv"), ("Anomaly report", "data/reports/detected_anomalies.csv")]]
    products.append(ProductSummary(product="Linear feature influence", status="restricted"))
    return OperationsSummary(assessed_at=now, health=health["label"], explanation=health["reason"],
        health_rules="Streamlit display rules: degraded for failed runs/current quality checks, missing releases/core sources, or >6-hour run/core-source age; warning for >2-hour success age, >3-hour source/forecast age, withholding, or continuity warnings. Archive weather is excluded. Unknown evidence never establishes health; this is not an issuance attestation.",
        latest_run_status=run_status, latest_run_time=_time(run[0]) if run else None, latest_success_time=success,
        latest_complete_market_hour=_time(metadata.get("latest_complete_price_hour")), forecast_status=forecast,
        forecast_reason=reason, s3_sync_status=_code(metadata.get("s3_sync_status"), {"SUCCESS", "FAILED", "PENDING", "NOT_REQUIRED", "PARTIAL"}),
        recent_checks_passed=counts["passed"] if counts else None, recent_checks_failed=counts["failed"] if counts else None,
        recent_checks_warning=counts["warning"] if counts else None, continuity_warning_sources=gap_count,
        quality_history=history, sources=sources, products=products,
        incident_evidence="Admin-only recorded evidence" if "operational_incidents" in tables else "Missing local evidence; details require authentication",
        timing_evidence="Admin-only recorded evidence" if "pipeline_stage_timings" in tables else "Missing local evidence; details require authentication")

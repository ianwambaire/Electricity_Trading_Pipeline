"""Bounded allowlisted Admin reports; never publish raw operational JSON."""
from __future__ import annotations
import hashlib
import io
import csv
import json
import math
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import AwareDatetime, Field
from .market_data import PublicModel
from .model_summaries import _summary

Status = Literal["HEALTHY", "DEGRADED", "STALE", "FAILED", "UNKNOWN"]


class AccountResponse(PublicModel):
    subject: str
    role: Literal["Admin", "Analyst"]
    email: str | None = None
    display_name: str | None = None


class SourceDiagnostics(PublicModel):
    source: Literal["ENTSOE_TOTAL_LOAD", "ENTSOE_WIND_SOLAR_DAY_AHEAD", "ENTSOE_WIND_SOLAR_INTRADAY", "ENTSOE_TOTAL_GENERATION", "OPEN_METEO"]
    status: Status
    latest_acquired_at_utc: AwareDatetime | None = None
    expected_target_count: int | None = Field(default=None, ge=0)
    observed_target_count: int | None = Field(default=None, ge=0)
    missing_target_count: int | None = Field(default=None, ge=0)
    duplicate_identity_count: int | None = Field(default=None, ge=0)
    revision_count: int | None = Field(default=None, ge=0)
    consecutive_collection_failures: int | None = Field(default=None, ge=0)
    s3_sync_status: Literal["SUCCESS", "FAILED", "PENDING", "UNKNOWN", "NOT_REQUIRED", "NOT_CONFIGURED", "DISABLED"] | None = None


class VintageDiagnostics(PublicModel):
    generated_at_utc: AwareDatetime
    overall_status: Status
    sources: list[SourceDiagnostics] = Field(max_length=12)


class ReadinessDiagnostics(PublicModel):
    generated_at_utc: AwareDatetime
    dataset_status: Literal["NOT_READY", "PARTIALLY_READY", "READY_FOR_EVALUATION"]
    distinct_issue_cycles: int = Field(ge=0)
    distinct_calendar_days: int = Field(ge=0)
    complete_issue_cycles: int = Field(ge=0)
    horizon_coverage_count: int = Field(ge=0, le=24)
    output_rows: int = Field(ge=0)
    duplicate_key_count: int | None = Field(default=None, ge=0)
    leakage_check_passed: bool | None = None


class LinearFeature(PublicModel):
    feature: str
    importance: float = Field(ge=0)
    signed_coefficient: float


class LinearInfluence(PublicModel):
    model: Literal["Ordinary Linear Regression"] = "Ordinary Linear Regression"
    horizon_hours: Literal[1] = 1
    feature_count: Literal[31] = 31
    metadata_sha256: str
    report_sha256: str
    provenance: str = "Persisted standardized-coefficient report associated with the frozen one-hour release by its existing writer; no report-to-artifact cryptographic binding is recorded."
    limitation: str = "Associations, not causal effects; these are not HGB feature importances. No model was loaded, fitted or executed."
    features: list[LinearFeature] = Field(min_length=31, max_length=31)


# An explicit schema allowlist for the frozen Full PowerFlow model, not free text.
LINEAR_FEATURES = frozenset("price_eur_mwh price_lag_1h price_rolling_mean_24h load_lag_1h load_mw price_lag_24h solar_mw shortwave_radiation renewable_generation_mw relative_humidity_2m load_rolling_mean_24h renewable_share wind_speed_10m hydro_mw biomass_mw load_lag_24h hard_coal_mw price_lag_168h price_rolling_std_24h lignite_mw is_weekend hour cloud_cover day_of_week month gas_mw wind_onshore_mw wind_total_mw nuclear_mw wind_offshore_mw temperature_2m".split())


def read_json(path: Path):
    if not path.is_file():
        raise HTTPException(404, "The restricted report is not available.")
    try:
        with path.open("rb") as handle:
            value = handle.read(1024 * 1024 + 1)
        if len(value) > 1024 * 1024:
            raise ValueError("Report size limit")
        raw = json.loads(value)
        if not isinstance(raw, dict):
            raise ValueError("Invalid report")
        return raw
    except (OSError, ValueError, UnicodeError):
        raise HTTPException(503, "The restricted report is invalid or unreadable.") from None


def vintage_diagnostics(path):
    raw = read_json(path)
    try:
        sources = raw["sources"]
        if not isinstance(sources, list) or len(sources) > 12:
            raise ValueError("Invalid source list")
        return VintageDiagnostics(generated_at_utc=raw["generated_at_utc"], overall_status=raw["overall_status"],
            sources=[SourceDiagnostics(**{key: row[key] for key in SourceDiagnostics.model_fields if key in row}) for row in sources])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(503, "The restricted report is invalid or unreadable.") from None


def readiness_diagnostics(path):
    raw = read_json(path)
    try:
        values = {key: raw[key] for key in ReadinessDiagnostics.model_fields if key in raw and key != "leakage_check_passed"}
        audit = raw.get("leakage_check")
        if isinstance(audit, dict) and isinstance(audit.get("passed"), bool):
            values["leakage_check_passed"] = audit["passed"]
        return ReadinessDiagnostics(**values)
    except (TypeError, ValueError):
        raise HTTPException(503, "The restricted report is invalid or unreadable.") from None


def linear_influence(root: Path | None):
    if root is None:
        raise HTTPException(503, "Model reporting is not configured.")
    path = root / "data/reports/feature_importance.csv"
    if not path.is_file():
        raise HTTPException(404, "The restricted report is not available.")
    try:
        model = _summary(root, "one_hour")
        if model.metadata_status != "available" or model.feature_count != 31:
            raise ValueError("No consistent release metadata")
        with path.open('rb') as handle:
            report_bytes = handle.read(64 * 1024 + 1)
        if len(report_bytes) > 64 * 1024:
            raise ValueError("Report size limit")
        reader = csv.DictReader(io.StringIO(report_bytes.decode('utf-8'), newline=''))
        rows = []
        for row in reader:
            if len(rows) >= 31 or row.get("feature") not in LINEAR_FEATURES:
                raise ValueError("Invalid feature")
            magnitude, coefficient = float(row["importance"]), float(row["signed_coefficient"])
            if not math.isfinite(magnitude) or not math.isfinite(coefficient) or not math.isclose(magnitude, abs(coefficient), rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Invalid coefficient")
            rows.append(LinearFeature(feature=row["feature"], importance=magnitude, signed_coefficient=coefficient))
        if {row.feature for row in rows} != LINEAR_FEATURES or len(rows) != 31:
            raise ValueError("Incomplete or duplicate feature report")
        return LinearInfluence(metadata_sha256=model.metadata_sha256, report_sha256=hashlib.sha256(report_bytes).hexdigest(), features=sorted(rows, key=lambda row: (-row.importance, row.feature)))
    except (OSError, ValueError, TypeError, KeyError, csv.Error):
        raise HTTPException(503, "The restricted report is invalid or inconsistent with release metadata.") from None

class ForecastProvenance(PublicModel):
    issue_time: AwareDatetime
    issued_at_utc: AwareDatetime | None = None
    issuance_evidence: Literal['missing', 'no_matching_complete_issue', 'available']
    provenance_evidence: Literal['missing', 'different_issue', 'available']
    market_latest_complete_hour: AwareDatetime | None = None
    weather_acquired_at_utc: AwareDatetime | None = None
    weather_source: Literal['open_meteo_forecast_api_operational_model'] | None = None
    note: str = 'Issuance time is taken only from a complete matching persisted 24-horizon history cycle. Issue time alone is not generation time. Weather source is an allowlisted report label, not a claim of future-horizon weather inputs.'


def forecast_provenance(root: Path | None, forecasts):
    from datetime import datetime, timezone
    if root is None:
        raise HTTPException(503, 'Forecast provenance is not configured.')
    first = forecasts[0]
    result = dict(issue_time=first.issue_time, issuance_evidence='missing', provenance_evidence='missing')
    def stamp(value):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError('Timezone required')
        return value.astimezone(timezone.utc)
    try:
        path = root/'data/reports/next24h_forecast_history.csv'
        if path.is_file():
            if path.stat().st_size > 64*1024*1024:
                raise ValueError('History size limit')
            expected = {r.horizon_hours:r for r in forecasts}
            matches = {}
            with path.open(encoding='utf-8', newline='') as handle:
                reader = csv.DictReader(handle)
                required = {'forecast_issue_time','target_timestamp','issued_at_utc','horizon_hours','model_release','predicted_price_eur_mwh'}
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError('Missing issuance fields')
                for i,row in enumerate(reader):
                    if i>=100000:
                        raise ValueError('History row limit')
                    if stamp(row['forecast_issue_time']) != first.issue_time or row['model_release'] != first.model_release:
                        continue
                    horizon=int(row['horizon_hours'])
                    if horizon not in expected or horizon in matches:
                        raise ValueError('Duplicate or invalid issue horizon')
                    target=expected[horizon]
                    if stamp(row['target_timestamp']) != target.target_time or float(row['predicted_price_eur_mwh']) != target.predicted_price_eur_mwh:
                        raise ValueError('History and current report differ')
                    issued = stamp(row['issued_at_utc'])
                    if issued >= target.target_time or issued < first.issue_time:
                        raise ValueError('Invalid issuance time')
                    matches[horizon]=issued
            result['issuance_evidence']='no_matching_complete_issue'
            if len(matches)==24 and len(set(matches.values()))==1:
                result.update(issuance_evidence='available',issued_at_utc=matches[1])
        path = root/'data/reports/next24h_forecast_provenance.json'
        if path.is_file():
            raw=read_json(path)
            result['provenance_evidence']='different_issue'
            if stamp(raw['forecast_issue_time'])==first.issue_time:
                result.update(provenance_evidence='available',market_latest_complete_hour=stamp(raw['market_latest_complete_hour']) if raw.get('market_latest_complete_hour') else None,weather_acquired_at_utc=stamp(raw['weather_acquired_at_utc']) if raw.get('weather_acquired_at_utc') else None,weather_source=raw.get('weather_source') if raw.get('weather_source')=='open_meteo_forecast_api_operational_model' else None)
        return ForecastProvenance(**result)
    except (OSError, ValueError, TypeError, KeyError, csv.Error, OverflowError):
        raise HTTPException(503, 'Forecast provenance is invalid or inconsistent.') from None

"""Read-only FastAPI surface for persisted PowerFlow reports and metadata."""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


from .market_data import MarketChart, MarketSummary, market_chart, market_summary, MarketCoverage, MarketHistory, MarketStore
from .anomalies import AnomalySummary, AnomalyEvents, anomaly_summary, anomaly_events
from .operations_summary import OperationsSummary, operations_summary
from typing import Literal
from .model_summaries import ModelsResponse, model_summaries


APPLICATION_NAME = "PowerFlow API"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SENSITIVE_KEY = re.compile(
    r"(?:password|secret|token|api[_-]?key|access[_-]?key|authorization)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class APISettings:
    operational_database: Path
    next24_forecast: Path
    one_hour_forecast: Path
    forecast_vintage_health: Path
    exogenous_readiness: Path
    market_silver: Path | None = None
    public_metadata_root: Path | None = None
    anomaly_report: Path | None = None

    @classmethod
    def from_root(cls, root: Path) -> "APISettings":
        root = Path(root)
        return cls(
            market_silver=root / "data/processed/silver_electricity_market_data.csv",
            public_metadata_root=root,
            anomaly_report=root / "data/reports/detected_anomalies.csv",
            operational_database=root / "database/electricity_trading.db",
            next24_forecast=root / "data/reports/next24h_forecast.csv",
            one_hour_forecast=root / "data/reports/actual_vs_predicted.csv",
            forecast_vintage_health=(
                root / "data/reports/monitoring/forecast_vintage_health.json"
            ),
            exogenous_readiness=(
                root
                / "data/reports/monitoring/next24h_exogenous_silver_quality.json"
            ),
        )


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictResponseModel):
    status: str
    application: str
    timestamp_utc: datetime


class PipelineStatusResponse(StrictResponseModel):
    latest_run_status: str
    latest_run_timestamp: datetime
    forecast_status: str | None = None


class Next24ForecastRow(StrictResponseModel):
    issue_time: datetime
    target_time: datetime
    horizon_hours: int = Field(ge=1, le=24)
    predicted_price_eur_mwh: float
    model_release: str


class Next24ForecastResponse(StrictResponseModel):
    row_count: int
    forecasts: list[Next24ForecastRow]


class OneHourForecastRow(StrictResponseModel):
    target_time: datetime
    actual_price_eur_mwh: float
    predicted_price_eur_mwh: float


class OneHourForecastResponse(StrictResponseModel):
    row_count: int
    forecasts: list[OneHourForecastRow]


def _utc_datetime(value: Any, field_name: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is not numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} is not finite")
    return number


def _read_csv_rows(path: Path, report_name: str) -> list[dict[str, str]]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{report_name} is not available.")
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail=f"{report_name} could not be read."
        ) from exc


def _sanitized_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else _sanitized_json(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitized_json(item) for item in value]
    return value


def _read_json_report(path: Path, report_name: str) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{report_name} is not available.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503, detail=f"{report_name} is invalid or unreadable."
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail=f"{report_name} is invalid.")
    return _sanitized_json(payload)


def _latest_pipeline_status(path: Path) -> PipelineStatusResponse:
    if not path.exists():
        raise HTTPException(
            status_code=503, detail="Operational metadata is not available."
        )
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_runs'"
            ).fetchone()
            if table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Operational metadata schema is unavailable.",
                )
            row = connection.execute(
                """
                SELECT run_time, status, message
                FROM pipeline_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503, detail="Operational metadata could not be read."
        ) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="No pipeline run is available.")

    run_time, status, message = row
    forecast_status = None
    if isinstance(message, str):
        try:
            metadata = json.loads(message)
        except json.JSONDecodeError:
            metadata = None
        if isinstance(metadata, dict):
            value = metadata.get("next24h_forecast_status")
            if value is None:
                value = metadata.get("next24h_forecast_freshness_status")
            if value is not None:
                forecast_status = str(value)
    try:
        timestamp = _utc_datetime(run_time, "latest run timestamp")
    except ValueError as exc:
        raise HTTPException(
            status_code=503, detail="Latest pipeline metadata is invalid."
        ) from exc
    return PipelineStatusResponse(
        latest_run_status=str(status),
        latest_run_timestamp=timestamp,
        forecast_status=forecast_status,
    )


def _next24_report(path: Path) -> Next24ForecastResponse:
    rows = _read_csv_rows(path, "Next24 forecast report")
    required = {
        "forecast_issue_time",
        "target_timestamp",
        "horizon_hours",
        "predicted_price_eur_mwh",
        "model_release",
    }
    if len(rows) != 24 or not rows or not required.issubset(rows[0]):
        raise HTTPException(
            status_code=503, detail="Next24 forecast report has an invalid schema."
        )
    forecasts: list[Next24ForecastRow] = []
    try:
        for expected_horizon, row in enumerate(rows, start=1):
            issue = _utc_datetime(row["forecast_issue_time"], "forecast issue time")
            target = _utc_datetime(row["target_timestamp"], "forecast target time")
            horizon = int(row["horizon_hours"])
            price = _finite_float(
                row["predicted_price_eur_mwh"], "predicted price"
            )
            release = str(row["model_release"]).strip()
            if (
                horizon != expected_horizon
                or target != issue + timedelta(hours=horizon)
                or not release
            ):
                raise ValueError("Next24 forecast row contract is invalid")
            forecasts.append(
                Next24ForecastRow(
                    issue_time=issue,
                    target_time=target,
                    horizon_hours=horizon,
                    predicted_price_eur_mwh=price,
                    model_release=release,
                )
            )
        if len({row.issue_time for row in forecasts}) != 1:
            raise ValueError("Next24 forecast issue times differ")
        if len({row.model_release for row in forecasts}) != 1:
            raise ValueError("Next24 forecast releases differ")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Next24 forecast report is invalid."
        ) from exc
    return Next24ForecastResponse(row_count=len(forecasts), forecasts=forecasts)


def _one_hour_report(path: Path) -> OneHourForecastResponse:
    rows = _read_csv_rows(path, "One-hour forecast report")
    required = {"timestamp", "actual_price", "predicted_price"}
    if not rows:
        raise HTTPException(status_code=404, detail="One-hour forecast report is empty.")
    if not required.issubset(rows[0]):
        raise HTTPException(
            status_code=503, detail="One-hour forecast report has an invalid schema."
        )
    forecasts: list[OneHourForecastRow] = []
    try:
        for row in rows:
            forecasts.append(
                OneHourForecastRow(
                    target_time=_utc_datetime(row["timestamp"], "target time"),
                    actual_price_eur_mwh=_finite_float(
                        row["actual_price"], "actual price"
                    ),
                    predicted_price_eur_mwh=_finite_float(
                        row["predicted_price"], "predicted price"
                    ),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="One-hour forecast report is invalid."
        ) from exc
    return OneHourForecastResponse(row_count=len(forecasts), forecasts=forecasts)


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Create the service with explicit read-only paths for safe testing."""
    configured = settings or APISettings.from_root(PROJECT_ROOT)
    market_store = MarketStore(configured.market_silver)

    @asynccontextmanager
    async def lifespan(_application):
        yield
        market_store.close()

    application = FastAPI(
        title=APPLICATION_NAME,
        description="Read-only access to persisted PowerFlow outputs.",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            application=APPLICATION_NAME,
            timestamp_utc=datetime.now(timezone.utc),
        )

    @application.get("/pipeline/status", response_model=PipelineStatusResponse)
    def pipeline_status() -> PipelineStatusResponse:
        return _latest_pipeline_status(configured.operational_database)

    @application.get("/forecast/next24", response_model=Next24ForecastResponse)
    def next24_forecast() -> Next24ForecastResponse:
        return _next24_report(configured.next24_forecast)

    @application.get("/forecast/one-hour", response_model=OneHourForecastResponse)
    def one_hour_forecast() -> OneHourForecastResponse:
        return _one_hour_report(configured.one_hour_forecast)

    @application.get("/monitoring/forecast-vintages", response_model=dict[str, Any])
    def forecast_vintage_monitoring() -> dict[str, Any]:
        return _read_json_report(
            configured.forecast_vintage_health, "Forecast-vintage health report"
        )

    @application.get("/monitoring/exogenous-readiness", response_model=dict[str, Any])
    def exogenous_readiness() -> dict[str, Any]:
        return _read_json_report(
            configured.exogenous_readiness, "Exogenous readiness report"
        )

    @application.get("/market/coverage", response_model=MarketCoverage)
    def market_coverage() -> MarketCoverage:
        return market_store.coverage()

    @application.get("/market/history", response_model=MarketHistory)
    def market_history(
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = Query(default=1000, ge=1, le=2000),
        offset: int = Query(default=0, ge=0, le=2_000_000),
    ) -> MarketHistory:
        return market_store.history(start, end, limit, offset)

    @application.get("/models/summary", response_model=ModelsResponse)
    def public_model_summaries() -> ModelsResponse:
        return model_summaries(configured.public_metadata_root)

    @application.get("/anomalies/summary", response_model=AnomalySummary)
    def public_anomaly_summary(start: datetime | None = None, end: datetime | None = None):
        return anomaly_summary(configured.anomaly_report, start, end)

    @application.get("/anomalies/events", response_model=AnomalyEvents)
    def public_anomaly_events(start: datetime | None = None, end: datetime | None = None,
                              order: Literal["price_desc", "time_asc", "time_desc"] = "price_desc",
                              limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0, le=100000)):
        return anomaly_events(configured.anomaly_report, start, end, order, limit, offset)

    @application.get("/market/summary", response_model=MarketSummary)
    def public_market_summary(start: datetime | None = None, end: datetime | None = None):
        return market_summary(market_store, start, end)

    @application.get("/market/chart", response_model=MarketChart)
    def public_market_chart(start: datetime | None = None, end: datetime | None = None,
                            max_points: int = Query(default=1600, ge=4, le=2000)):
        return market_chart(market_store, start, end, max_points)

    @application.get("/operations/summary", response_model=OperationsSummary)
    def public_operations_summary():
        issue, invalid = None, False
        try:
            issue = _next24_report(configured.next24_forecast).forecasts[0].issue_time
        except HTTPException as error:
            invalid = error.status_code != 404
        return operations_summary(configured, issue, invalid)

    return application


app = create_app()


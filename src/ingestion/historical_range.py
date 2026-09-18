import os
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


DEFAULT_START_DATE = "2019-01-01"
DEFAULT_END_DATE = "2025-09-30"
START_DATE_ENV = "POWERFLOW_HISTORY_START_DATE"
END_DATE_ENV = "POWERFLOW_HISTORY_END_DATE"
CANONICAL_TIMEZONE = "UTC"
API_CHUNK_MONTHS = 6


@dataclass(frozen=True)
class HistoricalDateRange:
    """Inclusive calendar-date range shared by market and weather ingestion."""

    start_date: date
    end_date: date

    @property
    def start_utc(self) -> pd.Timestamp:
        return pd.Timestamp(self.start_date, tz=CANONICAL_TIMEZONE)

    @property
    def end_utc_exclusive(self) -> pd.Timestamp:
        return pd.Timestamp(
            self.end_date + timedelta(days=1),
            tz=CANONICAL_TIMEZONE,
        )


def _parse_iso_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must use YYYY-MM-DD format: {value}") from error


def get_historical_date_range(
    start_date: str | None = None,
    end_date: str | None = None,
) -> HistoricalDateRange:
    start_value = start_date or os.getenv(START_DATE_ENV, DEFAULT_START_DATE)
    end_value = end_date or os.getenv(END_DATE_ENV, DEFAULT_END_DATE)

    historical_range = HistoricalDateRange(
        start_date=_parse_iso_date(start_value, "start_date"),
        end_date=_parse_iso_date(end_value, "end_date"),
    )
    if historical_range.start_date > historical_range.end_date:
        raise ValueError("start_date must be on or before end_date.")

    return historical_range


def iter_time_chunks(
    historical_range: HistoricalDateRange,
    chunk_months: int = API_CHUNK_MONTHS,
):
    """Yield continuous, non-overlapping, end-exclusive UTC API windows."""
    if chunk_months <= 0:
        raise ValueError("chunk_months must be positive.")

    chunk_start = historical_range.start_utc
    final_end = historical_range.end_utc_exclusive

    while chunk_start < final_end:
        chunk_end = min(
            chunk_start + pd.DateOffset(months=chunk_months),
            final_end,
        )
        yield chunk_start, chunk_end
        chunk_start = chunk_end


def iter_utc_chunks(
    start_utc: pd.Timestamp,
    end_utc_exclusive: pd.Timestamp,
    chunk_months: int = API_CHUNK_MONTHS,
):
    """Yield UTC timestamp windows for incremental, potentially intraday requests."""
    start = pd.Timestamp(start_utc)
    end = pd.Timestamp(end_utc_exclusive)
    start = start.tz_localize(CANONICAL_TIMEZONE) if start.tzinfo is None else start.tz_convert(CANONICAL_TIMEZONE)
    end = end.tz_localize(CANONICAL_TIMEZONE) if end.tzinfo is None else end.tz_convert(CANONICAL_TIMEZONE)
    if chunk_months <= 0:
        raise ValueError("chunk_months must be positive.")
    if start > end:
        raise ValueError("start_utc must be on or before end_utc_exclusive.")

    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + pd.DateOffset(months=chunk_months), end)
        yield chunk_start, chunk_end
        chunk_start = chunk_end

import os
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


DEFAULT_START_DATE = "2019-01-01"
DEFAULT_END_DATE = "2025-09-30"
START_DATE_ENV = "POWERFLOW_HISTORY_START_DATE"
END_DATE_ENV = "POWERFLOW_HISTORY_END_DATE"
MARKET_TIMEZONE = "Europe/Berlin"


@dataclass(frozen=True)
class HistoricalDateRange:
    """Inclusive calendar-date range shared by market and weather ingestion."""

    start_date: date
    end_date: date

    @property
    def entsoe_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.start_date, tz=MARKET_TIMEZONE)

    @property
    def entsoe_end_exclusive(self) -> pd.Timestamp:
        return pd.Timestamp(self.end_date + timedelta(days=1), tz=MARKET_TIMEZONE)


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


def iter_year_chunks(historical_range: HistoricalDateRange):
    """Yield non-overlapping, end-exclusive windows of at most one year."""
    chunk_start = historical_range.entsoe_start
    final_end = historical_range.entsoe_end_exclusive

    while chunk_start < final_end:
        chunk_end = min(chunk_start + pd.DateOffset(years=1), final_end)
        yield chunk_start, chunk_end
        chunk_start = chunk_end

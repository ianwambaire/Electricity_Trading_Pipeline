import argparse
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

if __package__:
    from .historical_range import (
        get_historical_date_range,
        iter_time_chunks,
        iter_utc_chunks,
    )
    from .incremental_utils import (
        append_csv_safely,
        completed_utc_hour,
        infer_stored_interval,
        latest_stored_timestamp,
        merge_incremental_rows,
        normalize_utc_timestamps,
    )
else:
    from historical_range import get_historical_date_range, iter_time_chunks, iter_utc_chunks
    from incremental_utils import (
        append_csv_safely,
        completed_utc_hour,
        infer_stored_interval,
        latest_stored_timestamp,
        merge_incremental_rows,
        normalize_utc_timestamps,
    )


COUNTRY_CODE = "DE_LU"
RAW_ENTSOE_DIR = Path("data/raw/entsoe")
QUARTER_HOURLY_PRICE_START_UTC = pd.Timestamp("2025-09-30T22:00:00Z")
SENSITIVE_QUERY_PARAMETERS = {
    "accesskey",
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "credential",
    "key",
    "passwd",
    "password",
    "secret",
    "securitytoken",
    "signature",
    "token",
}


def redact_sensitive_url(url: str) -> str:
    """Return a URL with credential-like query values replaced."""
    parts = urlsplit(url)
    redacted_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = key.casefold().replace("_", "").replace("-", "")
        safe_value = "[REDACTED]" if normalized_key in SENSITIVE_QUERY_PARAMETERS else value
        redacted_query.append((key, safe_value))

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(redacted_query),
            parts.fragment,
        )
    )


def combine_time_chunks(chunks: list[pd.Series | pd.DataFrame]):
    if not chunks:
        raise ValueError("At least one non-empty ENTSO-E chunk is required.")

    combined = pd.concat(chunks)
    combined = combined.loc[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def fetch_in_chunks(client, query_method, historical_range, dataset_name):
    return fetch_timestamp_range(
        client,
        query_method,
        historical_range.start_utc,
        historical_range.end_utc_exclusive,
        dataset_name,
        allow_empty=False,
    )


def fetch_timestamp_range(
    client,
    query_method,
    start_utc,
    end_utc_exclusive,
    dataset_name,
    *,
    allow_empty: bool,
):
    chunks = []
    for chunk_start, chunk_end in iter_utc_chunks(start_utc, end_utc_exclusive):
        print(
            f"Fetching {dataset_name}: "
            f"{chunk_start.isoformat()} to {chunk_end.isoformat()} (end exclusive)"
        )
        try:
            chunk = query_method(
                COUNTRY_CODE,
                start=chunk_start,
                end=chunk_end,
            )
        except NoMatchingDataError:
            if allow_empty:
                print(
                    f"No new ENTSO-E {dataset_name} records were available for "
                    f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
                )
                continue
            raise RuntimeError(
                f"ENTSO-E returned no {dataset_name} for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
            ) from None
        except Exception as error:
            error_type = type(error).__name__
            print(
                f"ENTSO-E {dataset_name} failed for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}; "
                f"error type: {error_type}."
            )
            raise RuntimeError(
                f"ENTSO-E {dataset_name} unavailable for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}; "
                f"error type: {error_type}."
            ) from None

        if chunk is not None:
            chunk = chunk.loc[
                (chunk.index >= chunk_start) & (chunk.index < chunk_end)
            ]
        if chunk is None or chunk.empty:
            if allow_empty:
                print(
                    f"No new ENTSO-E {dataset_name} records were available for "
                    f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
                )
                continue
            raise RuntimeError(
                f"ENTSO-E returned no {dataset_name} for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
            )
        chunks.append(chunk)

    if not chunks:
        return None
    return combine_time_chunks(chunks)


def save_series(series, filepath: Path, value_name: str):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(series, pd.Series):
        data = series.rename(value_name).to_frame()
    elif series.shape[1] == 1:
        data = series.copy()
        data.columns = [value_name]
    else:
        raise ValueError(f"Expected one {value_name} column, found {series.shape[1]}.")

    data.index.name = "timestamp"
    data.reset_index().to_csv(filepath, index=False)
    print(f"Saved {filepath} with shape {data.shape}")


def save_generation(generation: pd.DataFrame, filepath: Path):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    generation_data = _flatten_generation_frame(generation)
    generation_data.to_csv(filepath, index=False)
    print(f"Saved {filepath} with shape {generation_data.shape}")


def _to_value_frame(values, value_name: str | None = None) -> pd.DataFrame:
    if isinstance(values, pd.Series):
        data = values.rename(value_name or values.name).to_frame()
    else:
        data = values.copy()
        if value_name is not None:
            if data.shape[1] != 1:
                raise ValueError(
                    f"Expected one {value_name} column, found {data.shape[1]}."
                )
            data.columns = [value_name]
    data.index.name = "timestamp"
    return data.reset_index()


def _validate_incremental_index(
    values,
    start_utc: pd.Timestamp,
    default_interval: pd.Timedelta,
    *,
    quarter_hourly_price_transition: bool = False,
) -> None:
    index = pd.DatetimeIndex(values.index)
    index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    index = index.sort_values().drop_duplicates()
    if index.empty:
        return

    expected = [pd.Timestamp(start_utc)]
    while expected[-1] < index[-1]:
        interval = default_interval
        if quarter_hourly_price_transition and expected[-1] >= QUARTER_HOURLY_PRICE_START_UTC:
            interval = pd.Timedelta(minutes=15)
        expected.append(expected[-1] + interval)
    expected_index = pd.DatetimeIndex(expected)
    if not index.equals(expected_index):
        missing = expected_index.difference(index)
        raise ValueError(
            "ENTSO-E incremental response is not continuous from the requested "
            f"start; missing={list(missing[:5])}."
        )


def _flatten_generation_frame(generation: pd.DataFrame) -> pd.DataFrame:
    generation = generation.copy()
    if isinstance(generation.columns, pd.MultiIndex):
        actual_columns = [
            column
            for column in generation.columns
            if str(column[-1]).strip() == "Actual Aggregated"
        ]
        generation = generation.loc[:, actual_columns]
        generation.columns = [str(column[0]) for column in actual_columns]
    generation = generation.loc[:, ~generation.columns.duplicated(keep="first")]
    generation.index.name = "timestamp"
    return generation.reset_index()


def _read_stored_generation(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8") as source:
        first_line = source.readline()
        second_line = source.readline()
    if second_line.startswith(",") and "Actual Aggregated" in second_line:
        stored = pd.read_csv(path, header=[0, 1], low_memory=False)
        timestamp_column = stored.columns[0]
        timestamps = stored[timestamp_column]
        stored = stored.drop(columns=[timestamp_column])
        stored.index = timestamps
        return _flatten_generation_frame(stored)
    return pd.read_csv(path, low_memory=False)


def latest_generation_timestamp(path: Path) -> pd.Timestamp | None:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    generation = normalize_utc_timestamps(_read_stored_generation(path))
    return generation["timestamp"].iloc[-1] if not generation.empty else None


def _append_generation_safely(path: Path, generation: pd.DataFrame):
    incoming = normalize_utc_timestamps(_flatten_generation_frame(generation))
    if path.exists():
        existing = _read_stored_generation(path)
        combined, new_rows = merge_incremental_rows(
            existing,
            incoming,
            allow_column_union=True,
        )
    else:
        combined = incoming
        new_rows = len(incoming)
    latest = combined["timestamp"].iloc[-1] if not combined.empty else None
    if new_rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        combined.to_csv(temporary_path, index=False)
        temporary_path.replace(path)
    return new_rows, latest


def _incremental_dataset(
    client,
    query_method,
    *,
    dataset_name: str,
    output_path: Path,
    default_interval: str,
    end_utc_exclusive: pd.Timestamp,
    value_name: str | None = None,
    allow_column_union: bool = False,
) -> dict:
    if allow_column_union and value_name is None and output_path.exists():
        stored_generation = normalize_utc_timestamps(
            _read_stored_generation(output_path)
        )
        latest = stored_generation["timestamp"].iloc[-1]
        differences = stored_generation["timestamp"].tail(200).diff().dropna()
        interval = differences[differences > pd.Timedelta(0)].min()
    else:
        latest = latest_stored_timestamp(output_path)
        interval = (
            infer_stored_interval(output_path, default_interval)
            if latest is not None
            else pd.Timedelta(default_interval)
        )
    if latest is None:
        start_utc = get_historical_date_range().start_utc
    else:
        start_utc = latest + interval

    if start_utc >= end_utc_exclusive:
        print(f"No new ENTSO-E {dataset_name} interval is currently due.")
        return {
            "new_rows": 0,
            "latest_timestamp": latest,
        }

    values = fetch_timestamp_range(
        client,
        query_method,
        start_utc,
        end_utc_exclusive,
        dataset_name,
        allow_empty=True,
    )
    if values is None:
        return {"new_rows": 0, "latest_timestamp": latest}

    _validate_incremental_index(
        values,
        start_utc,
        interval,
        quarter_hourly_price_transition=value_name == "price_eur_mwh",
    )

    if allow_column_union and value_name is None:
        new_rows, latest_timestamp = _append_generation_safely(output_path, values)
    else:
        result = append_csv_safely(
            output_path,
            _to_value_frame(values, value_name),
            allow_column_union=allow_column_union,
        )
        new_rows = result.new_rows
        latest_timestamp = result.latest_timestamp
    print(
        f"Incremental {dataset_name}: appended {new_rows} rows; "
        f"latest timestamp={latest_timestamp}."
    )
    return {
        "new_rows": new_rows,
        "latest_timestamp": latest_timestamp,
    }


def fetch_entsoe_data(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    mode: str = "historical",
    now: pd.Timestamp | None = None,
    client=None,
):
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be 'historical' or 'incremental'.")
    if mode == "incremental" and (start_date is not None or end_date is not None):
        raise ValueError("start_date/end_date are supported only in historical mode.")
    if client is None:
        load_dotenv()
        api_key = os.getenv("ENTSOE_API_KEY")
        if not api_key:
            raise ValueError("ENTSOE_API_KEY not found. Check your .env file.")
        client = EntsoePandasClient(api_key=api_key)
    RAW_ENTSOE_DIR.mkdir(parents=True, exist_ok=True)

    if mode == "incremental":
        end_utc_exclusive = completed_utc_hour(now)
        specifications = [
            (
                "day-ahead prices",
                client.query_day_ahead_prices,
                RAW_ENTSOE_DIR / "prices.csv",
                "1h",
                "price_eur_mwh",
                False,
            ),
            (
                "actual load",
                client.query_load,
                RAW_ENTSOE_DIR / "load.csv",
                "15min",
                "load_mw",
                False,
            ),
            (
                "generation by type",
                client.query_generation,
                RAW_ENTSOE_DIR / "generation.csv",
                "15min",
                None,
                True,
            ),
        ]
        datasets = {}
        for name, method, path, interval, value_name, allow_union in specifications:
            datasets[name] = _incremental_dataset(
                client,
                method,
                dataset_name=name,
                output_path=path,
                default_interval=interval,
                end_utc_exclusive=end_utc_exclusive,
                value_name=value_name,
                allow_column_union=allow_union,
            )
        metadata = {
            "mode": mode,
            "new_rows": sum(item["new_rows"] for item in datasets.values()),
            "datasets": datasets,
        }
        if metadata["new_rows"] == 0:
            print("ENTSO-E incremental ingestion completed: no new records available.")
        else:
            print("ENTSO-E incremental ingestion completed.")
        return metadata

    historical_range = get_historical_date_range(start_date, end_date)

    prices = fetch_in_chunks(
        client,
        client.query_day_ahead_prices,
        historical_range,
        "day-ahead prices",
    )
    save_series(prices, RAW_ENTSOE_DIR / "prices.csv", "price_eur_mwh")

    load = fetch_in_chunks(
        client,
        client.query_load,
        historical_range,
        "actual load",
    )
    save_series(load, RAW_ENTSOE_DIR / "load.csv", "load_mw")

    generation = fetch_in_chunks(
        client,
        client.query_generation,
        historical_range,
        "generation by type",
    )
    save_generation(generation, RAW_ENTSOE_DIR / "generation.csv")

    metadata = {
        "mode": mode,
        "new_rows": len(prices) + len(load) + len(generation),
        "datasets": {
            "day-ahead prices": {
                "new_rows": len(prices),
                "latest_timestamp": prices.index.max(),
            },
            "actual load": {
                "new_rows": len(load),
                "latest_timestamp": load.index.max(),
            },
            "generation by type": {
                "new_rows": len(generation),
                "latest_timestamp": generation.index.max(),
            },
        },
    }
    print("ENTSO-E historical ingestion completed.")
    return metadata


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch ENTSO-E market data.")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        default="historical",
    )
    parser.add_argument("--start-date", help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Inclusive end date (YYYY-MM-DD).")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    fetch_entsoe_data(
        arguments.start_date,
        arguments.end_date,
        mode=arguments.mode,
    )

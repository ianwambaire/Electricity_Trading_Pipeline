import argparse
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient, EntsoeRawClient
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
        contiguous_prefix,
        contiguous_price_prefix,
        infer_stored_interval,
        latest_stored_timestamp,
        merge_generation_rows,
        normalize_utc_timestamps,
    )
else:
    from historical_range import get_historical_date_range, iter_time_chunks, iter_utc_chunks
    from incremental_utils import (
        append_csv_safely,
        completed_utc_hour,
        contiguous_prefix,
        contiguous_price_prefix,
        infer_stored_interval,
        latest_stored_timestamp,
        merge_generation_rows,
        normalize_utc_timestamps,
    )


COUNTRY_CODE = "DE_LU"
RAW_ENTSOE_DIR = Path("data/raw/entsoe")
QUARTER_HOURLY_PRICE_START_UTC = pd.Timestamp("2025-09-30T22:00:00Z")
GENERATION_REQUERY_OVERLAP = pd.Timedelta(hours=48)
LOAD_REQUERY_OVERLAP = pd.Timedelta(hours=48)
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
    if combined.index.duplicated().any():
        raise ValueError("ENTSO-E chunks contain duplicate timestamps.")
    return combined.sort_index()


def fetch_in_chunks(
    client, query_method, historical_range, dataset_name, *, chunk_months=6
):
    return fetch_timestamp_range(
        client,
        query_method,
        historical_range.start_utc,
        historical_range.end_utc_exclusive,
        dataset_name,
        allow_empty=False,
        chunk_months=chunk_months,
    )


def fetch_timestamp_range(
    client,
    query_method,
    start_utc,
    end_utc_exclusive,
    dataset_name,
    *,
    allow_empty: bool,
    chunk_months: int = 6,
):
    chunks = []
    for chunk_start, chunk_end in iter_utc_chunks(
        start_utc, end_utc_exclusive, chunk_months=chunk_months
    ):
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


def parse_price_observations(xml_text: str) -> pd.DataFrame:
    """Keep each explicit ENTSO-E price point and its declared period resolution."""
    root = ElementTree.fromstring(xml_text)

    def child_text(parent, name):
        child = parent.find(f"{{*}}{name}")
        if child is None or child.text is None:
            raise ValueError(f"ENTSO-E price response is missing {name}.")
        return child.text

    rows = []
    for series in root.findall(".//{*}TimeSeries"):
        for period in series.findall("{*}Period"):
            interval = period.find("{*}timeInterval")
            if interval is None:
                raise ValueError("ENTSO-E price period has no time interval.")
            start = pd.Timestamp(child_text(interval, "start"))
            end = pd.Timestamp(child_text(interval, "end"))
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError("ENTSO-E price interval must specify a timezone.")
            start, end = start.tz_convert("UTC"), end.tz_convert("UTC")
            resolution = child_text(period, "resolution")
            if resolution not in {"PT15M", "PT60M"}:
                raise ValueError(f"Unsupported ENTSO-E price resolution: {resolution}")
            step = pd.Timedelta(minutes=15 if resolution == "PT15M" else 60)
            for point in period.findall("{*}Point"):
                position = int(child_text(point, "position"))
                timestamp = start + (position - 1) * step
                if position < 1 or timestamp >= end:
                    raise ValueError("ENTSO-E price point falls outside its period.")
                rows.append(
                    (
                        timestamp,
                        float(child_text(point, "price.amount")),
                        resolution,
                    )
                )

    result = pd.DataFrame(
        rows, columns=["timestamp", "price_eur_mwh", "source_resolution"]
    )
    if result.empty:
        return result.set_index("timestamp")
    result = result.sort_values("timestamp")
    if result["timestamp"].duplicated().any():
        raise ValueError("ENTSO-E price response contains duplicate timestamps.")
    return result.set_index("timestamp")


def query_price_observations(client, country_code, start, end):
    """Use raw price XML so PT15M and PT60M remain distinguishable."""
    if isinstance(client, EntsoePandasClient):
        xml_text = EntsoeRawClient.query_day_ahead_prices(
            client,
            country_code,
            start=start,
            end=end,
            sequence=1,
        )
        return parse_price_observations(xml_text)
    return client.query_day_ahead_prices(country_code, start=start, end=end)


def save_series(series, filepath: Path, value_name: str):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(series, pd.Series):
        data = series.rename(value_name).to_frame()
    elif value_name == "price_eur_mwh" and set(series.columns) == {
        "price_eur_mwh", "source_resolution"
    }:
        data = series.copy()
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
        if value_name == "price_eur_mwh" and set(data.columns) == {
            "price_eur_mwh", "source_resolution"
        }:
            pass
        elif value_name is not None:
            if data.shape[1] != 1:
                raise ValueError(
                    f"Expected one {value_name} column, found {data.shape[1]}."
                )
            data.columns = [value_name]
    data.index.name = "timestamp"
    return data.reset_index()


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


def _append_generation_safely(
    path: Path,
    generation: pd.DataFrame,
    *,
    revision_window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    retain_protected_conflicts: bool = False,
):
    incoming = normalize_utc_timestamps(_flatten_generation_frame(generation))
    if path.exists():
        existing = _read_stored_generation(path)
        merged = merge_generation_rows(
            existing,
            incoming,
            revision_window=revision_window,
            retain_protected_conflicts=retain_protected_conflicts,
        )
        combined, new_rows = merged.data, merged.new_rows
        repaired_by_column = merged.repaired_by_column
        revised_by_column = merged.revised_by_column
        protected_conflicts_by_column = merged.protected_conflicts_by_column
        protected_conflict_timestamps = merged.protected_conflict_timestamps
    else:
        combined = incoming
        new_rows = len(incoming)
        repaired_by_column = {}
        revised_by_column = {}
        protected_conflicts_by_column = {}
        protected_conflict_timestamps = ()
    latest = combined["timestamp"].iloc[-1] if not combined.empty else None
    if new_rows or repaired_by_column or revised_by_column:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        try:
            combined.to_csv(temporary_path, index=False)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return (
        new_rows,
        latest,
        repaired_by_column,
        revised_by_column,
        protected_conflicts_by_column,
        protected_conflict_timestamps,
    )


def _append_load_safely(
    path: Path,
    load: pd.DataFrame,
    *,
    revision_window: tuple[pd.Timestamp, pd.Timestamp],
):
    """Atomically merge a recent load overlap under the source-revision policy."""
    incoming = normalize_utc_timestamps(load)
    if path.exists():
        existing = pd.read_csv(path, low_memory=False)
        merged = merge_generation_rows(
            existing,
            incoming,
            revision_window=revision_window,
            retain_protected_conflicts=True,
        )
        combined = merged.data
    else:
        combined = incoming
        merged = None

    new_rows = len(incoming) if merged is None else merged.new_rows
    repaired_by_column = {} if merged is None else merged.repaired_by_column
    revised_by_column = {} if merged is None else merged.revised_by_column
    protected_by_column = (
        {} if merged is None else merged.protected_conflicts_by_column
    )
    protected_timestamps = (
        () if merged is None else merged.protected_conflict_timestamps
    )
    changed = bool(new_rows or repaired_by_column or revised_by_column)
    latest = combined["timestamp"].iloc[-1] if not combined.empty else None
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        try:
            combined.to_csv(temporary_path, index=False)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return {
        "new_rows": new_rows,
        "latest_timestamp": latest,
        "repaired_by_column": repaired_by_column,
        "revised_by_column": revised_by_column,
        "protected_conflicts_by_column": protected_by_column,
        "protected_conflict_timestamps": protected_timestamps,
        "changed": changed,
    }


def repair_generation_interval(
    client,
    start_utc: pd.Timestamp,
    end_utc_exclusive: pd.Timestamp,
    *,
    path: Path = RAW_ENTSOE_DIR / "generation.csv",
    apply: bool = False,
) -> dict:
    """Preview or atomically fill genuine late generation values in an existing CSV."""
    start, end = pd.Timestamp(start_utc), pd.Timestamp(end_utc_exclusive)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Repair bounds must have explicit UTC timezones.")
    start, end = start.tz_convert("UTC"), end.tz_convert("UTC")
    if start >= end or end - start > pd.Timedelta(days=7):
        raise ValueError("Repair interval must be positive and no longer than seven days.")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Stored generation data not found: {path}")
    existing = normalize_utc_timestamps(_read_stored_generation(path))
    response = fetch_timestamp_range(
        client, client.query_generation, start, end, "generation by type",
        allow_empty=True, chunk_months=1,
    )
    if response is None:
        incoming = pd.DataFrame(columns=["timestamp"])
    else:
        incoming = normalize_utc_timestamps(_flatten_generation_frame(response))
    fetched_columns = [column for column in incoming if column != "timestamp"]
    fetched_null_counts = incoming[fetched_columns].isna().sum().astype(int).to_dict()
    # A controlled repair is cell-only: no new timestamps or schema columns.
    stored_interval = existing.loc[
        existing["timestamp"].between(start, end, inclusive="left")
    ]
    incoming = incoming.loc[
        incoming["timestamp"].isin(stored_interval["timestamp"])
    ].reindex(columns=existing.columns)
    merged = merge_generation_rows(existing, incoming)
    if merged.new_rows or list(merged.data.columns) != list(existing.columns):
        raise ValueError("Controlled repair cannot change generation timestamps or schema.")
    if apply and merged.repaired_cells:
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        try:
            merged.data.to_csv(temporary_path, index=False)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return {
        "start_utc": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "returned_timestamps": [value.isoformat() for value in incoming["timestamp"]],
        "returned_columns": fetched_columns,
        "stored_columns_absent_from_response": sorted(
            set(existing.columns) - set(fetched_columns) - {"timestamp"}
        ),
        "returned_null_counts": fetched_null_counts,
        "repaired_by_column": merged.repaired_by_column,
        "repaired_cells": merged.repaired_cells,
        "applied": bool(apply and merged.repaired_cells),
    }


def _latest_complete_price_hour(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    from processing.build_silver_dataset import aggregate_hourly_prices

    prices = pd.read_csv(path)
    prices["timestamp"] = pd.to_datetime(
        prices["timestamp"], errors="raise", utc=True
    )
    prices = prices.set_index("timestamp")
    complete = aggregate_hourly_prices(prices)
    return complete.index[-1].isoformat() if not complete.empty else None


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
    is_price = value_name == "price_eur_mwh"
    is_load = value_name == "load_mw"
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
        if is_price and latest is not None:
            stored_columns = pd.read_csv(output_path, nrows=0).columns
            if "source_resolution" in stored_columns:
                stored_resolutions = pd.read_csv(
                    output_path, usecols=["source_resolution"]
                )["source_resolution"]
                last_resolution = stored_resolutions.iloc[-1]
                if pd.notna(last_resolution):
                    if last_resolution not in {"PT15M", "PT60M"}:
                        raise ValueError("Stored price resolution is unsupported.")
                    interval = pd.Timedelta(
                        minutes=15 if last_resolution == "PT15M" else 60
                    )
    if latest is None:
        start_utc = get_historical_date_range().start_utc
    else:
        start_utc = latest + interval
        if allow_column_union and value_name is None:
            start_utc = max(
                get_historical_date_range().start_utc,
                latest - GENERATION_REQUERY_OVERLAP,
            )
        elif is_load:
            start_utc = max(
                get_historical_date_range().start_utc,
                latest - LOAD_REQUERY_OVERLAP,
            )

    if start_utc >= end_utc_exclusive:
        print(f"No new ENTSO-E {dataset_name} interval is currently due.")
        metadata = {
            "new_rows": 0,
            "latest_timestamp": latest,
            "unresolved_gap": None,
            "changed": False,
        }
        if is_price:
            metadata["latest_complete_hour"] = _latest_complete_price_hour(output_path)
        return metadata

    values = fetch_timestamp_range(
        client,
        query_method,
        start_utc,
        end_utc_exclusive,
        dataset_name,
        allow_empty=True,
        chunk_months=1 if is_price else 6,
    )
    if values is None:
        metadata = {
            "new_rows": 0,
            "latest_timestamp": latest,
            "unresolved_gap": None,
            "changed": False,
        }
        if is_price:
            metadata["latest_complete_hour"] = _latest_complete_price_hour(output_path)
        return metadata

    continuity_values = values
    if is_load and output_path.exists():
        stored_load = pd.read_csv(output_path, usecols=["timestamp"])
        stored_index = pd.DatetimeIndex(
            pd.to_datetime(stored_load["timestamp"], errors="raise", utc=True)
        )
        stored_index = stored_index[
            (stored_index >= start_utc) & (stored_index < end_utc_exclusive)
        ]
        fetched_index = pd.DatetimeIndex(pd.to_datetime(values.index, utc=True))
        continuity_values = pd.Series(
            1.0,
            index=stored_index.union(fetched_index).sort_values(),
        )

    continuity = (
        contiguous_price_prefix(
            values,
            start_utc,
            quarter_hourly_transition=QUARTER_HOURLY_PRICE_START_UTC,
        )
        if is_price
        else contiguous_prefix(continuity_values, start_utc, interval)
    )
    # Retain genuine observations on both sides of an isolated source gap.
    # Hourly completeness is decided downstream; no missing value is filled.
    observed_values = values

    unresolved_gap = None
    if continuity.missing_timestamps:
        unresolved_gap = {
            "requested_start": pd.Timestamp(start_utc).isoformat(),
            "first_unresolved_timestamp": (
                continuity.first_unresolved_timestamp.isoformat()
            ),
            "missing_timestamps": [
                timestamp.isoformat()
                for timestamp in continuity.missing_timestamps
            ],
            "missing_count": len(continuity.missing_timestamps),
            "last_contiguous_timestamp": (
                continuity.last_contiguous_timestamp.isoformat()
                if continuity.last_contiguous_timestamp is not None
                else (latest.isoformat() if latest is not None else None)
            ),
            "returned_last_timestamp": (
                continuity.returned_last_timestamp.isoformat()
                if continuity.returned_last_timestamp is not None
                else None
            ),
            "later_observations_retained": int(
                (values.index > continuity.first_unresolved_timestamp).sum()
            ),
            "affected_hour": (
                continuity.first_unresolved_timestamp.floor("h").isoformat()
            ),
            "affected_hours": sorted({
                timestamp.floor("h").isoformat()
                for timestamp in continuity.missing_timestamps
            }),
        }
        print(
            f"ENTSO-E {dataset_name} has an unresolved source gap at "
            f"{unresolved_gap['first_unresolved_timestamp']}; retaining later "
            "observed rows while excluding incomplete hours downstream."
        )

    if observed_values.empty:
        new_rows = 0
        latest_timestamp = latest
        repaired_by_column = {}
        revised_by_column = {}
        protected_conflicts_by_column = {}
        protected_conflict_timestamps = ()
        changed = False
    elif is_load:
        revision_window = (
            max(start_utc, end_utc_exclusive - LOAD_REQUERY_OVERLAP),
            end_utc_exclusive,
        )
        load_merge = _append_load_safely(
            output_path,
            _to_value_frame(observed_values, value_name),
            revision_window=revision_window,
        )
        new_rows = load_merge["new_rows"]
        latest_timestamp = load_merge["latest_timestamp"]
        repaired_by_column = load_merge["repaired_by_column"]
        revised_by_column = load_merge["revised_by_column"]
        protected_conflicts_by_column = load_merge[
            "protected_conflicts_by_column"
        ]
        protected_conflict_timestamps = load_merge[
            "protected_conflict_timestamps"
        ]
        changed = load_merge["changed"]
    elif allow_column_union and value_name is None:
        # The retry may cover old backlog. Only the last 48 operational hours
        # may revise existing non-null values; older conflicts remain protected.
        revision_window = (
            max(start_utc, end_utc_exclusive - GENERATION_REQUERY_OVERLAP),
            end_utc_exclusive,
        )
        (
            new_rows,
            latest_timestamp,
            repaired_by_column,
            revised_by_column,
            protected_conflicts_by_column,
            protected_conflict_timestamps,
        ) = (
            _append_generation_safely(
                output_path,
                observed_values,
                revision_window=revision_window,
                retain_protected_conflicts=True,
            )
        )
        changed = bool(new_rows or repaired_by_column or revised_by_column)
    else:
        result = append_csv_safely(
            output_path,
            _to_value_frame(observed_values, value_name),
            allow_column_union=allow_column_union or is_price,
        )
        new_rows = result.new_rows
        latest_timestamp = result.latest_timestamp
        repaired_by_column = {}
        revised_by_column = {}
        protected_conflicts_by_column = {}
        protected_conflict_timestamps = ()
        changed = result.changed
    protected_conflicts = sum(protected_conflicts_by_column.values())
    if protected_conflicts:
        print(
            f"Ignored {protected_conflicts} protected historical ENTSO-E "
            "revision(s) outside the permitted revision window; stored value retained."
        )
    print(
        f"Incremental {dataset_name}: appended {new_rows} rows; "
        f"repaired {sum(repaired_by_column.values())} missing cells; "
        f"accepted {sum(revised_by_column.values())} recent source revisions "
        f"{revised_by_column}; "
        f"protected {protected_conflicts} historical conflicts "
        f"{protected_conflicts_by_column}; "
        f"latest timestamp={latest_timestamp}."
    )
    metadata = {
        "new_rows": new_rows,
        "latest_timestamp": latest_timestamp,
        "unresolved_gap": unresolved_gap,
        "repaired_by_column": repaired_by_column,
        "repaired_cells": sum(repaired_by_column.values()),
        "repaired_rows": sum(repaired_by_column.values()),
        "revised_by_column": revised_by_column,
        "revised_cells": sum(revised_by_column.values()),
        "protected_conflicts_by_column": protected_conflicts_by_column,
        "protected_conflicts": protected_conflicts,
        "protected_conflict_first_timestamp": (
            protected_conflict_timestamps[0].isoformat()
            if protected_conflict_timestamps else None
        ),
        "protected_conflict_last_timestamp": (
            protected_conflict_timestamps[-1].isoformat()
            if protected_conflict_timestamps else None
        ),
        "changed": changed,
    }
    if is_price:
        metadata["latest_complete_hour"] = _latest_complete_price_hour(output_path)
        if unresolved_gap is not None:
            unresolved_gap["last_complete_hour"] = metadata[
                "latest_complete_hour"
            ]
    return metadata


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
        price_query = lambda country_code, start, end: query_price_observations(
            client, country_code, start, end
        )
        specifications = [
            (
                "day-ahead prices",
                price_query,
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
            "repaired_cells": sum(item.get("repaired_cells", 0) for item in datasets.values()),
            "revised_cells": sum(item.get("revised_cells", 0) for item in datasets.values()),
            "protected_conflicts": sum(
                item.get("protected_conflicts", 0) for item in datasets.values()
            ),
            "datasets": datasets,
            "changed": any(item.get("changed", False) for item in datasets.values()),
        }
        if not metadata["changed"]:
            print("ENTSO-E incremental ingestion completed: no stored changes.")
        else:
            print("ENTSO-E incremental ingestion completed.")
        return metadata

    historical_range = get_historical_date_range(start_date, end_date)

    prices = fetch_in_chunks(
        client,
        lambda country_code, start, end: query_price_observations(
            client, country_code, start, end
        ),
        historical_range,
        "day-ahead prices",
        chunk_months=1,
    )
    price_continuity = contiguous_price_prefix(
        prices,
        historical_range.start_utc,
        quarter_hourly_transition=QUARTER_HOURLY_PRICE_START_UTC,
    )
    price_gap = None
    if price_continuity.first_unresolved_timestamp is not None:
        price_gap = {
            "first_unresolved_timestamp": (
                price_continuity.first_unresolved_timestamp.isoformat()
            ),
            "missing_count": len(price_continuity.missing_timestamps),
            "missing_timestamps": [
                timestamp.isoformat()
                for timestamp in price_continuity.missing_timestamps
            ],
            "later_observations_retained": int(
                (prices.index > price_continuity.first_unresolved_timestamp).sum()
            ),
        }
        print(
            "Historical ENTSO-E prices have a source gap at "
            f"{price_gap['first_unresolved_timestamp']}; retaining later "
            "observed rows."
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
                "unresolved_gap": price_gap,
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

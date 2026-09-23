from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


TIMESTAMP_COLUMN = "timestamp"


@dataclass(frozen=True)
class AppendResult:
    new_rows: int
    latest_timestamp: pd.Timestamp | None
    changed: bool


@dataclass(frozen=True)
class GenerationMergeResult:
    data: pd.DataFrame
    new_rows: int
    repaired_by_column: dict[str, int]
    revised_by_column: dict[str, int]
    protected_conflicts_by_column: dict[str, int]
    protected_conflict_timestamps: tuple[pd.Timestamp, ...]

    @property
    def repaired_cells(self) -> int:
        return sum(self.repaired_by_column.values())

    @property
    def revised_cells(self) -> int:
        return sum(self.revised_by_column.values())

    @property
    def protected_conflicts(self) -> int:
        return sum(self.protected_conflicts_by_column.values())


@dataclass(frozen=True)
class ContiguousPrefixResult:
    data: pd.Series | pd.DataFrame
    missing_timestamps: tuple[pd.Timestamp, ...]
    first_unresolved_timestamp: pd.Timestamp | None
    last_contiguous_timestamp: pd.Timestamp | None
    returned_last_timestamp: pd.Timestamp | None


def _utc_index(values: pd.Series | pd.DataFrame) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(values.index)
    return index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")


def _expected_market_index(
    start_utc: pd.Timestamp,
    end_utc: pd.Timestamp,
    interval: pd.Timedelta,
    *,
    quarter_hourly_transition: pd.Timestamp | None,
) -> pd.DatetimeIndex:
    current = pd.Timestamp(start_utc)
    end = pd.Timestamp(end_utc)
    expected = []
    while current <= end:
        expected.append(current)
        step = interval
        if quarter_hourly_transition is not None and current >= quarter_hourly_transition:
            step = pd.Timedelta(minutes=15)
        current += step
    return pd.DatetimeIndex(expected)


def contiguous_prefix(
    values: pd.Series | pd.DataFrame,
    start_utc: pd.Timestamp,
    interval: str | pd.Timedelta,
    *,
    quarter_hourly_transition: pd.Timestamp | None = None,
    require_complete_quarter_hourly_hours: bool = False,
) -> ContiguousPrefixResult:
    """Return only the source prefix safe to append without crossing a gap."""
    if values is None or values.empty:
        return ContiguousPrefixResult(values, (), None, None, None)

    ordered = values.sort_index()
    actual_index = _utc_index(ordered)
    if actual_index.duplicated().any():
        raise ValueError("Incremental source response contains duplicate timestamps.")

    expected_index = _expected_market_index(
        pd.Timestamp(start_utc),
        actual_index[-1],
        pd.Timedelta(interval),
        quarter_hourly_transition=quarter_hourly_transition,
    )
    missing = list(expected_index.difference(actual_index))
    first_unresolved = min(missing) if missing else None
    prefix_end = first_unresolved

    if require_complete_quarter_hourly_hours:
        transition = pd.Timestamp(quarter_hourly_transition)
        candidate_index = actual_index[
            actual_index < first_unresolved
        ] if first_unresolved is not None else actual_index
        post_transition = candidate_index[candidate_index >= transition]
        if len(post_transition):
            final_hour = post_transition[-1].floor("h")
            final_hour_expected = pd.date_range(
                final_hour,
                final_hour + pd.Timedelta(minutes=45),
                freq="15min",
            )
            absent_from_final_hour = final_hour_expected.difference(actual_index)
            if len(absent_from_final_hour):
                missing.extend(absent_from_final_hour.tolist())
                prefix_end = (
                    final_hour
                    if prefix_end is None
                    else min(prefix_end, final_hour)
                )

    missing_index = pd.DatetimeIndex(sorted(set(missing)))
    first_unresolved = missing_index[0] if len(missing_index) else None
    if prefix_end is None:
        prefix = ordered
    else:
        prefix = ordered.loc[actual_index < prefix_end]

    prefix_index = _utc_index(prefix) if not prefix.empty else pd.DatetimeIndex([])
    last_contiguous = prefix_index[-1] if len(prefix_index) else None
    return ContiguousPrefixResult(
        data=prefix,
        missing_timestamps=tuple(missing_index),
        first_unresolved_timestamp=first_unresolved,
        last_contiguous_timestamp=last_contiguous,
        returned_last_timestamp=actual_index[-1],
    )


def contiguous_price_prefix(
    values: pd.Series | pd.DataFrame,
    start_utc: pd.Timestamp,
    *,
    quarter_hourly_transition: pd.Timestamp,
) -> ContiguousPrefixResult:
    """Accept complete PT15M or PT60M hours without crossing missing price hours.

    A legacy Series has no resolution metadata and therefore retains the
    historical, conservative cadence rule. New raw XML responses carry an
    explicit ``source_resolution`` column, so a lone PT15M point can never be
    mistaken for a complete PT60M hour.
    """
    if values is None or values.empty:
        return ContiguousPrefixResult(values, (), None, None, None)

    ordered = values.sort_index()
    actual_index = _utc_index(ordered)
    if actual_index.duplicated().any():
        raise ValueError("Incremental price response contains duplicate timestamps.")

    start = pd.Timestamp(start_utc)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    transition = pd.Timestamp(quarter_hourly_transition).tz_convert("UTC")
    if start != start.floor("h"):
        raise ValueError("Price continuity must start at a complete UTC hour.")

    if isinstance(ordered, pd.DataFrame) and "source_resolution" in ordered:
        resolutions = ordered["source_resolution"].astype(str).tolist()
    else:
        resolutions = [
            "PT15M" if timestamp >= transition else "PT60M"
            for timestamp in actual_index
        ]
    if any(value not in {"PT15M", "PT60M"} for value in resolutions):
        raise ValueError("Price observations have an unknown source resolution.")

    resolution_by_time = dict(zip(actual_index, resolutions))
    missing = []
    first_incomplete_hour = None
    previous_resolution = "PT15M" if start >= transition else "PT60M"
    for hour in pd.date_range(start, actual_index[-1].floor("h"), freq="h"):
        points = actual_index[(actual_index >= hour) & (actual_index < hour + pd.Timedelta(hours=1))]
        hour_resolutions = {resolution_by_time[point] for point in points}
        if len(hour_resolutions) > 1:
            raise ValueError("Price hour mixes PT15M and PT60M observations.")
        resolution = next(iter(hour_resolutions)) if hour_resolutions else previous_resolution
        offsets = (0, 15, 30, 45) if resolution == "PT15M" else (0,)
        expected = pd.DatetimeIndex(
            [hour + pd.Timedelta(minutes=offset) for offset in offsets]
        )
        if not points.isin(expected).all():
            raise ValueError("Price timestamps do not align with their resolution.")
        absent = expected.difference(points)
        if len(absent):
            missing.extend(absent.tolist())
            if first_incomplete_hour is None:
                first_incomplete_hour = hour
        if len(points):
            previous_resolution = resolution

    prefix = (
        ordered
        if first_incomplete_hour is None
        else ordered.loc[actual_index < first_incomplete_hour]
    )
    prefix_index = _utc_index(prefix) if not prefix.empty else pd.DatetimeIndex([])
    missing_index = pd.DatetimeIndex(sorted(set(missing)))
    return ContiguousPrefixResult(
        data=prefix,
        missing_timestamps=tuple(missing_index),
        first_unresolved_timestamp=missing_index[0] if len(missing_index) else None,
        last_contiguous_timestamp=prefix_index[-1] if len(prefix_index) else None,
        returned_last_timestamp=actual_index[-1],
    )


def normalize_utc_timestamps(
    data: pd.DataFrame,
    timestamp_column: str = TIMESTAMP_COLUMN,
) -> pd.DataFrame:
    """Return a chronologically sorted frame with explicit, unique UTC timestamps."""
    if timestamp_column not in data.columns:
        raise ValueError(f"Dataset is missing timestamp column {timestamp_column!r}.")

    normalized = data.copy()
    timestamps = pd.to_datetime(
        normalized[timestamp_column], errors="coerce", utc=True
    )
    if timestamps.isna().any():
        raise ValueError("Dataset contains unparseable timestamps.")
    normalized[timestamp_column] = timestamps
    normalized = normalized.sort_values(timestamp_column).reset_index(drop=True)
    if normalized[timestamp_column].duplicated().any():
        duplicates = normalized.loc[
            normalized[timestamp_column].duplicated(keep=False), timestamp_column
        ]
        raise ValueError(
            "Dataset contains duplicate timestamps: "
            + ", ".join(value.isoformat() for value in duplicates.head(5))
        )
    return normalized


def latest_stored_timestamp(
    path: Path,
    timestamp_column: str = TIMESTAMP_COLUMN,
) -> pd.Timestamp | None:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    timestamps = pd.read_csv(path, usecols=[timestamp_column])[timestamp_column]
    parsed = pd.to_datetime(timestamps, errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError(f"{path} contains unparseable timestamps.")
    if parsed.duplicated().any():
        raise ValueError(f"{path} contains duplicate timestamps.")
    if not parsed.is_monotonic_increasing:
        raise ValueError(f"{path} timestamps are not chronologically ordered.")
    return parsed.iloc[-1] if not parsed.empty else None


def infer_stored_interval(
    path: Path,
    default_interval: str | pd.Timedelta,
    timestamp_column: str = TIMESTAMP_COLUMN,
) -> pd.Timedelta:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.Timedelta(default_interval)
    timestamps = pd.to_datetime(
        pd.read_csv(path, usecols=[timestamp_column])[timestamp_column],
        errors="coerce",
        utc=True,
    ).dropna()
    positive_differences = timestamps.tail(200).diff().dropna()
    positive_differences = positive_differences[positive_differences > pd.Timedelta(0)]
    if positive_differences.empty:
        return pd.Timedelta(default_interval)
    # Use the smallest recent cadence so a source transition from hourly to
    # quarter-hourly delivery cannot skip the first new sub-hourly intervals.
    return positive_differences.min()


def _overlap_is_consistent(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    timestamp_column: str,
) -> bool:
    shared = existing.merge(
        incoming,
        on=timestamp_column,
        how="inner",
        suffixes=("_existing", "_incoming"),
    )
    if shared.empty:
        return True

    value_columns = [column for column in existing.columns if column != timestamp_column]
    for column in value_columns:
        left = shared[f"{column}_existing"]
        right = shared[f"{column}_incoming"]
        numeric_left = pd.to_numeric(left, errors="coerce")
        numeric_right = pd.to_numeric(right, errors="coerce")
        numeric_values = left.notna() & right.notna() & numeric_left.notna() & numeric_right.notna()
        equal = (left.isna() & right.isna()) | (left.astype(str) == right.astype(str))
        equal.loc[numeric_values] = np.isclose(
            numeric_left.loc[numeric_values],
            numeric_right.loc[numeric_values],
            rtol=1e-9,
            atol=1e-12,
        )
        if not bool(equal.all()):
            return False
    return True


def merge_incremental_rows(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    timestamp_column: str = TIMESTAMP_COLUMN,
    allow_column_union: bool = False,
) -> tuple[pd.DataFrame, int]:
    """Merge new observations, rejecting conflicting overlap and preserving order."""
    existing = normalize_utc_timestamps(existing, timestamp_column)
    incoming = normalize_utc_timestamps(incoming, timestamp_column)

    existing_columns = set(existing.columns)
    incoming_columns = set(incoming.columns)
    if existing_columns != incoming_columns:
        if not allow_column_union:
            raise ValueError(
                "Incoming schema does not match stored schema; "
                f"stored-only={sorted(existing_columns - incoming_columns)}, "
                f"incoming-only={sorted(incoming_columns - existing_columns)}."
            )
        ordered_columns = list(existing.columns) + [
            column for column in incoming.columns if column not in existing_columns
        ]
        existing = existing.reindex(columns=ordered_columns)
        incoming = incoming.reindex(columns=ordered_columns)

    if not _overlap_is_consistent(existing, incoming, timestamp_column):
        raise ValueError("Incoming rows overlap stored timestamps with inconsistent values.")

    existing_timestamps = set(existing[timestamp_column])
    new_rows = int((~incoming[timestamp_column].isin(existing_timestamps)).sum())
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=[timestamp_column], keep="first")
    combined = combined.sort_values(timestamp_column).reset_index(drop=True)
    return combined, new_rows


def merge_generation_rows(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    *,
    revision_window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    retain_protected_conflicts: bool = False,
) -> GenerationMergeResult:
    """Merge source values under an explicit recent-revision policy.

    Strict mode remains the default. Routine incremental ingestion may retain
    stored values for conflicts outside ``revision_window`` and report them via
    ``protected_conflicts_by_column`` without changing historical data.
    """
    if revision_window is not None:
        revision_start, revision_end = map(pd.Timestamp, revision_window)
        if revision_start.tzinfo is None or revision_end.tzinfo is None:
            raise ValueError("Generation revision window must have explicit UTC timezones.")
        revision_start = revision_start.tz_convert("UTC")
        revision_end = revision_end.tz_convert("UTC")
        if revision_start >= revision_end:
            raise ValueError("Generation revision window must be positive.")
    existing = normalize_utc_timestamps(existing)
    incoming = normalize_utc_timestamps(incoming)
    columns = list(existing.columns) + [
        column for column in incoming.columns if column not in existing.columns
    ]
    stored = existing.reindex(columns=columns).set_index(TIMESTAMP_COLUMN)
    fetched = incoming.reindex(columns=columns).set_index(TIMESTAMP_COLUMN)
    overlap = stored.index.intersection(fetched.index)
    repaired_by_column = {}
    revised_by_column = {}
    protected_conflicts_by_column = {}
    protected_conflict_timestamps = set()
    for column in columns:
        if column == TIMESTAMP_COLUMN or overlap.empty:
            continue
        old = stored.loc[overlap, column]
        new = fetched.loc[overlap, column]
        both_present = old.notna() & new.notna()
        old_numeric = pd.to_numeric(old, errors="coerce")
        new_numeric = pd.to_numeric(new, errors="coerce")
        numeric = both_present & old_numeric.notna() & new_numeric.notna()
        equal = old.astype(str).eq(new.astype(str))
        equal.loc[numeric] = np.isclose(
            old_numeric.loc[numeric], new_numeric.loc[numeric],
            rtol=1e-9, atol=1e-12,
        )
        conflicts = both_present & ~equal
        if conflicts.any():
            conflict_timestamps = conflicts[conflicts].index
            unapproved = conflict_timestamps
            if revision_window is not None:
                unapproved = conflict_timestamps[
                    (conflict_timestamps < revision_start)
                    | (conflict_timestamps >= revision_end)
                ]
            if len(unapproved):
                if not retain_protected_conflicts:
                    raise ValueError(
                        "Conflicting non-null generation value at "
                        f"{unapproved[0].isoformat()} in {column}; no values were replaced."
                    )
                protected_conflicts_by_column[column] = len(unapproved)
                protected_conflict_timestamps.update(unapproved)
            approved = conflict_timestamps.difference(unapproved)
            if len(approved):
                stored.loc[approved, column] = new.loc[approved].to_numpy()
                revised_by_column[column] = len(approved)
        fill = old.isna() & new.notna()
        if fill.any():
            stored.loc[fill[fill].index, column] = new.loc[fill].to_numpy()
            repaired_by_column[column] = int(fill.sum())
    added = fetched.loc[~fetched.index.isin(stored.index)]
    combined = pd.concat([stored, added]).sort_index().reset_index()
    return GenerationMergeResult(
        combined,
        len(added),
        repaired_by_column,
        revised_by_column,
        protected_conflicts_by_column,
        tuple(sorted(protected_conflict_timestamps)),
    )


def append_csv_safely(
    path: Path,
    incoming: pd.DataFrame,
    *,
    timestamp_column: str = TIMESTAMP_COLUMN,
    allow_column_union: bool = False,
) -> AppendResult:
    """Atomically append unique UTC rows and leave the file untouched on a no-op."""
    path = Path(path)
    incoming = normalize_utc_timestamps(incoming, timestamp_column)
    if incoming.empty:
        return AppendResult(0, latest_stored_timestamp(path, timestamp_column), False)

    if path.exists():
        existing = pd.read_csv(path, low_memory=False)
        combined, new_rows = merge_incremental_rows(
            existing,
            incoming,
            timestamp_column=timestamp_column,
            allow_column_union=allow_column_union,
        )
    else:
        combined = incoming
        new_rows = len(incoming)

    latest = combined[timestamp_column].iloc[-1] if not combined.empty else None
    if new_rows == 0:
        return AppendResult(0, latest, False)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    combined.to_csv(temporary_path, index=False)
    temporary_path.replace(path)
    return AppendResult(new_rows, latest, True)


def completed_utc_hour(now: pd.Timestamp | None = None) -> pd.Timestamp:
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    return current.floor("h")

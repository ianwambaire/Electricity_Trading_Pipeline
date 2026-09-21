from pathlib import Path

import pandas as pd
import pytest

from ingestion.fetch_entsoe_data import (
    _incremental_dataset,
    repair_generation_interval,
)
from ingestion.incremental_utils import merge_generation_rows
from processing.build_silver_dataset import clean_generation
from scheduled_pipeline import _skip_derived_rebuild


START = pd.Timestamp("2026-09-20T22:00:00Z")
END = pd.Timestamp("2026-09-21T00:00:00Z")
TECHNOLOGIES = {
    "Biomass": 10.0,
    "Fossil Brown coal/Lignite": 20.0,
    "Fossil Gas": 30.0,
    "Fossil Hard coal": 40.0,
    "Hydro Run-of-river and poundage": 50.0,
    "Nuclear": 0.0,
    "Solar": 60.0,
    "Wind Offshore": 70.0,
    "Wind Onshore": 80.0,
}


def generation_hours():
    hours = pd.date_range(START, END, freq="15min", inclusive="left")
    data = pd.DataFrame({"timestamp": hours})
    for name, value in TECHNOLOGIES.items():
        data[name] = value
    return data


class GenerationClient:
    def __init__(self, data):
        self.data = data
        self.requests = []

    def query_generation(self, _country, start, end):
        self.requests.append((start, end))
        data = self.data.copy()
        data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
        return data.loc[
            data["timestamp"].between(start, end, inclusive="left")
        ].set_index("timestamp")


def test_cell_merge_enriches_nulls_without_overwriting_or_duplicates():
    existing = generation_hours()
    existing.loc[:3, ["Biomass", "Solar"]] = float("nan")
    incoming = generation_hours().loc[:3, ["timestamp", "Biomass", "Solar", "Fossil Gas"]]
    result = merge_generation_rows(existing, incoming)
    assert result.new_rows == 0
    assert result.repaired_by_column == {"Biomass": 4, "Solar": 4}
    assert result.data["timestamp"].is_unique
    assert result.data["Fossil Gas"].equals(existing["Fossil Gas"])
    assert result.data.loc[4:, :].equals(existing.loc[4:, :])


def test_cell_merge_rejects_non_null_conflict_and_duplicate_timestamps():
    existing = generation_hours()
    incoming = existing.iloc[[0]].copy()
    incoming["Solar"] = 999.0
    with pytest.raises(ValueError, match="Conflicting non-null generation"):
        merge_generation_rows(existing, incoming)
    duplicate = pd.concat([incoming, incoming], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate timestamps"):
        merge_generation_rows(existing, duplicate)


def test_controlled_repair_dry_run_then_atomic_apply_and_clean_hour(tmp_path):
    path = tmp_path / "generation.csv"
    existing = generation_hours()
    existing.loc[:3, ["Biomass", "Fossil Gas", "Solar", "Wind Onshore"]] = float("nan")
    unrelated = generation_hours().iloc[[0]].copy()
    unrelated["timestamp"] = START - pd.Timedelta(minutes=15)
    existing = pd.concat([unrelated, existing], ignore_index=True)
    existing.to_csv(path, index=False)
    unrelated_before = pd.read_csv(path).iloc[0].copy()
    before = path.read_bytes()
    client = GenerationClient(generation_hours())
    assert START not in clean_generation(path).index
    assert START + pd.Timedelta(hours=1) in clean_generation(path).index

    preview = repair_generation_interval(client, START, END, path=path)
    assert preview["repaired_cells"] == 16
    assert not preview["applied"]
    assert path.read_bytes() == before
    assert START in client.requests[0]

    applied = repair_generation_interval(client, START, END, path=path, apply=True)
    assert applied["applied"] and applied["repaired_cells"] == 16
    repaired = pd.read_csv(path)
    assert len(repaired) == len(existing)
    assert repaired["timestamp"].is_unique
    assert repaired.iloc[0].equals(unrelated_before)
    clean = clean_generation(path)
    assert START in clean.index
    assert START + pd.Timedelta(hours=1) in clean.index
    assert not (path.with_suffix(".csv.tmp")).exists()


def test_controlled_repair_keeps_file_on_source_absence_or_conflict(tmp_path):
    path = tmp_path / "generation.csv"
    existing = generation_hours()
    existing.loc[:3, "Biomass"] = float("nan")
    existing.to_csv(path, index=False)
    before = path.read_bytes()
    partial = generation_hours().drop(columns=["Biomass"])
    no_values = repair_generation_interval(
        GenerationClient(partial), START, END, path=path, apply=True
    )
    assert no_values["repaired_cells"] == 0 and not no_values["applied"]
    assert "Biomass" not in no_values["returned_columns"]
    assert "Biomass" in no_values["stored_columns_absent_from_response"]
    assert path.read_bytes() == before

    conflict = generation_hours()
    conflict.loc[0, "Fossil Gas"] = 999.0
    with pytest.raises(ValueError, match="Conflicting non-null generation"):
        repair_generation_interval(
            GenerationClient(conflict), START, END, path=path, apply=True
        )
    assert path.read_bytes() == before


def test_atomic_repair_failure_leaves_original_file_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "generation.csv"
    existing = generation_hours()
    existing.loc[0, "Biomass"] = float("nan")
    existing.to_csv(path, index=False)
    before = path.read_bytes()
    original_replace = Path.replace

    def fail_replace(self, target):
        if self.name == "generation.csv.tmp":
            raise OSError("simulated rename failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated rename failure"):
        repair_generation_interval(
            GenerationClient(generation_hours()), START, END,
            path=path, apply=True,
        )
    assert path.read_bytes() == before
    assert not path.with_suffix(".csv.tmp").exists()


def test_incremental_overlap_retries_and_enriches_existing_nulls(tmp_path):
    path = tmp_path / "generation.csv"
    existing = generation_hours()
    existing.loc[:3, "Biomass"] = float("nan")
    existing.to_csv(path, index=False)
    incoming = generation_hours().loc[:, ["timestamp", "Biomass", "Fossil Brown coal/Lignite"]]
    client = GenerationClient(incoming)
    result = _incremental_dataset(
        client, client.query_generation,
        dataset_name="generation by type", output_path=path,
        default_interval="15min", end_utc_exclusive=END,
        allow_column_union=True,
    )
    assert client.requests[0][0] < START
    assert result["new_rows"] == 0
    assert result["repaired_by_column"] == {"Biomass": 4}
    assert pd.read_csv(path)["Biomass"].notna().all()
    assert pd.read_csv(path)["timestamp"].is_unique


def test_cell_repair_forces_derived_rebuild_without_new_rows_or_watermark():
    assert _skip_derived_rebuild("incremental", False, 0, 0)
    assert not _skip_derived_rebuild("incremental", False, 0, 4)

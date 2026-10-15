from pathlib import Path

import numpy as np
import pandas as pd

from ingestion.fetch_entsoe_forecasts import (
    ENTSOE_FORECAST_COLUMNS,
    LEGACY_ENTSOE_FORECAST_COLUMNS,
)
from ingestion.fetch_operational_weather_forecasts import (
    LEGACY_WEATHER_FORECAST_COLUMNS,
    WEATHER_FORECAST_COLUMNS,
)
from processing.build_next24h_exogenous_silver import (
    DATASET_STATUS_NOT_READY,
    DATASET_STATUS_PARTIALLY_READY,
    DATASET_STATUS_READY,
    EXOGENOUS_FEATURE_COLUMNS,
    MIN_READY_CALENDAR_DAYS,
    MIN_READY_ISSUE_CYCLES,
    OUTPUT_COLUMNS,
    TARGET_COLUMN,
    assess_dataset_readiness,
    build_next24h_exogenous_frame,
    build_next24h_exogenous_silver,
)


ISSUE = pd.Timestamp("2026-10-15T12:00:00Z")
ACQUIRED = ISSUE + pd.Timedelta(minutes=5)
CREATED = ISSUE - pd.Timedelta(minutes=20)


def _silver():
    hours = pd.date_range(ISSUE - pd.Timedelta(hours=200), ISSUE + pd.Timedelta(hours=24), freq="h")
    steps = np.arange(len(hours), dtype=float)
    return pd.DataFrame(
        {
            "timestamp": hours,
            "price_eur_mwh": 40 + steps / 10,
            "load_mw": 40_000 + steps,
            "biomass_mw": 1_000 + steps / 20,
            "lignite_mw": 3_000 + steps / 20,
            "gas_mw": 2_000 + steps / 20,
            "hard_coal_mw": 1_000 + steps / 20,
            "hydro_mw": 200 + steps / 20,
            "nuclear_mw": 0.0,
            "solar_mw": 100 + steps / 20,
            "wind_offshore_mw": 100 + steps / 20,
            "wind_onshore_mw": 200 + steps / 20,
            "wind_total_mw": 300 + steps / 10,
            "temperature_2m": 10 + steps / 100,
            "relative_humidity_2m": 60 + steps / 100,
            "wind_speed_10m": 8 + steps / 100,
            "cloud_cover": 50 + steps / 100,
            "shortwave_radiation": 100 + steps / 100,
        }
    )


def _entsoe_rows(
    document_type,
    process_type,
    technology,
    *,
    resolution="PT60M",
    base_value=1_000.0,
    revision="1",
    document_id=None,
    collection_issue=ISSUE,
    acquired=ACQUIRED,
    created=CREATED,
):
    offsets = (0, 15, 30, 45) if resolution == "PT15M" else (0,)
    rows = []
    for horizon in range(1, 25):
        target_hour = ISSUE + pd.Timedelta(hours=horizon)
        for position, minute in enumerate(offsets):
            target = target_hour + pd.Timedelta(minutes=minute)
            rows.append(
                {
                    "source": "ENTSOE",
                    "document_type": document_type,
                    "process_type": process_type,
                    "document_id": document_id
                    or f"{document_type}-{process_type}-{technology}-{revision}",
                    "revision_number": revision,
                    "source_created_at_utc": created.isoformat(),
                    "collection_issue_time": collection_issue.isoformat(),
                    "acquired_at_utc": acquired.isoformat(),
                    "market_area": "DE_LU",
                    "target_timestamp": target.isoformat(),
                    "resolution": resolution,
                    "source_horizon_minutes": (target - created).total_seconds() / 60,
                    "technology": technology,
                    "value_mw": base_value + horizon * 10 + position * 10,
                }
            )
    return pd.DataFrame(rows, columns=ENTSOE_FORECAST_COLUMNS)


def _wind_rows(*, include_day=True, include_intraday=True):
    frames = []
    for technology, value in (
        ("SOLAR", 100.0),
        ("WIND_OFFSHORE", 200.0),
        ("WIND_ONSHORE", 300.0),
    ):
        if include_day:
            frames.append(
                _entsoe_rows(
                    "A69", "A01", technology, base_value=value, resolution="PT60M"
                )
            )
        if include_intraday:
            frames.append(
                _entsoe_rows(
                    "A69", "A40", technology, base_value=value + 1_000, resolution="PT15M"
                )
            )
    return pd.concat(frames, ignore_index=True)


def _weather():
    rows = []
    for horizon in range(1, 25):
        rows.append(
            {
                "collection_issue_time": ISSUE.isoformat(),
                "acquired_at_utc": ACQUIRED.isoformat(),
                "target_timestamp": (ISSUE + pd.Timedelta(hours=horizon)).isoformat(),
                "horizon_hours": horizon,
                "temperature_2m": 10.0 + horizon,
                "relative_humidity_2m": 60.0,
                "wind_speed_10m": 8.0,
                "cloud_cover": 40.0,
                "shortwave_radiation": 100.0,
                "provider": "OPEN_METEO",
                "model": "best_match",
            }
        )
    return pd.DataFrame(rows, columns=WEATHER_FORECAST_COLUMNS)


def _inputs(*, include_day=True, include_intraday=True):
    return (
        _silver(),
        _entsoe_rows("A65", "A01", "TOTAL_LOAD", base_value=40_000),
        _wind_rows(include_day=include_day, include_intraday=include_intraday),
        _entsoe_rows("A71", "A01", "TOTAL_GENERATION", base_value=60_000),
        _weather(),
    )


def _build(inputs=None):
    return build_next24h_exogenous_frame(
        *(inputs or _inputs()), generated_at_utc="2026-10-16T00:00:00Z"
    )


def test_exact_grain_schema_horizons_and_leakage_audit():
    data, report = _build()

    assert tuple(data.columns) == OUTPUT_COLUMNS
    assert len(data) == 24
    assert data["horizon_hours"].tolist() == list(range(1, 25))
    assert not data.duplicated(
        ["collection_issue_time", "target_timestamp", "horizon_hours"]
    ).any()
    assert (
        data["target_timestamp"] - data["collection_issue_time"]
    ).dt.total_seconds().div(3600).tolist() == list(range(1, 25))
    assert TARGET_COLUMN not in EXOGENOUS_FEATURE_COLUMNS
    assert report["leakage_check"]["passed"] is True
    assert report["duplicate_key_count"] == 0
    assert report["horizons_represented"] == list(range(1, 25))
    assert report["dataset_status"] == DATASET_STATUS_PARTIALLY_READY
    assert report["distinct_issue_cycles"] == 1
    assert report["distinct_calendar_days"] == 1
    assert report["horizon_coverage_count"] == 24
    assert report["horizons_missing_from_dataset"] == []


def test_pt15m_forecasts_are_averaged_only_from_complete_quarters():
    data, _ = _build()
    first = data.iloc[0]

    # Base + horizon*10 + mean([0, 10, 20, 30]).
    assert first["forecast_solar_mw"] == 1_125.0
    assert first["forecast_wind_offshore_mw"] == 1_225.0
    assert first["forecast_wind_total_mw"] == 2_550.0
    assert first["solar_forecast_resolution"] == "PT15M"


def test_incomplete_pt15m_hour_is_rejected_without_interpolation():
    inputs = list(_inputs(include_day=False, include_intraday=True))
    wind = inputs[2]
    missing = ISSUE + pd.Timedelta(hours=7, minutes=45)
    inputs[2] = wind.loc[
        ~(
            (wind["technology"] == "SOLAR")
            & (pd.to_datetime(wind["target_timestamp"], utc=True) == missing)
        )
    ].copy()
    data, report = _build(tuple(inputs))

    assert 7 not in set(data["horizon_hours"])
    assert report["excluded_rows_by_reason"]["missing_solar_forecast"] == 1
    assert report["entsoe_hourly_aggregation_rejections"]["wind_solar"] == {
        "incomplete_pt15m_hour": 1
    }


def test_latest_available_revision_selected_but_future_cycle_never_leaks():
    inputs = list(_inputs())
    load = inputs[1]
    revision_two = _entsoe_rows(
        "A65",
        "A01",
        "TOTAL_LOAD",
        base_value=50_000,
        revision="2",
        document_id="load-revision-2",
        created=CREATED + pd.Timedelta(minutes=5),
    )
    future_cycle = ISSUE + pd.Timedelta(hours=1)
    future_revision = _entsoe_rows(
        "A65",
        "A01",
        "TOTAL_LOAD",
        base_value=90_000,
        revision="99",
        document_id="future-load-revision",
        collection_issue=future_cycle,
        acquired=future_cycle + pd.Timedelta(minutes=5),
        created=future_cycle - pd.Timedelta(minutes=1),
    )
    inputs[1] = pd.concat([load, revision_two, future_revision], ignore_index=True)
    data, _ = _build(tuple(inputs))
    first_cycle = data.loc[data["collection_issue_time"] == ISSUE]

    assert set(first_cycle["load_forecast_revision_number"].astype(str)) == {"2"}
    assert first_cycle.iloc[0]["forecast_load_mw"] == 50_010.0
    assert "99" not in set(first_cycle["load_forecast_revision_number"].astype(str))


def test_intraday_is_preferred_and_day_ahead_is_deterministic_fallback():
    inputs = list(_inputs())
    wind = inputs[2]
    target = ISSUE + pd.Timedelta(hours=5)
    timestamps = pd.to_datetime(wind["target_timestamp"], utc=True)
    inputs[2] = wind.loc[
        ~(
            (wind["process_type"] == "A40")
            & (wind["technology"] == "SOLAR")
            & (timestamps.dt.floor("h") == target)
        )
    ].copy()
    data, report = _build(tuple(inputs))

    assert data.loc[data["horizon_hours"] == 1, "solar_forecast_process_type"].item() == "A40"
    assert data.loc[data["horizon_hours"] == 5, "solar_forecast_process_type"].item() == "A01"
    assert report["wind_solar_process_usage"]["day_ahead_A01"] == 1
    assert report["wind_solar_process_usage"]["intraday_A40"] == 71


def test_open_meteo_and_target_price_are_exactly_target_aligned():
    silver, *rest = _inputs()
    data, _ = _build((silver, *rest))
    row = data.loc[data["horizon_hours"] == 9].iloc[0]
    expected_price = silver.loc[
        pd.to_datetime(silver["timestamp"], utc=True) == ISSUE + pd.Timedelta(hours=9),
        "price_eur_mwh",
    ].item()

    assert row["forecast_temperature_2m"] == 19.0
    assert row[TARGET_COLUMN] == expected_price
    assert row["target_hour"] == (ISSUE + pd.Timedelta(hours=9)).hour


def test_missing_exact_target_price_excludes_only_that_training_row():
    inputs = list(_inputs())
    silver = inputs[0]
    missing = ISSUE + pd.Timedelta(hours=12)
    silver.loc[pd.to_datetime(silver["timestamp"], utc=True) == missing, "price_eur_mwh"] = np.nan
    inputs[0] = silver
    data, report = _build(tuple(inputs))

    assert 12 not in set(data["horizon_hours"])
    assert report["excluded_rows_by_reason"]["missing_target_price"] == 1


def test_future_realized_non_price_values_never_enter_features():
    original = list(_inputs())
    changed = [frame.copy() for frame in original]
    future = pd.to_datetime(changed[0]["timestamp"], utc=True) > ISSUE
    for column in (
        "load_mw",
        "solar_mw",
        "wind_offshore_mw",
        "wind_onshore_mw",
        "temperature_2m",
        "relative_humidity_2m",
    ):
        changed[0].loc[future, column] += 999_999

    baseline, _ = _build(tuple(original))
    mutated, _ = _build(tuple(changed))
    pd.testing.assert_frame_equal(
        baseline.loc[:, EXOGENOUS_FEATURE_COLUMNS],
        mutated.loc[:, EXOGENOUS_FEATURE_COLUMNS],
    )


def test_identical_source_duplicates_do_not_create_duplicate_output_rows():
    inputs = list(_inputs())
    inputs[1] = pd.concat([inputs[1], inputs[1].iloc[[0]]], ignore_index=True)
    data, report = _build(tuple(inputs))

    assert len(data) == 24
    assert report["duplicate_key_count"] == 0


def test_legacy_vintage_rows_remain_readable_without_claiming_earlier_availability():
    inputs = list(_inputs())
    for index in (1, 2, 3):
        inputs[index] = (
            inputs[index]
            .drop(columns="collection_issue_time")
            .rename(columns={"source_horizon_minutes": "horizon_minutes"})
            .loc[:, LEGACY_ENTSOE_FORECAST_COLUMNS]
        )
    inputs[4] = (
        inputs[4]
        .rename(columns={"collection_issue_time": "forecast_issue_time"})
        .loc[:, LEGACY_WEATHER_FORECAST_COLUMNS]
    )
    data, report = _build(tuple(inputs))

    assert len(data) == 24
    assert report["legacy_entsoe_rows"]["load"] == 24
    assert set(data["load_forecast_collection_issue_time"]) == {ISSUE}


def test_file_builder_writes_only_new_offline_dataset_and_quality_report(tmp_path):
    silver, load, wind, generation, weather = _inputs()
    paths = {
        "observed_silver_path": tmp_path / "silver.csv",
        "load_vintages_path": tmp_path / "load.csv",
        "wind_solar_vintages_path": tmp_path / "wind.csv",
        "generation_vintages_path": tmp_path / "generation.csv",
        "weather_vintages_path": tmp_path / "weather.csv",
        "output_path": tmp_path / "processed/exogenous.csv",
        "quality_report_path": tmp_path / "reports/quality.json",
    }
    for frame, key in zip(
        (silver, load, wind, generation, weather),
        (
            "observed_silver_path",
            "load_vintages_path",
            "wind_solar_vintages_path",
            "generation_vintages_path",
            "weather_vintages_path",
        ),
    ):
        frame.to_csv(paths[key], index=False)

    output, report = build_next24h_exogenous_silver(**paths)

    assert len(pd.read_csv(paths["output_path"])) == len(output) == 24
    assert paths["quality_report_path"].exists()
    assert report["leakage_check"]["passed"] is True


def test_builder_is_not_wired_to_production_forecasting():
    project = Path(__file__).resolve().parents[1]
    scheduled = (project / "src/scheduled_pipeline.py").read_text(encoding="utf-8")
    production = (project / "src/models/next24h_production.py").read_text(encoding="utf-8")

    assert "build_next24h_exogenous_silver" not in scheduled
    assert "build_next24h_exogenous_silver" not in production


def _readiness_rows(cycles, horizons=range(1, 25)):
    rows = []
    for issue in cycles:
        for horizon in horizons:
            rows.append(
                {
                    "collection_issue_time": issue,
                    "target_timestamp": issue + pd.Timedelta(hours=horizon),
                    "horizon_hours": horizon,
                }
            )
    return pd.DataFrame(rows)


def _passing_audit(data):
    return {
        "passed": True,
        "duplicate_key_count": int(
            data.duplicated(
                ["collection_issue_time", "target_timestamp", "horizon_hours"]
            ).sum()
        ),
    }


def test_zero_output_rows_are_not_ready_in_generated_quality_report():
    inputs = list(_inputs())
    silver = inputs[0]
    future = pd.to_datetime(silver["timestamp"], utc=True) > ISSUE
    silver.loc[future, "price_eur_mwh"] = np.nan
    inputs[0] = silver

    data, report = _build(tuple(inputs))

    assert data.empty
    assert report["dataset_status"] == DATASET_STATUS_NOT_READY
    assert "No complete training rows are currently available" in report[
        "readiness_reasons"
    ]
    assert report["leakage_check"]["passed"] is True


def test_complete_rows_with_insufficient_history_are_partially_ready():
    data = _readiness_rows([ISSUE])
    readiness = assess_dataset_readiness(data, _passing_audit(data))

    assert readiness["dataset_status"] == DATASET_STATUS_PARTIALLY_READY
    assert readiness["complete_issue_cycles"] == 1
    assert readiness["horizon_coverage_count"] == 24
    assert readiness["readiness_reasons"]


def test_full_engineering_thresholds_are_ready_for_evaluation():
    cycles = [
        ISSUE.floor("D") + pd.Timedelta(days=day, hours=hour)
        for day in range(MIN_READY_CALENDAR_DAYS)
        for hour in (0, 12)
    ][:MIN_READY_ISSUE_CYCLES]
    data = _readiness_rows(cycles)
    readiness = assess_dataset_readiness(data, _passing_audit(data))

    assert readiness["dataset_status"] == DATASET_STATUS_READY
    assert readiness["distinct_issue_cycles"] == MIN_READY_ISSUE_CYCLES
    assert readiness["distinct_calendar_days"] == MIN_READY_CALENDAR_DAYS
    assert readiness["horizons_missing_from_dataset"] == []
    assert readiness["readiness_reasons"] == []


def test_leakage_failure_can_never_be_ready_for_evaluation():
    cycles = [
        ISSUE.floor("D") + pd.Timedelta(days=day, hours=hour)
        for day in range(MIN_READY_CALENDAR_DAYS)
        for hour in (0, 12)
    ][:MIN_READY_ISSUE_CYCLES]
    data = _readiness_rows(cycles)
    audit = _passing_audit(data)
    audit["passed"] = False
    readiness = assess_dataset_readiness(data, audit)

    assert readiness["dataset_status"] == DATASET_STATUS_NOT_READY
    assert "Leakage audit did not pass" in readiness["readiness_reasons"]


def test_missing_horizons_prevent_ready_for_evaluation():
    cycles = [
        ISSUE.floor("D") + pd.Timedelta(days=day, hours=hour)
        for day in range(MIN_READY_CALENDAR_DAYS)
        for hour in (0, 12)
    ][:MIN_READY_ISSUE_CYCLES]
    data = _readiness_rows(cycles, horizons=range(1, 24))
    readiness = assess_dataset_readiness(data, _passing_audit(data))

    assert readiness["dataset_status"] == DATASET_STATUS_NOT_READY
    assert readiness["horizon_coverage_count"] == 23
    assert readiness["horizons_missing_from_dataset"] == [24]


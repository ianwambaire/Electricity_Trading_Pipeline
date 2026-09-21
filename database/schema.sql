-- PowerFlow primary SQLite schema
--
-- SQLite stores operational pipeline metadata, data-quality history,
-- incidents, and measured stage timings only.
-- ENTSO-E raw, silver, and gold datasets remain in the file-based data layers;
-- model tracking remains in MLflow and generated report files.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    status TEXT NOT NULL,
    records_processed INTEGER,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_run_time
    ON pipeline_runs (run_time DESC);

CREATE TABLE IF NOT EXISTS data_quality_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_time TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_data_quality_results_check_time
    ON data_quality_results (check_time DESC);

CREATE TABLE IF NOT EXISTS operational_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_operational_incidents_time
    ON operational_incidents (timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_operational_incidents_event
    ON operational_incidents (component, event_type, id DESC);

CREATE TABLE IF NOT EXISTS pipeline_stage_timings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    start_timestamp_utc TEXT NOT NULL,
    end_timestamp_utc TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pipeline_stage_timings_run
    ON pipeline_stage_timings (run_id, id);
CREATE INDEX IF NOT EXISTS idx_pipeline_stage_timings_time
    ON pipeline_stage_timings (start_timestamp_utc DESC);

-- Legacy SQLite tables are intentionally not created by the primary schema:
--   clean_market_data  - legacy EIA cleaned dataset storage
--   model_registry     - replaced by MLflow experiment tracking
--   predictions        - replaced by data/reports/actual_vs_predicted.csv
-- Existing local databases may retain these tables and their historical rows.

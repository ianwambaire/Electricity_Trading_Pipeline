-- PowerFlow primary SQLite schema
--
-- SQLite stores operational pipeline metadata and data-quality history only.
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

-- Legacy SQLite tables are intentionally not created by the primary schema:
--   clean_market_data  - legacy EIA cleaned dataset storage
--   model_registry     - replaced by MLflow experiment tracking
--   predictions        - replaced by data/reports/actual_vs_predicted.csv
-- Existing local databases may retain these tables and their historical rows.

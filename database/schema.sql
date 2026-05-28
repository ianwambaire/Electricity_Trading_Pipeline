CREATE TABLE IF NOT EXISTS clean_market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    market_price REAL NOT NULL,
    demand_mw REAL NOT NULL,
    supply_mw REAL NOT NULL,
    weather_temperature REAL,
    region TEXT,
    energy_source TEXT,
    hour INTEGER,
    day INTEGER,
    month INTEGER,
    day_of_week TEXT,
    supply_demand_gap REAL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    status TEXT NOT NULL,
    records_processed INTEGER,
    message TEXT
);

CREATE TABLE IF NOT EXISTS data_quality_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_time TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT
);
CREATE TABLE IF NOT EXISTS model_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    training_date TEXT NOT NULL,
    rmse REAL,
    mae REAL,
    r2_score REAL
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_time TEXT NOT NULL,
    predicted_price REAL NOT NULL,
    actual_price REAL,
    model_version TEXT
);
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EIA_API_KEY = os.getenv("EIA_API_KEY")

DATA_DIR = PROJECT_ROOT / "data"
EXTERNAL_DATA_DIR = DATA_DIR / "external"
FINAL_DATA_DIR = DATA_DIR / "final"
RAW_DATA_DIR = DATA_DIR / "raw"
BACKUP_DATA_DIR = DATA_DIR / "backups"

EIA_ELECTRICITY_PATH = EXTERNAL_DATA_DIR / "eia_electricity_data.csv"
WEATHER_DATA_PATH = EXTERNAL_DATA_DIR / "open_meteo_weather_data.csv"

FINAL_REAL_WORLD_DATASET_PATH = FINAL_DATA_DIR / "real_world_electricity_dataset.csv"

PIPELINE_INPUT_PATH = RAW_DATA_DIR / "electricity_market_data.csv"

DEFAULT_STATE_CODE = "CA"
DEFAULT_EIA_LENGTH = 120

DEFAULT_LATITUDE = 36.7783
DEFAULT_LONGITUDE = -119.4179
DEFAULT_START_DATE = "2015-01-01"
DEFAULT_END_DATE = "2025-12-31"
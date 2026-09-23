import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from powerflow_secrets import get_secret  # noqa: E402

load_dotenv()

api_key = get_secret("ENTSOE_API_KEY")

client = EntsoePandasClient(api_key=api_key)

country_code = "DE_LU"

start = pd.Timestamp("2024-01-01", tz="Europe/Berlin")
end = pd.Timestamp("2024-01-03", tz="Europe/Berlin")

print("Fetching ENTSO-E day-ahead prices...")

prices = client.query_day_ahead_prices(
    country_code,
    start=start,
    end=end
)

print(prices.head())
print(prices.shape)

prices.to_csv("data/raw/entsoe/test_prices.csv")

print("Saved to data/raw/entsoe/test_prices.csv")

import os
import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

load_dotenv()

api_key = os.getenv("ENTSOE_API_KEY")

if not api_key:
    raise ValueError("ENTSOE_API_KEY not found. Check your .env file.")

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
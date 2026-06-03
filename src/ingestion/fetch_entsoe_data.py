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

start = pd.Timestamp("2022-01-01", tz="Europe/Berlin")
end = pd.Timestamp("2025-01-01", tz="Europe/Berlin")


def save_series(series, filepath, value_name):
    df = series.reset_index()
    df.columns = ["timestamp", value_name]
    df.to_csv(filepath, index=False)
    print(f"Saved {filepath} with shape {df.shape}")


print("Fetching day-ahead prices...")
prices = client.query_day_ahead_prices(country_code, start=start, end=end)
save_series(prices, "data/raw/entsoe/prices.csv", "price_eur_mwh")


print("Fetching actual load...")
load = client.query_load(country_code, start=start, end=end)
save_series(load, "data/raw/entsoe/load.csv", "load_mw")


print("Fetching generation by type...")
generation = client.query_generation(country_code, start=start, end=end)
generation = generation.reset_index()
generation.rename(columns={"index": "timestamp"}, inplace=True)
generation.to_csv("data/raw/entsoe/generation.csv", index=False)

print(f"Saved data/raw/entsoe/generation.csv with shape {generation.shape}")
print("ENTSO-E ingestion completed.")
import pandas as pd


def clean_prices():
    prices = pd.read_csv("data/raw/entsoe/prices.csv")
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True)
    prices = prices.set_index("timestamp").sort_index()
    return prices


def clean_load():
    load = pd.read_csv("data/raw/entsoe/load.csv")
    load["timestamp"] = pd.to_datetime(load["timestamp"], utc=True)
    load = load.set_index("timestamp").sort_index()

    load["load_mw"] = pd.to_numeric(load["load_mw"], errors="coerce")

    hourly_load = load.resample("h").mean()
    return hourly_load


def clean_generation():
    generation = pd.read_csv("data/raw/entsoe/generation.csv", low_memory=False)

    generation["timestamp"] = pd.to_datetime(
        generation["timestamp"],
        errors="coerce",
        utc=True
    )

    generation = generation.dropna(subset=["timestamp"])
    generation = generation.set_index("timestamp").sort_index()

    for col in generation.columns:
        generation[col] = pd.to_numeric(generation[col], errors="coerce")

    hourly_generation = generation.resample("h").mean()

    useful_columns = [
        "Biomass",
        "Fossil Brown coal/Lignite",
        "Fossil Gas",
        "Fossil Hard coal",
        "Hydro Run-of-river and poundage",
        "Nuclear",
        "Solar",
        "Wind Offshore",
        "Wind Onshore",
    ]

    existing_columns = [
        col for col in useful_columns
        if col in hourly_generation.columns
    ]

    hourly_generation = hourly_generation[existing_columns]

    hourly_generation = hourly_generation.rename(
        columns={
            "Biomass": "biomass_mw",
            "Fossil Brown coal/Lignite": "lignite_mw",
            "Fossil Gas": "gas_mw",
            "Fossil Hard coal": "hard_coal_mw",
            "Hydro Run-of-river and poundage": "hydro_mw",
            "Nuclear": "nuclear_mw",
            "Solar": "solar_mw",
            "Wind Offshore": "wind_offshore_mw",
            "Wind Onshore": "wind_onshore_mw",
        }
    )

    hourly_generation["wind_total_mw"] = (
        hourly_generation.get("wind_offshore_mw", 0)
        + hourly_generation.get("wind_onshore_mw", 0)
    )

    return hourly_generation


def clean_weather():
    weather = pd.read_csv("data/raw/weather/open_meteo_weather.csv")

    weather["timestamp"] = pd.to_datetime(weather["timestamp"])

    weather["timestamp"] = (
        weather["timestamp"]
        .dt.tz_localize(
            "Europe/Berlin",
            nonexistent="shift_forward",
            ambiguous="NaT"
        )
        .dt.tz_convert("UTC")
    )

    weather = weather.dropna(subset=["timestamp"])
    weather = weather.set_index("timestamp").sort_index()

    for col in weather.columns:
        weather[col] = pd.to_numeric(weather[col], errors="coerce")

    # In case DST creates duplicate UTC timestamps, average them
    weather = weather.groupby(weather.index).mean()

    return weather

def build_silver_dataset():
    prices = clean_prices()
    load = clean_load()
    generation = clean_generation()
    weather = clean_weather()

    df = prices.join(load, how="inner")
    df = df.join(generation, how="inner")
    df = df.join(weather, how="inner")

    df = df.reset_index()

    df.to_csv("data/processed/silver_electricity_market_data.csv", index=False)

    print("Silver dataset created.")
    print(df.head())
    print(df.shape)
    print(df.columns)


if __name__ == "__main__":
    build_silver_dataset()
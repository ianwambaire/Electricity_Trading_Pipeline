from pathlib import Path

import pandas as pd


QUARTER_HOURLY_PRICE_START_UTC = pd.Timestamp("2025-09-30T22:00:00Z")


def set_utc_timestamp_index(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        errors="coerce",
        utc=True,
    )
    if data["timestamp"].isna().any() or data["timestamp"].duplicated().any():
        raise ValueError("Raw source timestamps must be valid and unique in UTC.")
    data = data.set_index("timestamp").sort_index()
    return data


def aggregate_quarter_hourly(
    data: pd.DataFrame,
    *,
    require_complete_hours: bool = False,
    required_columns: list[str] | None = None,
) -> pd.DataFrame:
    data = data.copy()
    data.index = pd.to_datetime(data.index, utc=True)
    data = data.sort_index()
    hourly = data.resample("h").mean()
    if require_complete_hours:
        counts = data.resample("h").size()
        aligned = (
            data.index.minute.isin([0, 15, 30, 45])
            & (data.index.second == 0)
            & (data.index.microsecond == 0)
            & (data.index.nanosecond == 0)
        )
        aligned_hours = pd.Series(aligned, index=data.index).resample("h").min()
        complete = counts.eq(4) & aligned_hours
        if required_columns:
            complete &= (
                data[required_columns].notna().resample("h").sum().eq(4).all(axis=1)
            )
        hourly = hourly.loc[complete[complete].index]
    return hourly


def clean_prices(path: Path = Path("data/raw/entsoe/prices.csv")):
    prices = pd.read_csv(path)
    parsed = pd.to_datetime(prices["timestamp"], errors="coerce", utc=True)
    if parsed.isna().any() or parsed.duplicated().any():
        raise ValueError("Raw ENTSO-E prices require unique, valid UTC timestamps.")
    prices = set_utc_timestamp_index(prices)
    return aggregate_hourly_prices(prices)


def aggregate_hourly_prices(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()
    prices.index = pd.to_datetime(prices.index, utc=True)
    prices = prices.sort_index()
    if prices.index.duplicated().any():
        raise ValueError("Raw ENTSO-E prices contain duplicate timestamps.")
    prices["price_eur_mwh"] = pd.to_numeric(
        prices["price_eur_mwh"], errors="coerce"
    )
    hourly = prices[["price_eur_mwh"]].resample("h").mean()
    counts = prices.resample("h").size()
    if "source_resolution" not in prices.columns:
        quarter_hourly = hourly.index >= QUARTER_HOURLY_PRICE_START_UTC
        expected_count = pd.Series(
            [4 if recent else 1 for recent in quarter_hourly], index=hourly.index
        )
        aligned = (
            (prices.index.second == 0)
            & (prices.index.microsecond == 0)
            & (prices.index.nanosecond == 0)
            & (
                (
                    (prices.index >= QUARTER_HOURLY_PRICE_START_UTC)
                    & (prices.index.minute % 15 == 0)
                )
                | (
                    (prices.index < QUARTER_HOURLY_PRICE_START_UTC)
                    & (prices.index.minute == 0)
                )
            )
        )
        aligned_hours = pd.Series(aligned, index=prices.index).resample("h").min()
        valid_prices = prices["price_eur_mwh"].notna().resample("h").min()
        complete = counts.eq(expected_count) & aligned_hours & valid_prices
        return hourly.loc[complete]

    resolutions = prices["source_resolution"].copy()
    legacy = resolutions.isna()
    resolutions.loc[legacy] = [
        "PT15M" if timestamp >= QUARTER_HOURLY_PRICE_START_UTC else "PT60M"
        for timestamp in resolutions.index[legacy]
    ]
    if not resolutions.isin({"PT15M", "PT60M"}).all():
        raise ValueError("Raw ENTSO-E prices contain an unsupported resolution.")

    hours = prices.index.floor("h")
    resolution_by_hour = resolutions.groupby(hours).first()
    mixed_resolution = resolutions.groupby(hours).nunique() > 1
    if mixed_resolution.any():
        raise ValueError("Raw ENTSO-E price hour mixes source resolutions.")
    expected_count = resolution_by_hour.map({"PT15M": 4, "PT60M": 1})
    aligned = (
        (prices.index.second == 0)
        & (prices.index.microsecond == 0)
        & (prices.index.nanosecond == 0)
        & (
            (
                (resolutions.to_numpy() == "PT15M")
                & (prices.index.minute % 15 == 0)
            )
            | (prices.index.minute == 0)
        )
    )
    aligned_by_hour = pd.Series(aligned, index=prices.index).groupby(hours).all()
    valid_values = prices["price_eur_mwh"].notna().groupby(hours).all()
    complete = (
        counts.reindex(resolution_by_hour.index).eq(expected_count)
        & aligned_by_hour
        & valid_values
    )
    return hourly.loc[complete[complete].index]


def clean_load(path: Path = Path("data/raw/entsoe/load.csv")):
    load = pd.read_csv(path)
    load = set_utc_timestamp_index(load)

    load["load_mw"] = pd.to_numeric(load["load_mw"], errors="coerce")

    hourly_load = aggregate_quarter_hourly(
        load, require_complete_hours=True, required_columns=["load_mw"]
    )
    return hourly_load


def clean_generation(path: Path = Path("data/raw/entsoe/generation.csv")):
    generation = pd.read_csv(path, low_memory=False)

    generation = set_utc_timestamp_index(generation)

    for col in generation.columns:
        generation[col] = pd.to_numeric(generation[col], errors="coerce")

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
        if col in generation.columns
    ]

    hourly_generation = aggregate_quarter_hourly(
        generation,
        require_complete_hours=True,
        required_columns=[
            column for column in existing_columns if column != "Nuclear"
        ],
    )

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
    raw_timestamps = weather["timestamp"].astype(str)
    explicit_timezone = raw_timestamps.str.contains(
        r"(?:Z|[+-][0-9]{2}:[0-9]{2})$",
        regex=True,
    )
    if not explicit_timezone.all():
        raise ValueError(
            "Open-Meteo timestamps must be explicitly UTC. "
            "Re-run src/ingestion/fetch_weather_data.py."
        )

    weather = set_utc_timestamp_index(weather)
    if (weather.index != weather.index.floor("h")).any():
        raise ValueError("Open-Meteo weather timestamps must be exact UTC hours.")

    for col in weather.columns:
        weather[col] = pd.to_numeric(weather[col], errors="coerce")

    return weather.dropna()


def build_silver_dataset():
    prices = clean_prices()
    load = clean_load()
    generation = clean_generation()
    weather = clean_weather()

    df = prices.join(load, how="inner")
    df = df.join(generation, how="inner")
    df = df.join(weather, how="inner")

    df = df.sort_index().reset_index()

    output_path = "data/processed/silver_electricity_market_data.csv"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    print("Silver dataset created.")
    print(df.head())
    print(df.shape)
    print(df.columns)


if __name__ == "__main__":
    build_silver_dataset()

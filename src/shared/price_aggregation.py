"""Read-only price aggregation for the standalone API release.

Kept equivalent to the pipeline aggregator; parity tests guard completeness rules.
The API distribution intentionally excludes pipeline execution modules.
"""
import pandas as pd

QUARTER_HOURLY_PRICE_START_UTC = pd.Timestamp("2025-09-30T22:00:00Z")


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

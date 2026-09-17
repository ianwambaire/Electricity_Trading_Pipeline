import argparse
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

if __package__:
    from .historical_range import get_historical_date_range, iter_time_chunks
else:
    from historical_range import get_historical_date_range, iter_time_chunks


COUNTRY_CODE = "DE_LU"
RAW_ENTSOE_DIR = Path("data/raw/entsoe")
SENSITIVE_QUERY_PARAMETERS = {
    "accesskey",
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "credential",
    "key",
    "passwd",
    "password",
    "secret",
    "securitytoken",
    "signature",
    "token",
}


def redact_sensitive_url(url: str) -> str:
    """Return a URL with credential-like query values replaced."""
    parts = urlsplit(url)
    redacted_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = key.casefold().replace("_", "").replace("-", "")
        safe_value = "[REDACTED]" if normalized_key in SENSITIVE_QUERY_PARAMETERS else value
        redacted_query.append((key, safe_value))

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(redacted_query),
            parts.fragment,
        )
    )


def combine_time_chunks(chunks: list[pd.Series | pd.DataFrame]):
    if not chunks:
        raise ValueError("At least one non-empty ENTSO-E chunk is required.")

    combined = pd.concat(chunks)
    combined = combined.loc[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def fetch_in_chunks(client, query_method, historical_range, dataset_name):
    chunks = []
    for chunk_start, chunk_end in iter_time_chunks(historical_range):
        print(
            f"Fetching {dataset_name}: "
            f"{chunk_start.date()} to {(chunk_end - pd.Timedelta(days=1)).date()}"
        )
        try:
            chunk = query_method(
                COUNTRY_CODE,
                start=chunk_start,
                end=chunk_end,
            )
        except Exception as error:
            error_type = type(error).__name__
            print(
                f"ENTSO-E {dataset_name} failed for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}; "
                f"error type: {error_type}."
            )
            raise RuntimeError(
                f"ENTSO-E {dataset_name} unavailable for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}; "
                f"error type: {error_type}."
            ) from None

        if chunk is not None:
            chunk = chunk.loc[
                (chunk.index >= chunk_start) & (chunk.index < chunk_end)
            ]
        if chunk is None or chunk.empty:
            raise RuntimeError(
                f"ENTSO-E returned no {dataset_name} for "
                f"{chunk_start.isoformat()} to {chunk_end.isoformat()}."
            )
        chunks.append(chunk)

    return combine_time_chunks(chunks)


def save_series(series, filepath: Path, value_name: str):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(series, pd.Series):
        data = series.rename(value_name).to_frame()
    elif series.shape[1] == 1:
        data = series.copy()
        data.columns = [value_name]
    else:
        raise ValueError(f"Expected one {value_name} column, found {series.shape[1]}.")

    data.index.name = "timestamp"
    data.reset_index().to_csv(filepath, index=False)
    print(f"Saved {filepath} with shape {data.shape}")


def save_generation(generation: pd.DataFrame, filepath: Path):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    generation = generation.copy()
    generation.index.name = "timestamp"
    generation.reset_index().to_csv(filepath, index=False)
    print(f"Saved {filepath} with shape {generation.shape}")


def fetch_entsoe_data(start_date: str | None = None, end_date: str | None = None):
    load_dotenv()
    api_key = os.getenv("ENTSOE_API_KEY")
    if not api_key:
        raise ValueError("ENTSOE_API_KEY not found. Check your .env file.")

    historical_range = get_historical_date_range(start_date, end_date)
    client = EntsoePandasClient(api_key=api_key)
    RAW_ENTSOE_DIR.mkdir(parents=True, exist_ok=True)

    prices = fetch_in_chunks(
        client,
        client.query_day_ahead_prices,
        historical_range,
        "day-ahead prices",
    )
    save_series(prices, RAW_ENTSOE_DIR / "prices.csv", "price_eur_mwh")

    load = fetch_in_chunks(
        client,
        client.query_load,
        historical_range,
        "actual load",
    )
    save_series(load, RAW_ENTSOE_DIR / "load.csv", "load_mw")

    generation = fetch_in_chunks(
        client,
        client.query_generation,
        historical_range,
        "generation by type",
    )
    save_generation(generation, RAW_ENTSOE_DIR / "generation.csv")

    print("ENTSO-E ingestion completed.")


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch historical ENTSO-E data.")
    parser.add_argument("--start-date", help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", help="Inclusive end date (YYYY-MM-DD).")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    fetch_entsoe_data(arguments.start_date, arguments.end_date)

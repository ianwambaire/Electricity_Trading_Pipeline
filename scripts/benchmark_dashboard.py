#!/usr/bin/env python3
"""Measure representative PowerFlow dashboard reruns with Streamlit AppTest."""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import streamlit as st
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

DASHBOARD_PATH = PROJECT_ROOT / "src" / "dashboard.py"
PAGES = (
    "Executive Overview",
    "Forecasting",
    "Model Insights",
    "Pipeline Summary",
)


def measure_sequence() -> dict[str, float]:
    st.cache_data.clear()
    app = AppTest.from_file(str(DASHBOARD_PATH))
    timings = {}

    started = time.perf_counter()
    app.run(timeout=60)
    timings[PAGES[0]] = time.perf_counter() - started

    for page in PAGES[1:]:
        started = time.perf_counter()
        app.radio[0].set_value(page).run(timeout=60)
        timings[page] = time.perf_counter() - started

    if app.exception:
        raise RuntimeError(f"Dashboard benchmark failed: {app.exception}")
    return timings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    runs = [measure_sequence() for _ in range(args.runs)]
    medians = {
        page: statistics.median(run[page] for run in runs)
        for page in PAGES
    }
    print(json.dumps({"runs": runs, "median_seconds": medians}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

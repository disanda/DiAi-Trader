#!/usr/bin/env python3
"""Run configured agents against the prediction competition data."""

import argparse
import copy
import json
from pathlib import Path

try:
    from .competition import load_indices, run_competition
except ImportError:  # Direct execution: python predict/run_test.py
    from competition import load_indices, run_competition


def prediction_dates(config):
    """Resolve a date range to actual index trading dates."""
    if config.get("prediction_date"):
        return [str(config["prediction_date"]).replace("-", "")]
    start = str(config.get("prediction_start_date", "")).replace("-", "")
    end = str(config.get("prediction_end_date", "")).replace("-", "")
    if not start or not end or start > end:
        raise ValueError("Set prediction_date or a valid prediction_start_date/prediction_end_date range")
    dates = set()
    for index in load_indices():
        dates.update(str(row.get("trade_date", "")).replace("-", "") for row in index["records"])
    return sorted(date for date in dates if start <= date <= end)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline prediction competition")
    parser.add_argument("--config", default=Path(__file__).with_name("test_config.json"), type=Path)
    args = parser.parse_args()
    with args.config.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    dates = prediction_dates(config)
    if not dates:
        raise ValueError("No index trading dates found in the requested range")
    for target_date in dates:
        run_config = copy.deepcopy(config)
        run_config["prediction_date"] = target_date
        for path in run_competition(run_config):
            print(f"Saved: {path}")


if __name__ == "__main__":
    main()

"""Trusted market-data loading tool."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from predict_v2.feature_layer.validation import default_cutoff, parse_timestamp, validate_history


class MarketDataTool:
    name = "load_market_history"

    def __init__(self, project_root: Path, data_paths: dict[str, str]):
        self.project_root = project_root
        self.data_paths = data_paths

    def run(self, asset_type: str, symbol: str, prediction_date: str,
            cutoff_text: str | None, history_days: int) -> dict[str, Any]:
        if asset_type not in self.data_paths:
            raise ValueError("unsupported_asset_type")
        directory = (self.project_root / self.data_paths[asset_type]).resolve()
        path = directory / f"{symbol}.json"
        if path.parent != directory or not path.is_file():
            raise FileNotFoundError(f"market_data_not_found:{symbol}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
            raise ValueError("invalid_market_data_file")
        cutoff = parse_timestamp(cutoff_text) if cutoff_text else default_cutoff(prediction_date)
        rows, quality = validate_history(payload["records"], prediction_date, cutoff, history_days, symbol)
        name = next((str(row.get("name")) for row in reversed(payload["records"]) if row.get("name")), symbol)
        return {"symbol": symbol, "name": name, "asset_type": asset_type,
                "prediction_date": str(prediction_date).replace("-", ""),
                "cutoff": cutoff.isoformat(), "rows": rows, "data_quality": quality,
                "source_path": str(path.relative_to(self.project_root))}

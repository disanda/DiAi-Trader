"""Single deterministic feature pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .returns import compact_return_bars, compute_return_features
from .signals import derive_signals


def analyze(rows: list[dict[str, Any]], compact_days: int) -> dict[str, Any]:
    features = compute_return_features(rows)
    signals = derive_signals(features)
    canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return {
        "schema_version": "feature-report-2.0",
        "basis": "returns_and_relative_values_only",
        "coverage": {"sessions": len(rows), "start": rows[0]["trade_date"], "end": rows[-1]["trade_date"]},
        "features": features,
        "signals": signals,
        "compact_return_bars": compact_return_bars(rows, compact_days),
        "input_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "limitations": ["Descriptive deterministic features, not calibrated probabilities.",
                        "No absolute prices are exposed to the LLM."],
    }

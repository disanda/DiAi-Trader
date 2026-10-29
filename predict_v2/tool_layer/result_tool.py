"""Validate and persist the model's predicted OHLC candle."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

TOOL_NAME = "submit_prediction"
TEXT_FIELDS = ("analysis", "counter_view")
LIST_FIELDS = ("signal_relationships", "positive_evidence", "negative_evidence", "uncertainties", "risk_scenarios")


def prediction_tool_schema() -> dict[str, Any]:
    return {"type": "function", "function": {"name": TOOL_NAME,
        "description": "Submit a predicted OHLC candle for the next trading session.",
        "parameters": {"type": "object", "additionalProperties": False,
            "required": ["predicted_open", "predicted_high", "predicted_low", "predicted_close",
                         "confidence_level", "analysis", "signal_relationships", "positive_evidence",
                         "negative_evidence", "uncertainties", "counter_view", "risk_scenarios"],
            "properties": {
                "predicted_open": {"type": "number", "exclusiveMinimum": 0},
                "predicted_high": {"type": "number", "exclusiveMinimum": 0},
                "predicted_low": {"type": "number", "exclusiveMinimum": 0},
                "predicted_close": {"type": "number", "exclusiveMinimum": 0},
                "confidence_level": {"type": "string", "enum": ["low", "medium", "high"]},
                "analysis": {"type": "string"},
                "signal_relationships": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "positive_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "negative_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "uncertainties": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "counter_view": {"type": "string"},
                "risk_scenarios": {"type": "array", "items": {"type": "string"}, "maxItems": 20}
            }}}}


def validate_submission(value: dict[str, Any], reference_close: float | None = None) -> dict[str, Any]:
    required = prediction_tool_schema()["function"]["parameters"]["required"]
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError("prediction_fields_mismatch")
    opening = _positive_number(value["predicted_open"])
    high = _positive_number(value["predicted_high"])
    low = _positive_number(value["predicted_low"])
    closing = _positive_number(value["predicted_close"])
    if low > min(opening, closing) or high < max(opening, closing) or low > high:
        raise ValueError("invalid_ohlc_relationship")
    if value["confidence_level"] not in ("low", "medium", "high"):
        raise ValueError("invalid_confidence")
    for field in TEXT_FIELDS:
        if not isinstance(value[field], str) or not value[field].strip() or len(value[field]) > 8000:
            raise ValueError(f"invalid_{field}")
    for field in LIST_FIELDS:
        if (not isinstance(value[field], list) or len(value[field]) > 20 or
                any(not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in value[field])):
            raise ValueError(f"invalid_{field}")
    baseline = _positive_number(reference_close) if reference_close is not None else opening
    expected = 100 * (closing / baseline - 1)
    direction = "up" if expected >= 0 else "down"
    candle = "strong_down" if expected <= -1 else "down" if expected < 0 else "up" if expected < 1 else "strong_up"
    return {**value, "open": opening, "high": high, "low": low, "close": closing,
            "direction": direction, "candle_class": candle,
            "expected_pct_change": expected, "rationale": value["analysis"],
            "market_analysis": "；".join(value["signal_relationships"])}


def save_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"result_exists:{path}")
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite_number_required")
    return float(value)


def _positive_number(value: Any) -> float:
    number = _number(value)
    if number <= 0:
        raise ValueError("positive_number_required")
    return number

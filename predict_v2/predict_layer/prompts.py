"""Prompt construction for next-session OHLC forecasts."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """You are a short-term OHLC forecasting analyst for a stock, index, or ETF.
Use only the point-in-time data and news supplied in the user message. Do not use memory,
future events, external tools, or hidden calculations. The feature report is relative,
but target.reference_close supplies the latest known absolute price scale.
You must call submit_prediction exactly once. Its predicted_open, predicted_high,
predicted_low, and predicted_close must be positive absolute prices for the next session,
with low <= open/close <= high. Explain uncertainty and evidence in the other fields.
This is an offline evaluation, not investment advice."""


def build_prompt(context: dict[str, Any], profile: dict[str, str]) -> str:
    instructions = f"""Forecast task: predict the next trading session's absolute OHLC candle.
Use target.reference_close as the latest known close and keep all four predicted prices
on the same scale. The candle must satisfy low <= min(open, close) and
high >= max(open, close).

Analysis order:
1. Check data_quality, feature coverage, and news_context.status.
2. Explain trend, mean reversion, volatility, volume/price signals, and news evidence.
3. State supporting evidence, negative evidence, uncertainties, counter-view, and risks.
4. Call submit_prediction with predicted_open, predicted_high, predicted_low,
   predicted_close, confidence_level, and the required explanation fields.

Prompt profile: {profile['name']}
Profile requirements: {profile['instruction']}

"""
    return instructions + json.dumps(context, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

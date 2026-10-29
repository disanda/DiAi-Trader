"""Return-based features. Absolute prices never leave this module."""

from __future__ import annotations

import math
import statistics
from typing import Any


def _mean(values: list[float]) -> float:
    return statistics.mean(values)


def _std(values: list[float]) -> float:
    return statistics.pstdev(values)


def _max_drawdown(returns: list[float]) -> float:
    wealth = peak = 1.0
    worst = 0.0
    for value in returns:
        wealth *= 1 + value
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1)
    return 100 * worst


def compute_return_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [row["close"] for row in rows]
    volumes = [row["vol"] for row in rows]
    returns = [current / previous - 1 for previous, current in zip(closes, closes[1:])]
    output: dict[str, Any] = {
        "schema_version": "return-features-2.0",
        "units": "All return, volatility, range and deviation fields are percentage points.",
        "history_sessions": len(rows),
    }
    for window in (1, 3, 5, 10, 20, 60):
        output[f"return_{window}d_pct"] = 100 * (closes[-1] / closes[-window - 1] - 1) if len(closes) > window else None
    for window in (5, 10, 20, 60):
        sample = returns[-window:]
        output[f"mean_return_{window}d_pct"] = 100 * _mean(sample) if len(sample) == window else None
        output[f"volatility_{window}d_pct"] = 100 * _std(sample) if len(sample) == window else None
        output[f"downside_volatility_{window}d_pct"] = 100 * math.sqrt(_mean([min(value, 0) ** 2 for value in sample])) if len(sample) == window else None
        output[f"max_drawdown_{window}d_pct"] = _max_drawdown(sample) if len(sample) == window else None
        average = _mean(closes[-window:]) if len(closes) >= window else None
        output[f"close_vs_mean_{window}d_pct"] = 100 * (closes[-1] / average - 1) if average else None
    latest, previous = rows[-1], rows[-2]
    output.update({
        "gap_return_pct": 100 * (latest["open"] / previous["close"] - 1),
        "intraday_return_pct": 100 * (latest["close"] / latest["open"] - 1),
        "high_excursion_pct": 100 * (latest["high"] / previous["close"] - 1),
        "low_excursion_pct": 100 * (latest["low"] / previous["close"] - 1),
        "range_pct": 100 * (latest["high"] - latest["low"]) / previous["close"],
        "volume_change_pct": 100 * (volumes[-1] / volumes[-2] - 1) if volumes[-2] else None,
        "volume_relative_20": volumes[-1] / _mean(volumes[-21:-1]) if len(volumes) >= 21 and _mean(volumes[-21:-1]) else None,
    })
    changes = [current - previous for previous, current in zip(closes[-15:-1], closes[-14:])]
    gains = sum(max(value, 0) for value in changes)
    losses = sum(max(-value, 0) for value in changes)
    output["rsi_14_simple"] = 100 * gains / (gains + losses) if gains + losses else 50.0
    output["positive_session_ratio_20"] = sum(value > 0 for value in returns[-20:]) / 20
    output["return_skew_20"] = _skew(returns[-20:])
    output["return_autocorrelation_20"] = _correlation(returns[-20:-1], returns[-19:])
    output["price_volume_correlation_20"] = _price_volume_correlation(returns[-20:], volumes[-21:])
    output["consecutive_up"] = _streak(returns, 1)
    output["consecutive_down"] = _streak(returns, -1)
    return output


def compact_return_bars(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    selected = rows[-(count + 1):]
    compact = []
    for previous, current in zip(selected, selected[1:]):
        compact.append({
            "trade_date": current["trade_date"],
            "close_return_pct": 100 * (current["close"] / previous["close"] - 1),
            "gap_return_pct": 100 * (current["open"] / previous["close"] - 1),
            "intraday_return_pct": 100 * (current["close"] / current["open"] - 1),
            "high_excursion_pct": 100 * (current["high"] / previous["close"] - 1),
            "low_excursion_pct": 100 * (current["low"] / previous["close"] - 1),
            "volume_change_pct": 100 * (current["vol"] / previous["vol"] - 1) if previous["vol"] else None,
        })
    return compact[-count:]


def _streak(values: list[float], sign: int) -> int:
    count = 0
    for value in reversed(values):
        if value * sign <= 0:
            break
        count += 1
    return count


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right))
    return numerator / denominator if denominator else None


def _price_volume_correlation(returns: list[float], volumes: list[float]) -> float | None:
    if len(returns) != 20 or len(volumes) != 21 or any(value == 0 for value in volumes[:-1]):
        return None
    volume_changes = [current / previous - 1 for previous, current in zip(volumes, volumes[1:])]
    return _correlation(returns, volume_changes)


def _skew(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    mean, std = _mean(values), _std(values)
    return _mean([((value - mean) / std) ** 3 for value in values]) if std else 0.0

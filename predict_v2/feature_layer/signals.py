"""Transparent rule-based signal extraction from deterministic features."""

from __future__ import annotations

from typing import Any


def derive_signals(features: dict[str, Any]) -> list[dict[str, Any]]:
    signals = []

    def add(signal_id: str, family: str, direction: str, strength: float, evidence: dict[str, Any]):
        signals.append({"signal_id": signal_id, "family": family, "direction": direction,
                        "strength": round(max(0.0, min(1.0, strength)), 4), "evidence": evidence})

    return_20 = features.get("return_20d_pct")
    return_5 = features.get("return_5d_pct")
    if return_20 is not None:
        add("trend_20d", "trend", "positive" if return_20 > 0 else "negative" if return_20 < 0 else "neutral",
            min(abs(return_20) / 10, 1), {"return_20d_pct": return_20})
    if return_5 is not None and return_20 is not None:
        aligned = return_5 * return_20 > 0
        add("multi_horizon_alignment", "trend", "positive" if aligned and return_5 > 0 else "negative" if aligned else "conflict",
            min((abs(return_5) + abs(return_20)) / 15, 1), {"return_5d_pct": return_5, "return_20d_pct": return_20})
    vol = features.get("volatility_20d_pct")
    if vol is not None:
        add("volatility_regime", "risk", "negative" if vol >= 2.5 else "neutral", min(vol / 5, 1),
            {"volatility_20d_pct": vol})
    volume = features.get("volume_relative_20")
    latest_return = features.get("return_1d_pct")
    if volume is not None and latest_return is not None:
        direction = "positive" if volume >= 1.2 and latest_return > 0 else "negative" if volume >= 1.2 and latest_return < 0 else "neutral"
        add("volume_confirmation", "volume", direction, min(abs(volume - 1), 1),
            {"volume_relative_20": volume, "return_1d_pct": latest_return})
    rsi = features.get("rsi_14_simple")
    if rsi is not None:
        direction = "negative" if rsi >= 70 else "positive" if rsi <= 30 else "neutral"
        add("rsi_extreme", "mean_reversion", direction, min(abs(rsi - 50) / 50, 1), {"rsi_14_simple": rsi})
    drawdown = features.get("max_drawdown_20d_pct")
    if drawdown is not None and drawdown <= -8:
        add("drawdown_risk", "risk", "negative", min(abs(drawdown) / 20, 1), {"max_drawdown_20d_pct": drawdown})
    return signals

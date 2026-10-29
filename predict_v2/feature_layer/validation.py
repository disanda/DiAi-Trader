"""Strict point-in-time validation for daily OHLCV data."""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone
from typing import Any

MARKET_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
REQUIRED_NUMERIC = ("open", "high", "low", "close", "vol", "amount")


def date_key(value: Any) -> str:
    text = str(value)
    fmt = "%Y-%m-%d" if "-" in text else "%Y%m%d"
    parsed = datetime.strptime(text, fmt)
    if parsed.strftime(fmt) != text:
        raise ValueError("invalid_date_format")
    return parsed.strftime("%Y%m%d")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("iso_timestamp_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def default_cutoff(prediction_date: str) -> datetime:
    target = datetime.strptime(date_key(prediction_date), "%Y%m%d").date()
    return datetime.combine(target, time.min, MARKET_TZ).astimezone(timezone.utc)


def finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}_not_numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field}_not_finite")
    return result


def validate_history(
    records: list[dict[str, Any]],
    prediction_date: str,
    cutoff: datetime,
    history_days: int,
    symbol: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise ValueError("records_required")
    if type(history_days) is not int or not 60 <= history_days <= 250:
        raise ValueError("history_days_must_be_60_to_250")
    target = date_key(prediction_date)
    accepted: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    input_dates: list[str] = []
    excluded_target_or_future = 0
    for raw in records:
        try:
            day = date_key(raw["trade_date"])
        except (KeyError, TypeError, ValueError):
            errors.append("invalid_trade_date")
            continue
        input_dates.append(day)
        if day >= target:
            excluded_target_or_future += 1
            continue
        close_time = datetime.combine(datetime.strptime(day, "%Y%m%d").date(), time(15), MARKET_TZ)
        if close_time > cutoff:
            continue
        try:
            values = {field: finite_number(raw[field], field) for field in REQUIRED_NUMERIC}
            if any(values[field] <= 0 for field in ("open", "high", "low", "close")):
                raise ValueError("nonpositive_price")
            if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
                raise ValueError("invalid_ohlc_relationship")
            if values["vol"] < 0 or values["amount"] < 0:
                raise ValueError("negative_volume_or_amount")
            row_symbol = raw.get("ts_code", symbol)
            if row_symbol != symbol:
                raise ValueError("mixed_symbol")
            accepted.append({"trade_date": day, "ts_code": symbol, **values})
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{day}:{exc}")
    if input_dates != sorted(input_dates):
        warnings.append("input_was_resorted")
    accepted.sort(key=lambda row: row["trade_date"])
    accepted_dates = [row["trade_date"] for row in accepted]
    if len(accepted_dates) != len(set(accepted_dates)):
        errors.append("duplicate_trade_date")
    if len(accepted) < history_days:
        errors.append(f"insufficient_history:{len(accepted)}<{history_days}")
    selected = accepted[-history_days:]
    quality = {
        "status": "error" if errors else "warning" if warnings else "ok",
        "errors": sorted(set(errors)),
        "warnings": warnings,
        "input_count": len(records),
        "selected_count": len(selected),
        "excluded_target_or_future": excluded_target_or_future,
        "coverage_start": selected[0]["trade_date"] if selected else None,
        "coverage_end": selected[-1]["trade_date"] if selected else None,
        "missing_sessions_checked": False,
        "note": "Exchange calendar not supplied; internal gaps cannot be proven absent.",
    }
    return selected, quality

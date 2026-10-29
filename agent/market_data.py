"""Read the canonical per-symbol market data used by trading and prediction."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKET_ROOTS = {
    "cn": (PROJECT_ROOT / "data" / "Astocks", PROJECT_ROOT / "data" / "ETFs"),
    "us": (PROJECT_ROOT / "data" / "USstocks",),
}


def roots_for_market(market: str = "cn") -> tuple[Path, ...]:
    key = str(market or "cn").lower()
    return MARKET_ROOTS["us"] if key in {"us", "usstocks"} else MARKET_ROOTS["cn"]


def find_symbol_file(symbol: str, market: str = "cn") -> Path | None:
    code = str(symbol).strip().upper()
    for root in roots_for_market(market):
        for source in ("stocks", "indices"):
            candidate = root / source / f"{code}.json"
            if candidate.is_file():
                return candidate
    # Agents may trade a mixed universe even when their market config is stale.
    for roots in MARKET_ROOTS.values():
        for root in roots:
            for source in ("stocks", "indices"):
                candidate = root / source / f"{code}.json"
                if candidate.is_file():
                    return candidate
    return None


def load_symbol(symbol: str, market: str = "cn") -> dict | None:
    path = find_symbol_file(symbol, market)
    if not path:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def normalize_date(value: object) -> str:
    return str(value or "").strip().replace("-", "")[:8]


def get_record(symbol: str, date: str, market: str = "cn") -> dict | None:
    payload = load_symbol(symbol, market)
    wanted = normalize_date(date)
    if not payload or not wanted:
        return None
    for record in payload.get("records") or []:
        if normalize_date(record.get("trade_date") or record.get("date")) == wanted:
            return record
    return None


def available_dates(market: str = "cn") -> list[str]:
    dates: set[str] = set()
    for root in roots_for_market(market):
        index = root / "dates.json"
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
            dates.update(normalize_date(value) for value in payload.get("dates", []) if normalize_date(value))
            continue
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        for _, payload in iter_symbols(market, roots=(root,)):
            dates.update(normalize_date(row.get("trade_date") or row.get("date")) for row in payload.get("records") or [])
    return [f"{value[:4]}-{value[4:6]}-{value[6:8]}" for value in sorted(dates) if len(value) == 8]


def iter_symbols(market: str = "cn", roots: tuple[Path, ...] | None = None) -> Iterator[tuple[str, dict]]:
    seen: set[str] = set()
    for root in roots or roots_for_market(market):
        for source in ("stocks", "indices"):
            for path in sorted((root / source).glob("*.json")):
                if path.stem in seen:
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    seen.add(path.stem)
                    yield path.stem, payload


def name_mapping(market: str = "cn") -> dict[str, str]:
    result: dict[str, str] = {}
    for symbol, payload in iter_symbols(market):
        records = payload.get("records") or []
        name = payload.get("name") or (records[-1].get("name") if records else None)
        if name:
            result[symbol] = str(name)
    return result

#!/usr/bin/env python3
"""Unified incremental downloader for U.S. equities and indexes.

Each symbol is tried against the configured providers in order. A missing
optional dependency, unavailable endpoint, unsupported symbol, or empty
response only skips that provider; the next provider is attempted.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent


def load_dotenv_token() -> str | None:
    """Load TUSHARE_TOKEN from the project .env without printing its value."""
    if os.getenv("TUSHARE_TOKEN"):
        return os.getenv("TUSHARE_TOKEN")
    for path in (PROJECT_ROOT / ".env", ROOT / ".env", Path.cwd() / ".env"):
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "TUSHARE_TOKEN":
                    value = value.strip().strip("'\"")
                    if value:
                        return value
        except OSError:
            continue
    return None


TUSHARE_TOKEN = load_dotenv_token()
DEFAULT_ROOT = Path(os.getenv("US_STOCKS_DATA_DIR", ROOT / "USstocks"))
DEFAULT_PROVIDERS = ("tencent", "sina", "eastmoney", "akshare", "yfinance", "tushare")

# Canonical local code -> provider-specific code. These are indexes, not ETFs.
INDEXES = {
    "DJI": {"name": "Dow Jones Industrial Average", "tencent": "DJI", "sina": "dji", "eastmoney": "DJIA", "yfinance": "^DJI", "tushare": "DJI"},
    "SPX": {"name": "S&P 500", "tencent": "INX", "sina": "inx", "eastmoney": "SPX", "yfinance": "^GSPC", "tushare": "SPX"},
    "NDX": {"name": "Nasdaq 100", "tencent": "NDX", "sina": "ndx", "eastmoney": "NDX", "yfinance": "^NDX", "tushare": "NDX"},
    "IXIC": {"name": "Nasdaq Composite", "tencent": "IXIC", "sina": "ixic", "eastmoney": "IXIC", "yfinance": "^IXIC", "tushare": "IXIC"},
    "HXC": {"name": "Nasdaq Golden Dragon China Index", "tencent": "HXC", "sina": "hxc", "eastmoney": "HXC", "yfinance": "^HXC", "tushare": "HXC"},
}
INDEX_ALIASES = {"DJIA": "DJI", "DOW": "DJI", "INX": "SPX", "GSPC": "SPX", "NASDAQ": "IXIC"}


class ProviderUnavailable(RuntimeError):
    """A provider cannot serve this request; fallback should continue."""


def normalize_date(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    return str(value).replace("-", "").replace("/", "")[:8]


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if symbol.startswith("US") and len(symbol) > 2:
        symbol = symbol[2:]
    return INDEX_ALIASES.get(symbol, symbol)


def number(value: Any) -> float | None:
    try:
        result = float(value) if value not in (None, "", "-") else None
        return result if result is None or math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if hasattr(value, "item"):
            return json_clean(value.item())
    except (TypeError, ValueError):
        pass
    return value


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(json_clean(payload), handle, ensure_ascii=False, indent=indent,
                  separators=None if indent else (",", ":"), allow_nan=False)


def load_symbol_file(path: Path) -> list[str]:
    payload = read_json(path, None)
    values = payload if isinstance(payload, list) else payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise ValueError(f"{path} must be a JSON array or contain a symbols array")
    return [normalize_symbol(value) for value in values if normalize_symbol(value)]


def request_json(url: str, encoding: str = "utf-8") -> Any:
    request = Request(url, headers={"Accept": "application/json,text/plain,*/*",
                                    "User-Agent": "Mozilla/5.0 DiAi-Trader/1.0",
                                    "Referer": "https://finance.sina.com.cn/"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode(encoding, errors="replace"))


def provider_code(asset_type: str, symbol: str, provider: str) -> str:
    if asset_type == "index":
        return str(INDEXES[symbol].get(provider, symbol))
    return symbol


def fetch_tencent(asset_type: str, symbol: str, start: str, end: str, count: int, _: str | None) -> list[dict]:
    code = f"us{provider_code(asset_type, symbol, 'tencent')}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,,,{count}"
    payload = request_json(url)
    rows = ((payload.get("data") or {}).get(code) or {}).get("day") or []
    result = []
    for row in rows:
        if len(row) >= 6 and start <= normalize_date(row[0]) <= end:
            result.append({"trade_date": normalize_date(row[0]), "open": number(row[1]),
                           "close": number(row[2]), "high": number(row[3]),
                           "low": number(row[4]), "vol": number(row[5])})
    return result


def fetch_sina(asset_type: str, symbol: str, start: str, end: str, count: int, _: str | None) -> list[dict]:
    # stock-api's Sina transformer uses the ``us`` market prefix for U.S.
    # symbols (for example ``usaapl`` and ``usdji``).
    code = "us" + provider_code(asset_type, symbol, "sina").lower()
    url = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData?"
           f"symbol={quote(code)}&scale=240&ma=no&datalen={count}")
    rows = request_json(url, "gb18030")
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        date = normalize_date(row.get("day"))
        if start <= date <= end:
            result.append({"trade_date": date, "open": number(row.get("open")),
                           "close": number(row.get("close")), "high": number(row.get("high")),
                           "low": number(row.get("low")), "vol": number(row.get("volume"))})
    return result


def fetch_eastmoney(asset_type: str, symbol: str, start: str, end: str, count: int, _: str | None) -> list[dict]:
    market = "100" if asset_type == "index" else "105"
    code = provider_code(asset_type, symbol, "eastmoney")
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?"
           f"secid={market}.{quote(code)}&klt=101&fqt=0&beg={start}&end={end}"
           "&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61")
    payload = request_json(url)
    rows = ((payload.get("data") or {}).get("klines") or [])[-count:]
    result = []
    for raw in rows:
        fields = str(raw).split(",")
        if len(fields) >= 7 and start <= normalize_date(fields[0]) <= end:
            result.append({"trade_date": normalize_date(fields[0]), "open": number(fields[1]),
                           "close": number(fields[2]), "high": number(fields[3]),
                           "low": number(fields[4]), "vol": number(fields[5]),
                           "amount": number(fields[6])})
    return result


def fetch_akshare(asset_type: str, symbol: str, start: str, end: str, _count: int, _token: str | None) -> list[dict]:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ProviderUnavailable("akshare is not installed") from exc
    market = "100" if asset_type == "index" else "105"
    code = provider_code(asset_type, symbol, "eastmoney")
    frame = ak.stock_us_hist(symbol=f"{market}.{code}", period="daily",
                             start_date=start, end_date=end, adjust="")
    if frame is None or frame.empty:
        return []
    aliases = {"日期": "trade_date", "开盘": "open", "收盘": "close", "最高": "high",
               "最低": "low", "成交量": "vol", "成交额": "amount"}
    frame = frame.rename(columns=aliases)
    return _frame_records(frame)


def fetch_yfinance(asset_type: str, symbol: str, start: str, end: str, _count: int, _token: str | None) -> list[dict]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ProviderUnavailable("yfinance is not installed") from exc
    code = provider_code(asset_type, symbol, "yfinance") if asset_type == "index" else symbol.replace(".", "-")
    exclusive_end = (datetime.strptime(end, "%Y%m%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    frame = yf.Ticker(code).history(start=datetime.strptime(start, "%Y%m%d").strftime("%Y-%m-%d"),
                                    end=exclusive_end, interval="1d", auto_adjust=False,
                                    actions=False, repair=True)
    if frame is None or frame.empty:
        return []
    frame = frame.reset_index().rename(columns={"Date": "trade_date", "Open": "open", "Close": "close",
                                                 "High": "high", "Low": "low", "Volume": "vol",
                                                 "Adj Close": "adj_close"})
    return _frame_records(frame)


def fetch_tushare(asset_type: str, symbol: str, start: str, end: str, _count: int, token: str | None) -> list[dict]:
    if not token:
        raise ProviderUnavailable("TUSHARE_TOKEN is not configured")
    try:
        import tushare as ts
    except ImportError as exc:
        raise ProviderUnavailable("tushare is not installed") from exc
    pro = ts.pro_api(token)
    if asset_type == "index":
        frame = pro.index_global(ts_code=provider_code(asset_type, symbol, "tushare"),
                                 start_date=start, end_date=end)
    else:
        frame = pro.us_daily(ts_code=symbol, start_date=start, end_date=end)
    if frame is None or frame.empty:
        return []
    return _frame_records(frame)


def _frame_records(frame: Any) -> list[dict]:
    required = {"trade_date", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ProviderUnavailable(f"missing columns: {', '.join(sorted(required - set(frame.columns)))}")
    frame["trade_date"] = frame["trade_date"].map(normalize_date)
    columns = [column for column in ("trade_date", "open", "high", "low", "close", "vol", "amount", "adj_close", "vwap") if column in frame]
    return frame[columns].sort_values("trade_date").to_dict("records")


PROVIDER_LOADERS: dict[str, Callable[..., list[dict]]] = {
    "tencent": fetch_tencent, "sina": fetch_sina, "eastmoney": fetch_eastmoney,
    "akshare": fetch_akshare, "yfinance": fetch_yfinance, "tushare": fetch_tushare,
}


def fetch_with_fallback(asset_type: str, symbol: str, start: str, end: str,
                        providers: list[str], retries: int, count: int,
                        token: str | None) -> tuple[list[dict], str, list[str]]:
    errors = []
    for provider in providers:
        loader = PROVIDER_LOADERS[provider]
        for attempt in range(1, retries + 1):
            try:
                rows = loader(asset_type, symbol, start, end, count, token)
                rows = [row for row in rows if start <= normalize_date(row.get("trade_date")) <= end]
                if not rows:
                    raise ProviderUnavailable("empty response")
                for row in rows:
                    row["source"] = provider
                return rows, provider, errors
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                if attempt < retries:
                    time.sleep(attempt)
        print(f"{symbol}: {provider} unavailable, trying next provider")
    raise ProviderUnavailable("; ".join(errors))


def enrich_records(records: list[dict]) -> list[dict]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required to build market files") from exc
    frame = pd.DataFrame(records).sort_values("trade_date").drop_duplicates("trade_date", keep="last")
    for column in ("open", "high", "low", "close", "vol", "amount"):
        if column not in frame:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["amount"] = frame["amount"].fillna(frame["close"] * frame["vol"])
    frame["pre_close"] = frame["close"].shift(1)
    frame["change"] = frame["close"] - frame["pre_close"]
    frame["pct_change"] = frame["change"] / frame["pre_close"] * 100
    frame["pct_chg"] = frame["pct_change"]
    returns = frame["close"].pct_change(fill_method=None)
    for window in (5, 10, 20):
        frame[f"mom_{window}"] = frame["close"].pct_change(window, fill_method=None)
        frame[f"ma{window}"] = frame["close"].rolling(window).mean()
    frame["volatility_10"] = returns.rolling(10).std()
    frame["volatility_20"] = returns.rolling(20).std()
    frame["ma20_dev"] = (frame["close"] - frame["ma20"]) / frame["ma20"]
    frame["vol_ratio"] = frame["vol"].rolling(5).mean() / frame["vol"].rolling(20).mean()
    frame["amount_ma5"] = frame["amount"].rolling(5).mean()
    if "vwap" not in frame:
        frame["vwap"] = None
    return frame.where(frame.notna(), None).to_dict("records")


def update_symbol(asset_type: str, symbol: str, name: str, output_root: Path,
                  start: str, end: str, providers: list[str], retries: int,
                  count: int, token: str | None) -> dict | None:
    directory = output_root / ("stocks" if asset_type == "stock" else "indices")
    path = directory / f"{symbol}.json"
    old = read_json(path, {})
    existing = old.get("records") or [] if isinstance(old, dict) else []
    latest = max((normalize_date(row.get("trade_date")) for row in existing), default="")
    fetch_start = ((datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                   if latest else start)
    source = old.get("source") if isinstance(old, dict) else None
    errors: list[str] = []
    incoming: list[dict] = []
    if fetch_start <= end:
        try:
            incoming, source, errors = fetch_with_fallback(asset_type, symbol, fetch_start, end,
                                                           providers, retries, count, token)
        except ProviderUnavailable as exc:
            print(f"{symbol}: all providers failed: {exc}")
            if not existing:
                return None
    records = enrich_records(existing + incoming)
    if not records:
        return None
    result = {"ts_code": symbol, "name": old.get("name") or name, "asset_type": asset_type.upper(),
              "source": source or "local", "start_date": records[0]["trade_date"],
              "end_date": records[-1]["trade_date"], "records": records}
    if errors:
        result["provider_fallbacks"] = errors
    write_json(path, result)
    print(f"{symbol}: {len(records)} rows ({result['source']})")
    return result


def rebuild_layout(output_root: Path, *, write_daily: bool = False) -> None:
    stocks = [read_json(path, {}) for path in sorted((output_root / "stocks").glob("*.json"))]
    stocks = [stock for stock in stocks if stock.get("records")]
    by_date: dict[str, list[dict]] = {}
    for stock in stocks:
        for row in stock["records"]:
            date = normalize_date(row.get("trade_date"))
            if date:
                by_date.setdefault(date, []).append({**row, "ts_code": stock["ts_code"], "name": stock["name"]})
    daily_dir = output_root / "daily"
    if write_daily:
        daily_dir.mkdir(parents=True, exist_ok=True)
    for date, rows in by_date.items() if write_daily else []:
        write_json(daily_dir / f"{date}.json", {"date": date, "asset_count": len(rows), "data": rows})
    dates = sorted(by_date)
    latest = by_date.get(dates[-1], []) if dates else []
    indexes = [read_json(path, {}) for path in sorted((output_root / "indices").glob("*.json"))]
    indexes = [item for item in indexes if item.get("records")]
    write_json(output_root / "latest.json", {"date": dates[-1] if dates else None,
                                               "asset_count": len(latest), "data": latest})
    write_json(output_root / "dates.json", {"dates": dates, "updated_at": datetime.now().isoformat(timespec="seconds")})
    write_json(output_root / "meta.json", {"asset_type": "US_MARKET", "stock_count": len(stocks),
                                             "index_count": len(indexes),
                                             "symbols": [item["ts_code"] for item in stocks],
                                             "indices": [item["ts_code"] for item in indexes],
                                             "name_map": {item["ts_code"]: item["name"] for item in stocks + indexes},
                                             "updated_at": datetime.now().isoformat(timespec="seconds")}, indent=2)
    write_json(output_root / "symbols" / "us_stock.json",
               {"symbolname": "U.S. stocks", "symbols": [item["ts_code"] for item in stocks]}, indent=2)
    write_json(output_root / "symbols" / "us_index.json",
               {"symbolname": "U.S. indexes", "symbols": [item["ts_code"] for item in indexes]}, indent=2)


def discover_stocks(providers: list[str], token: str | None) -> list[str]:
    if "akshare" in providers:
        try:
            import akshare as ak
            frame = ak.stock_us_spot_em()
            if frame is not None and not frame.empty and "代码" in frame:
                return sorted({str(value).split(".", 1)[-1].upper() for value in frame["代码"]})
        except Exception as exc:
            print(f"stock discovery via akshare failed: {exc}")
    if "tushare" in providers and token:
        try:
            import tushare as ts
            frame = ts.pro_api(token).us_basic(limit=6000)
            if frame is not None and not frame.empty:
                return sorted(set(frame["ts_code"].astype(str).str.upper()))
        except Exception as exc:
            print(f"stock discovery via tushare failed: {exc}")
    raise SystemExit("Unable to discover U.S. stocks; provide --stocks or a symbol file")


def fetch_stock_names(providers: list[str], token: str | None, symbols: list[str]) -> dict[str, str]:
    """Fetch and persistable display names for U.S. stocks when the provider exposes them."""
    wanted = {normalize_symbol(value) for value in symbols}
    if "tushare" in providers and token and wanted:
        try:
            import tushare as ts
            frame = ts.pro_api(token).us_basic(limit=6000)
            if frame is not None and not frame.empty and "ts_code" in frame.columns:
                result = {}
                for _, row in frame.iterrows():
                    code = normalize_symbol(row.get("ts_code"))
                    name = str(row.get("name") or row.get("英文全称") or "").strip()
                    if code in wanted and name:
                        result[code] = name
                return result
        except Exception as exc:
            print(f"stock name lookup via tushare failed: {exc}")
    return {}


def parse_providers(value: str) -> list[str]:
    providers = [item.strip().lower() for item in value.split(",") if item.strip()]
    unsupported = sorted(set(providers) - set(PROVIDER_LOADERS))
    if unsupported:
        raise ValueError(f"unsupported providers: {', '.join(unsupported)}")
    if not providers:
        raise ValueError("at least one provider is required")
    return providers


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified U.S. stock and index downloader with provider fallback")
    parser.add_argument("--symbols", nargs="*", help="Mixed stock/index symbols; known indexes are auto-detected")
    parser.add_argument("--symbols-file", help="Mixed JSON symbol file; known indexes are auto-detected")
    parser.add_argument("--stocks", nargs="*", default=[])
    parser.add_argument("--stock-symbols-file")
    parser.add_argument("--indices", nargs="*", default=[])
    parser.add_argument("--index-symbols-file")
    parser.add_argument("--discover-stocks", action="store_true", help="Discover all stocks via AkShare, then Tushare")
    parser.add_argument("--start", default="20250101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--output", default=str(DEFAULT_ROOT))
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS),
                        help="Comma-separated fallback order")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--token", default=TUSHARE_TOKEN)
    parser.add_argument("--write-daily", action="store_true", help="Also generate legacy daily/ partitions (disabled by default)")
    args = parser.parse_args()
    try:
        providers = parse_providers(args.providers)
    except ValueError as exc:
        parser.error(str(exc))
    output_root = Path(args.output)
    mixed = list(args.symbols or [])
    if args.symbols_file:
        mixed.extend(load_symbol_file(Path(args.symbols_file)))
    stocks = [normalize_symbol(item) for item in args.stocks]
    indices = [normalize_symbol(item) for item in args.indices]
    if args.stock_symbols_file:
        stocks.extend(load_symbol_file(Path(args.stock_symbols_file)))
    if args.index_symbols_file:
        indices.extend(load_symbol_file(Path(args.index_symbols_file)))
    for symbol in map(normalize_symbol, mixed):
        (indices if symbol in INDEXES else stocks).append(symbol)
    if not mixed and not stocks and not indices and not args.discover_stocks:
        stock_file = output_root / "symbols" / "us_stock.json"
        index_file = output_root / "symbols" / "us_index.json"
        if stock_file.exists():
            for symbol in load_symbol_file(stock_file):
                (indices if symbol in INDEXES else stocks).append(symbol)
        if index_file.exists():
            indices.extend(load_symbol_file(index_file))
    if args.discover_stocks:
        stocks.extend(discover_stocks(providers, args.token))
    stocks = sorted({symbol for symbol in stocks if symbol and symbol not in INDEXES})
    indices = sorted({normalize_symbol(symbol) for symbol in indices if normalize_symbol(symbol) in INDEXES})
    if args.limit:
        stocks = stocks[:args.limit]
    if not stocks and not indices:
        raise SystemExit("No symbols selected. Use --symbols, --stocks, --indices, symbol files, or --discover-stocks")
    start, end = normalize_date(args.start), normalize_date(args.end)
    if len(start) != 8 or len(end) != 8 or start > end:
        raise SystemExit("Invalid date range; expected YYYYMMDD and start <= end")
    print(f"Providers: {' -> '.join(providers)}")
    print(f"Selected: {len(stocks)} stocks, {len(indices)} indexes")
    stock_names = fetch_stock_names(providers, args.token, stocks)
    update_started = time.monotonic()
    total_symbols = len(stocks) + len(indices)
    completed = 0
    print(f"Incremental update range: {start} -> {end}; {total_symbols} symbols; per-symbol progress includes rows/s and ETA")
    for symbol in stocks:
        symbol_started = time.monotonic()
        update_symbol("stock", symbol, stock_names.get(symbol, symbol), output_root, start, end, providers,
                      max(1, args.retries), max(1, args.count), args.token)
        completed += 1
        elapsed = time.monotonic() - symbol_started
        total_elapsed = time.monotonic() - update_started
        rate = completed / max(total_elapsed, 0.001)
        eta = (total_symbols - completed) / rate if rate else 0
        print(f"Progress {completed}/{total_symbols} ({completed / max(total_symbols, 1):.0%}); {symbol} took {elapsed:.1f}s; total {total_elapsed:.1f}s; ETA {eta:.0f}s")
    for symbol in indices:
        symbol_started = time.monotonic()
        update_symbol("index", symbol, INDEXES[symbol]["name"], output_root, start, end,
                      providers, max(1, args.retries), max(1, args.count), args.token)
        completed += 1
        elapsed = time.monotonic() - symbol_started
        total_elapsed = time.monotonic() - update_started
        rate = completed / max(total_elapsed, 0.001)
        eta = (total_symbols - completed) / rate if rate else 0
        print(f"Progress {completed}/{total_symbols} ({completed / max(total_symbols, 1):.0%}); {symbol} took {elapsed:.1f}s; total {total_elapsed:.1f}s; ETA {eta:.0f}s")
    rebuild_started = time.monotonic()
    rebuild_layout(output_root, write_daily=args.write_daily)
    print(f"Layout rebuild completed in {time.monotonic() - rebuild_started:.1f}s; total update {time.monotonic() - update_started:.1f}s")


if __name__ == "__main__":
    main()

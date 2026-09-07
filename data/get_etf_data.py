#!/usr/bin/env python3
"""Download listed exchange-traded funds from Tushare.

Storage mirrors the A-share layout but is kept under data/ETFs so ETF records
are not mixed with ordinary stocks:
  ETFs/stocks/<ts_code>.json, ETFs/daily/<date>.json, ETFs/latest.json,
  ETFs/dates.json and ETFs/meta.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "ETFs"
STOCKS_DIR, DAILY_DIR = DATA_DIR / "stocks", DATA_DIR / "daily"
START_DEFAULT = "20250101"
FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
ETF_SHARE_FIELDS = "ts_code,trade_date,fd_share"


def norm(value):
    return str(value or "").replace("-", "")


def json_clean(value):
    """Convert pandas/numpy NaN and infinities to JSON null."""
    if isinstance(value, dict):
        return {key: json_clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_clean(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if hasattr(value, "item"):
            scalar = value.item()
            if isinstance(scalar, float) and not math.isfinite(scalar):
                return None
            return scalar
    except (TypeError, ValueError):
        pass
    return value


def read_records(path):
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle).get("records") or []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def enrich_records(records):
    """Add the same technical columns used by A-share stock files."""
    if not records:
        return records
    frame = pd.DataFrame(records).sort_values("trade_date")
    close = pd.to_numeric(frame["close"], errors="coerce")
    ret = close.pct_change()
    frame["mom_5"], frame["mom_10"], frame["mom_20"] = close.pct_change(5), close.pct_change(10), close.pct_change(20)
    frame["volatility_10"], frame["volatility_20"] = ret.rolling(10).std(), ret.rolling(20).std()
    frame["ma5"], frame["ma10"], frame["ma20"] = close.rolling(5).mean(), close.rolling(10).mean(), close.rolling(20).mean()
    frame["ma20_dev"] = (close - frame["ma20"]) / frame["ma20"]
    vol = pd.to_numeric(frame.get("vol"), errors="coerce")
    frame["vol_ratio"] = vol.rolling(5).mean() / vol.rolling(20).mean()
    frame["amount_ma5"] = pd.to_numeric(frame.get("amount"), errors="coerce").rolling(5).mean()
    for field in ("pe", "pe_ttm", "pb", "ps_ttm", "turnover_rate", "turnover_rate_f", "total_mv", "circ_mv", "free_share"):
        if field not in frame:
            frame[field] = None
    frame = frame.where(pd.notna(frame), None)
    return frame.to_dict("records")


def fetch_etf_share(pro, code, start, end):
    """Fetch ETF fund shares using Tushare's valid fund_share endpoint."""
    try:
        frame = pro.fund_share(ts_code=code, start_date=start, end_date=end, fields=ETF_SHARE_FIELDS)
    except Exception:
        return {}
    if frame is None or frame.empty:
        return {}
    return {
        norm(row.get("trade_date")): row
        for row in frame.to_dict("records")
        if norm(row.get("trade_date"))
    }


def main():
    parser = argparse.ArgumentParser(description="增量更新场内 ETF 数据")
    parser.add_argument("--start", default=START_DEFAULT)
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    parser.add_argument("--limit", type=int, default=0, help="仅调试时限制基金数量，0 表示全部")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("TUSHARE_TOKEN is required")
    end = norm(args.end)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STOCKS_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    pro = ts.pro_api(args.token)
    funds = pro.fund_basic(market="E", status="L", fields="ts_code,name")
    if funds is None or funds.empty:
        raise RuntimeError("Tushare fund_basic returned no listed ETFs")
    funds = funds.drop_duplicates("ts_code").sort_values("ts_code")
    if args.limit:
        funds = funds.head(args.limit)
    rows_by_date, symbols = {}, []
    for _, fund in funds.iterrows():
        code, name = str(fund.ts_code), str(fund.get("name") or "")
        path = STOCKS_DIR / f"{code}.json"
        old = read_records(path)
        last = max((norm(row.get("trade_date")) for row in old), default="")
        start = (datetime.strptime(last, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d") if last else norm(args.start)
        basic_start = last or norm(args.start)
        share_by_date = fetch_etf_share(pro, code, basic_start, end) if basic_start <= end else {}
        incoming = []
        if start <= end:
            frame = pro.fund_daily(ts_code=code, start_date=start, end_date=end, fields=FIELDS)
            if frame is not None and not frame.empty:
                incoming = frame.sort_values("trade_date").to_dict("records")
        for row in incoming:
            share = share_by_date.get(norm(row.get("trade_date")), {}).get("fd_share")
            if share is not None:
                row["free_share"] = share
                row["total_mv"] = float(row.get("close") or 0) * float(share)
                row["circ_mv"] = row["total_mv"]
                row["turnover_rate"] = (float(row.get("vol") or 0) * 100 / float(share)) if float(share) else None
                row["turnover_rate_f"] = row["turnover_rate"]
        by_date = {norm(row.get("trade_date")): row for row in old}
        by_date.update({norm(row.get("trade_date")): row for row in incoming})
        for key, row in by_date.items():
            share = share_by_date.get(key, {}).get("fd_share")
            if share is not None:
                row["free_share"] = share
                row["total_mv"] = float(row.get("close") or 0) * float(share)
                row["circ_mv"] = row["total_mv"]
                row["turnover_rate"] = (float(row.get("vol") or 0) * 100 / float(share)) if float(share) else None
                row["turnover_rate_f"] = row["turnover_rate"]
        records = enrich_records([by_date[key] for key in sorted(by_date) if key])
        if not records:
            continue
        payload = {"ts_code": code, "name": name, "start_date": records[0]["trade_date"], "end_date": records[-1]["trade_date"], "records": records}
        with path.open("w", encoding="utf-8") as handle:
            json.dump(json_clean(payload), handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        symbols.append(code)
        for row in records:
            row = {**row, "name": name}
            rows_by_date.setdefault(norm(row.get("trade_date")), []).append(row)
    dates = sorted(rows_by_date)
    for date in dates:
        payload = {"date": date, "asset_count": len(rows_by_date[date]), "data": rows_by_date[date]}
        with (DAILY_DIR / f"{date}.json").open("w", encoding="utf-8") as handle:
            json.dump(json_clean(payload), handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    latest = rows_by_date.get(dates[-1], []) if dates else []
    with (DATA_DIR / "latest.json").open("w", encoding="utf-8") as handle:
        json.dump(json_clean({"date": dates[-1] if dates else None, "asset_count": len(latest), "data": latest}), handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    with (DATA_DIR / "dates.json").open("w", encoding="utf-8") as handle:
        json.dump({"dates": dates, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, handle, ensure_ascii=False, separators=(",", ":"))
    with (DATA_DIR / "meta.json").open("w", encoding="utf-8") as handle:
        json.dump({"asset_type": "ETF", "fund_count": len(symbols), "symbols": symbols, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "start_date": dates[0] if dates else norm(args.start), "end_date": dates[-1] if dates else end}, handle, ensure_ascii=False, indent=2)
    symbols_dir = DATA_DIR / "symbols"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    with (symbols_dir / "etf.json").open("w", encoding="utf-8") as handle:
        json.dump([{"symbolname": "1634+场内ETF基金", "symbols": symbols}], handle, ensure_ascii=False, indent=2)
    print(f"ETF 更新完成：{len(symbols)} 只，{len(dates)} 个交易日，目录：{DATA_DIR}")


if __name__ == "__main__":
    main()

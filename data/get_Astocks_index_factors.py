#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compute per-day, per-index important factors and persist them.

Output layout (matches user spec):
    data/Astocks/factors/<ts_code>/<YYYYMMDD>.json

Each JSON file holds the high-value factor set for one index on one
trading day, derived entirely from the local OHLCV records already stored
in data/Astocks/indices/<code>.json.  Tushare is only used optionally to
pull incremental OHLCV rows when --refresh is set; if it fails (e.g. the
interface name does not exist for public indices, network is down, or no
token is configured), we fall back gracefully to local data only.

Public Chinese indices on tushare only expose daily OHLCV via
"index_daily".  They do NOT have "index_daily_basic" (PE/PB/total_mv)
or "index_moneyflow" in the public API, so those field families are
removed entirely.
"""
import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

try:
    import tushare as ts
    _HAS_TUSHARE = True
except Exception:
    _HAS_TUSHARE = False


INDICES = [
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000300.SH", "沪深300"),
    ("000905.SH", "中证500"),
    ("000852.SH", "中证1000"),
    ("932000.CSI", "中证2000"),
    ("000016.SH", "上证50"),
    ("000688.SH", "科创50"),
]


def normalize_date(value):
    return str(value or "").replace("-", "").replace("/", "")


# ---------- technical indicator helpers ----------

def sma(s, n):
    return s.rolling(n, min_periods=1).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=1).mean()


def macd(close, fast=12, slow=26, signal=9):
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    return dif, dea, (dif - dea) * 2


def kdj(df, n=9):
    low_n = df["low"].rolling(n, min_periods=1).min()
    high_n = df["high"].rolling(n, min_periods=1).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1.0/3, adjust=False).mean()
    d = k.ewm(alpha=1.0/3, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def rsi(close, n=6):
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1.0/n, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1.0/n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def boll(close, n=20, k=2):
    mid = sma(close, n)
    std = close.rolling(n, min_periods=2).std()
    return mid, mid + k * std, mid - k * std


def pct_change(s, n):
    return s.pct_change(n, fill_method=None) * 100


def rps(close, n=120):
    return close.rolling(n, min_periods=min(20, n)).rank(pct=True) * 100


# ---------- factor builder ----------

def build_factor_frame(records):
    """Compute the full factor panel for one index."""
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame()
    if "vol" not in df.columns and "volume" in df.columns:
        df = df.rename(columns={"volume": "vol"})
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = df["trade_date"].astype(str)

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = df["trade_date"]
    for c in ("close", "open", "high", "low", "pre_close", "change", "pct_chg", "vol", "amount"):
        if c in df.columns:
            out[c] = pd.to_numeric(df[c], errors="coerce")

    for n in (5, 10, 20, 60, 120, 250):
        out["ma_" + str(n)] = sma(out["close"], n)
    for n in (5, 10, 20, 60, 120, 250):
        out["change_" + str(n) + "d_pct"] = pct_change(out["close"], n)
    out["ytd_pct"] = (out["close"] / out["close"].expanding().min() - 1) * 100

    dif, dea, hist = macd(out["close"])
    out["macd_dif"], out["macd_dea"], out["macd_hist"] = dif, dea, hist
    k, d, j = kdj(df)
    out["kdj_k"], out["kdj_d"], out["kdj_j"] = k, d, j
    out["rsi_6"] = rsi(out["close"], 6)
    out["rsi_12"] = rsi(out["close"], 12)
    mid, up, lo = boll(out["close"], 20, 2)
    out["boll_mid"], out["boll_upper"], out["boll_lower"] = mid, up, lo
    out["boll_pct_b"] = (out["close"] - lo) / (up - lo).replace(0, np.nan)

    out["amplitude_pct"] = (out["high"] - out["low"]) / out["pre_close"].replace(0, np.nan) * 100
    out["realized_vol_20d_pct"] = out["pct_chg"].rolling(20, min_periods=5).std()

    out["turnover_ma5"] = sma(out["amount"], 5)
    out["amount_ratio_5d"] = out["amount"] / out["turnover_ma5"].replace(0, np.nan)
    out["volume_ratio"] = out["vol"] / sma(out["vol"], 5).replace(0, np.nan)
    out["liangbi"] = out["amount_ratio_5d"]

    for n in (20, 120, 250):
        out["rps_" + str(n)] = rps(out["close"], n)

    out["above_ma20"] = (out["close"] > out["ma_20"]).astype(int)
    out["above_ma60"] = (out["close"] > out["ma_60"]).astype(int)
    out["ma20_above_ma60"] = (out["ma_20"] > out["ma_60"]).astype(int)
    out["macd_golden_cross"] = ((dif > dea) & (dif.shift(1) <= dea.shift(1))).astype(int)
    out["macd_dead_cross"] = ((dif < dea) & (dif.shift(1) >= dea.shift(1))).astype(int)
    sign = (out["pct_chg"] > 0).astype(int)
    out["up_streak"] = sign.groupby((sign == 0).cumsum()).cumcount() + 1
    sign = (out["pct_chg"] < 0).astype(int)
    out["down_streak"] = sign.groupby((sign == 0).cumsum()).cumcount() + 1
    out["n_day_high_20"] = (out["close"] >= out["close"].rolling(20, min_periods=1).max()).astype(int)
    out["n_day_low_20"] = (out["close"] <= out["close"].rolling(20, min_periods=1).min()).astype(int)

    return out


# ---------- daily factor record (what is persisted per day) ----------

DAILY_FACTOR_KEYS = [
    "close", "open", "high", "low", "pre_close", "change", "pct_chg",
    "vol", "amount", "amount_ratio_5d", "volume_ratio", "turnover_ma5", "liangbi",
    "ma_5", "ma_10", "ma_20", "ma_60", "ma_120", "ma_250",
    "change_5d_pct", "change_10d_pct", "change_20d_pct",
    "change_60d_pct", "change_120d_pct", "change_250d_pct", "ytd_pct",
    "macd_dif", "macd_dea", "macd_hist",
    "kdj_k", "kdj_d", "kdj_j",
    "rsi_6", "rsi_12",
    "boll_mid", "boll_upper", "boll_lower", "boll_pct_b",
    "amplitude_pct", "realized_vol_20d_pct",
    "rps_20", "rps_120", "rps_250",
    "above_ma20", "above_ma60", "ma20_above_ma60",
    "macd_golden_cross", "macd_dead_cross",
    "up_streak", "down_streak", "n_day_high_20", "n_day_low_20",
]


def row_to_dict(row):
    out = {}
    for k in DAILY_FACTOR_KEYS:
        v = row.get(k)
        if v is None:
            out[k] = None
            continue
        if isinstance(v, float) and np.isnan(v):
            out[k] = None
            continue
        try:
            if isinstance(v, (int, float, np.floating, np.integer)):
                out[k] = round(float(v), 6)
            else:
                out[k] = v
        except (TypeError, ValueError):
            out[k] = None
    return out


# ---------- optional tushare refresh (index_daily only) ----------

def maybe_refresh_index_ohlcv(pro, ts_code, existing_records):
    if pro is None:
        return existing_records
    if not existing_records:
        start = "20250101"
    else:
        latest = max(normalize_date(r.get("trade_date")) for r in existing_records)
        start = (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    if start > end:
        return existing_records
    try:
        df = pro.query("index_daily", ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        print("  index_daily query failed for " + ts_code + ": " + repr(exc))
        return existing_records
    if df is None or df.empty:
        return existing_records
    incoming = df.sort_values("trade_date").to_dict(orient="records")
    by_date = {normalize_date(r.get("trade_date")): r for r in existing_records}
    for r in incoming:
        by_date[normalize_date(r.get("trade_date"))] = r
    return [by_date[k] for k in sorted(by_date)]


# ---------- main ----------

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Compute per-day index factors")
    default_root = Path(__file__).resolve().parent
    parser.add_argument("--indices-root", default=str(default_root / "Astocks" / "indices"))
    parser.add_argument("--output-root", default=str(default_root / "Astocks" / "factors"))
    parser.add_argument("--start", default="20250101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--only-new", action="store_true",
                        help="skip days already persisted in output root")
    parser.add_argument("--refresh", action="store_true",
                        help="attempt to refresh OHLCV from tushare before computing")
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    args = parser.parse_args()

    indices_root = Path(args.indices_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    pro = None
    if args.refresh:
        if not _HAS_TUSHARE:
            print("--refresh requested but tushare is not installed; skipping")
        elif not args.token:
            print("--refresh requested but TUSHARE_TOKEN is not set; skipping")
        else:
            try:
                pro = ts.pro_api(args.token)
            except Exception as exc:
                print("tushare init failed: " + repr(exc) + "; continuing without refresh")

    start = normalize_date(args.start)
    end = normalize_date(args.end)

    for code, name in INDICES:
        print("=== " + name + " (" + code + ") ===")
        src = indices_root / (code + ".json")
        if not src.exists():
            print("  missing " + str(src) + ", skip")
            continue
        try:
            with src.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print("  failed to read " + str(src) + ": " + str(exc))
            continue
        records = payload.get("records") or []
        if pro is not None:
            records = maybe_refresh_index_ohlcv(pro, code, records)
        if not records:
            print("  no records, skip")
            continue
        if start:
            records = [r for r in records if normalize_date(r.get("trade_date")) >= start]
        if end:
            records = [r for r in records if normalize_date(r.get("trade_date")) <= end]
        if not records:
            print("  no records in window, skip")
            continue

        factor_df = build_factor_frame(records)
        if factor_df.empty or "trade_date" not in factor_df.columns:
            print("  factor frame is empty, skip")
            continue

        per_index_dir = output_root / code
        per_index_dir.mkdir(parents=True, exist_ok=True)
        existing = {p.name for p in per_index_dir.glob("*.json")} if args.only_new else set()
        written, skipped = 0, 0
        for _, row in factor_df.iterrows():
            d = str(row["trade_date"]).replace("-", "")
            fname = d + ".json"
            if fname in existing:
                skipped += 1
                continue
            payload_out = {
                "ts_code": code,
                "name": name,
                "trade_date": d,
                "factors": row_to_dict(row),
            }
            with (per_index_dir / fname).open("w", encoding="utf-8") as f:
                json.dump(payload_out, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            written += 1
        print("  rows=" + str(len(factor_df)) + " written=" + str(written) + " skipped=" + str(skipped))


if __name__ == "__main__":
    main()

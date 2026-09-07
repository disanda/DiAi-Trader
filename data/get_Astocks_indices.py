"""Incrementally download common A-share indices into data/Astocks/indices."""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import tushare as ts
from dotenv import load_dotenv


INDICES = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "932000.CSI": "中证2000",
    "000016.SH": "上证50",
    "000688.SH": "科创50",
}


def normalize_date(value):
    return str(value or "").replace("-", "")


def load_records(path):
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f).get("records") or []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Update common A-share index data")
    parser.add_argument("--output", default=Path(__file__).resolve().parent / "Astocks" / "indices")
    parser.add_argument("--start", default="20250101")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("TUSHARE_TOKEN is required")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    pro = ts.pro_api(args.token)
    for code, name in INDICES.items():
        path = output / f"{code}.json"
        records = load_records(path)
        latest = max((normalize_date(row.get("trade_date")) for row in records), default="")
        start = (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d") if latest else normalize_date(args.start)
        if start <= normalize_date(args.end):
            df = pro.index_daily(ts_code=code, start_date=start, end_date=normalize_date(args.end))
            if df is not None and not df.empty:
                incoming = df.sort_values("trade_date").to_dict(orient="records")
                by_date = {normalize_date(row.get("trade_date")): row for row in records}
                by_date.update({normalize_date(row.get("trade_date")): row for row in incoming})
                records = [by_date[key] for key in sorted(by_date)]
        with path.open("w", encoding="utf-8") as f:
            json.dump({"ts_code": code, "name": name, "start_date": normalize_date(records[0].get("trade_date")) if records else start, "end_date": normalize_date(records[-1].get("trade_date")) if records else "", "records": records}, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        print(f"{name} ({code}): {len(records)} records")


if __name__ == "__main__":
    main()

"""Build stock-code groups used by the A-share market page.

The files are deliberately small JSON arrays so the page can load a group without
loading historical price data. Re-run this script after index constituent changes.
"""

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent



INDEX_GROUPS = {
    "sci2k": ["932000.CSI", "932000.SH"],
    "csi1000": ["000852.SH", "000852.CSI"],
    "csi500": ["000905.SH", "000905.CSI"],
    "hs300": ["000300.SH", "000300.CSI"],
    "sse50": ["000016.SH", "000016.CSI"],
    "star50": ["000688.SH", "000688.CSI"],
}
GROUP_NAMES = {
    "sci2k": "中证2000", "chinext": "创业板股票", "csi1000": "中证1000",
    "csi500": "中证500", "hs300": "沪深300", "sse50": "上证50",
    "star50": "科创50", "watchlist1": "自选股1", "watchlist2": "自选股2",
}


def write_group(directory: Path, group_id: str, symbols: list[str]) -> None:
    symbols = sorted(set(symbols))
    with (directory / f"{group_id}.json").open("w", encoding="utf-8") as f:
        json.dump({"symbolname": GROUP_NAMES.get(group_id, group_id), "symbols": symbols}, f, ensure_ascii=False, indent=2)
    print(f"{group_id}: {len(symbols)} stocks")


def latest_index_members(pro, index_codes: list[str], end_date: str) -> list[str]:
    start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=370)).strftime("%Y%m%d")
    for index_code in index_codes:
        df = pro.index_weight(index_code=index_code, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            latest_date = df["trade_date"].max()
            return df.loc[df["trade_date"] == latest_date, "con_code"].dropna().astype(str).tolist()
    raise RuntimeError(f"No index members returned for {', '.join(index_codes)}")


def local_chinext_symbols(stocks_dir: Path) -> list[str]:
    return [path.stem for path in stocks_dir.glob("*.json") if path.stem.startswith(("300", "301")) and path.stem.endswith(".SZ")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate A-share market-page symbol groups")
    parser.add_argument("--output", default=PROJECT_DIR / "data" / "Astocks" / "symbols")
    parser.add_argument("--stocks-dir", default=PROJECT_DIR / "data" / "Astocks" / "stocks")
    parser.add_argument("--sse50-source", default=PROJECT_DIR / "docs" / "data" / "stocks.json")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--token", default=os.getenv("TUSHARE_TOKEN"))
    parser.add_argument("--local-only", action="store_true", help="Only create groups available from local files")
    args = parser.parse_args()

    if not args.local_only and not args.token:
        from dotenv import load_dotenv
        load_dotenv()
        args.token = os.getenv("TUSHARE_TOKEN")
    if not args.token and not args.local_only:
        raise SystemExit("TUSHARE_TOKEN is required for index constituent groups")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stocks_dir = Path(args.stocks_dir)
    if not args.local_only:
        import tushare as ts
        pro = ts.pro_api(args.token)
        for group_id, index_code in INDEX_GROUPS.items():
            write_group(output, group_id, latest_index_members(pro, index_code, args.end))
    else:
        source = Path(args.sse50_source)
        if source.exists():
            with source.open("r", encoding="utf-8") as f:
                write_group(output, "sse50", json.load(f).get("sse_50", []))

    write_group(output, "chinext", local_chinext_symbols(stocks_dir))
    for group_id in ("watchlist1", "watchlist2"):
        path = output / f"{group_id}.json"
        if not path.exists():
            write_group(output, group_id, [])


if __name__ == "__main__":
    main()

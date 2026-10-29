"""
全部 A 股数据获取与存储脚本
- 获取全部上市 A 股列表（stock_basic）
- 获取日线行情（daily）
- 获取每日基本面因子（daily_basic）：PE/PB/市值/换手率
- 自算技术因子：动量、波动率、均线、量比
- 存储格式：
    data/Astocks/stocks/<ts_code>.json  每只股票独立文件
    data/Astocks/merged.json            （可选）合并文件，仅 --write-merged 时生成
    data/Astocks/meta.json              元信息（股票列表、更新时间等）
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv

load_dotenv()

# ── 常量 ──────────────────────────────────────────────────────────────────
INDEX_CODE   = "ALL_A_STOCKS"         # 全部 A 股标识
DATA_DIR     = Path(os.getenv("ASTOCKS_DATA_DIR", Path(__file__).parent / "Astocks"))
STOCKS_DIR   = DATA_DIR / "stocks"
DAILY_DIR    = DATA_DIR / "daily"
MERGED_FILE  = DATA_DIR / "merged.json"
META_FILE    = DATA_DIR / "meta.json"
DATES_FILE   = DATA_DIR / "dates.json"
LATEST_FILE  = DATA_DIR / "latest.json"

DEFAULT_START = "20250101"
DEFAULT_END   = "20260531"


# ── 工具函数 ──────────────────────────────────────────────────────────────
def _to_tushare_date(date_str: str) -> str:
    """统一转换为 yyyymmdd 格式"""
    return date_str.replace("-", "")


def _compact_record(record: dict, *, strip_name: bool = False) -> dict:
    """Remove JSON nulls and optionally the repeated symbol name."""
    if not isinstance(record, dict):
        return record
    return {
        key: value
        for key, value in record.items()
        if value is not None and not (strip_name and key == "name")
    }


def _calc_tech_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    基于日线行情（close/vol/amount）自算技术因子。
    df 需包含列：close, vol, amount，已按 trade_date 升序。
    """
    c = df["close"]
    ret = c.pct_change()

    # 动量
    df["mom_5"]  = c.pct_change(5)
    df["mom_10"] = c.pct_change(10)
    df["mom_20"] = c.pct_change(20)

    # 波动率（收益率标准差）
    df["volatility_10"] = ret.rolling(10).std()
    df["volatility_20"] = ret.rolling(20).std()

    # 均线
    df["ma5"]  = c.rolling(5).mean()
    df["ma10"] = c.rolling(10).mean()
    df["ma20"] = c.rolling(20).mean()

    # 均线偏离度（价格偏离20日均线的程度）
    df["ma20_dev"] = (c - df["ma20"]) / df["ma20"]

    # 量比（5日均量 / 20日均量）
    vol_ma5  = df["vol"].rolling(5).mean()
    vol_ma20 = df["vol"].rolling(20).mean()
    df["vol_ratio"] = vol_ma5 / vol_ma20

    # 成交额均值
    df["amount_ma5"] = df["amount"].rolling(5).mean()

    return df


class AstocksHandler:

    def __init__(self, token: str = None, start_date: str = DEFAULT_START, end_date: str = DEFAULT_END, incremental: bool = False, symbols: list[str] = None):
        """
        Args:
            token:      Tushare API Token，若为 None 则从环境变量 TUSHARE_TOKEN 读取
            start_date: 开始日期，支持 'yyyymmdd' 或 'yyyy-mm-dd'
            end_date:   结束日期，同上
            incremental: 是否从本地最新日期继续更新；默认 False，严格抓取指定日期范围
        """
        _token = token or os.getenv("TUSHARE_TOKEN")
        if not _token:
            raise ValueError("请提供 Tushare Token 或在 .env 中设置 TUSHARE_TOKEN")

        self.pro = ts.pro_api(_token)
        self.start_date = _to_tushare_date(start_date)
        self.end_date   = _to_tushare_date(end_date)
        self.incremental = incremental
        self.requested_symbols = {str(symbol).strip().upper() for symbol in (symbols or []) if str(symbol).strip()}
        self.symbol_start_dates = {}
        self.new_symbols = set()

        # 创建目录
        STOCKS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"📁 输出目录: {DATA_DIR.resolve()}")
        print(f"📅 日期范围: {self.start_date} ~ {self.end_date}")

    def build_frontend_partitions(self, *, write_daily: bool = False) -> None:
        """
        从单股历史文件刷新 dates.json 与 latest.json。

        默认仅保留日期集合与最新行情，不生成 daily/。显式指定 write_daily
        时使用临时 JSONL 文件额外生成旧版按日分片。
        """
        import shutil
        build_started = time.monotonic()

        stock_files = sorted(STOCKS_DIR.glob("*.json"))
        if not stock_files:
            raise RuntimeError(f"未找到单股历史文件：{STOCKS_DIR}")

        if not write_daily:
            dates, latest_rows, latest_date = set(), [], ''
            for path in stock_files:
                try:
                    with path.open(encoding='utf-8-sig') as handle:
                        payload = json.load(handle)
                except (OSError, ValueError) as exc:
                    print(f'  Skipping invalid stock file {path.name}: {exc}')
                    continue
                symbol = payload.get('ts_code') or path.stem
                for record in payload.get('records') or []:
                    day = str(record.get('trade_date') or record.get('date') or '').replace('-', '')
                    if not day:
                        continue
                    dates.add(day)
                    if day > latest_date:
                        latest_date, latest_rows = day, []
                    if day == latest_date:
                        latest_rows.append({**record, 'ts_code': symbol,
                                            'name': payload.get('name') or record.get('name') or symbol})
            with DATES_FILE.open('w', encoding='utf-8') as handle:
                json.dump({'dates': sorted(dates), 'updated_at': datetime.now().isoformat(timespec='seconds')}, handle, ensure_ascii=False, separators=(',', ':'))
            with LATEST_FILE.open('w', encoding='utf-8') as handle:
                json.dump({'date': latest_date or None, 'stock_count': len(latest_rows), 'data': latest_rows}, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            print(f'Metadata refreshed: {len(dates)} dates; daily/ generation disabled')
            return

        temp_dir = DATA_DIR / ".daily_build"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        DAILY_DIR.mkdir(parents=True, exist_ok=True)

        writers = {}
        counts = {}
        try:
            print(f"\n🧩 正在从 {len(stock_files)} 个单股文件生成按日分段数据...")
            for index, stock_file in enumerate(stock_files, start=1):
                try:
                    with stock_file.open("r", encoding="utf-8") as f:
                        payload = json.load(f)
                    ts_code = payload.get("ts_code", stock_file.stem)
                    for record in payload.get("records", []):
                        trade_date = record.get("trade_date") or record.get("date")
                        if not trade_date:
                            continue
                        output_record = {"ts_code": ts_code, **record}
                        if payload.get("name") and "name" not in output_record:
                            output_record["name"] = payload["name"]
                        writer = writers.get(trade_date)
                        if writer is None:
                            writer = (temp_dir / f"{trade_date}.jsonl").open("a", encoding="utf-8")
                            writers[trade_date] = writer
                        writer.write(json.dumps(output_record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
                        counts[trade_date] = counts.get(trade_date, 0) + 1
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    print(f"  ⚠️ 跳过异常文件 {stock_file.name}: {exc}")
                if index % 500 == 0 or index == len(stock_files):
                    print(f"  进度: {index}/{len(stock_files)}")
        finally:
            for writer in writers.values():
                writer.close()

        dates = sorted(counts)
        latest_payload = None
        for trade_date in dates:
            source = temp_dir / f"{trade_date}.jsonl"
            target = DAILY_DIR / f"{trade_date}.json"
            with source.open("r", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
            payload = {"date": trade_date, "stock_count": len(rows), "data": rows}
            with target.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if trade_date == dates[-1]:
                latest_payload = payload

        with DATES_FILE.open("w", encoding="utf-8") as f:
            json.dump({"dates": dates, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, separators=(",", ":"))
        with LATEST_FILE.open("w", encoding="utf-8") as f:
            json.dump(latest_payload or {"date": None, "stock_count": 0, "data": []}, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

        shutil.rmtree(temp_dir, ignore_errors=True)
        elapsed = time.monotonic() - build_started
        print(f"Partition rebuild: {len(stock_files)} stocks, {len(dates)} dates in {elapsed:.1f}s ({len(stock_files) / max(elapsed, 0.001):.1f} stocks/s)")
        print(f"  ✅ 日期目录：{DATES_FILE}（{len(dates)} 个交易日）")
        print(f"  ✅ 最新行情：{LATEST_FILE}")
        print(f"  ✅ 分段目录：{DAILY_DIR}")

    def _detect_latest_saved_date(self):
        """扫描已保存的 JSON 文件，返回已存在数据的最晚 trade_date（yyyymmdd），没有则返回 None。"""
        max_date = None
        # 优先读取 meta.json 或 merged.json
        try:
            if META_FILE.exists():
                with open(META_FILE, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    end = meta.get('end_date')
                    if end:
                        return end.replace('-', '')
            if MERGED_FILE.exists():
                with open(MERGED_FILE, 'r', encoding='utf-8') as f:
                    merged = json.load(f)
                    data = merged.get('data', {})
                    for ts_code, records in data.items():
                        if records:
                            last = records[-1].get('trade_date') or records[-1].get('date')
                            if last:
                                d = last.replace('-', '')
                                if (max_date is None) or (d > max_date):
                                    max_date = d
                    if max_date:
                        return max_date
        except Exception:
            pass

        # 回退到逐文件扫描 stocks 目录
        try:
            for p in STOCKS_DIR.glob('*.json'):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                        records = obj.get('records') or []
                        if records:
                            last = records[-1].get('trade_date') or records[-1].get('date')
                            if last:
                                d = last.replace('-', '')
                                if (max_date is None) or (d > max_date):
                                    max_date = d
                except Exception:
                    continue
        except Exception:
            pass

        return max_date

    def _existing_last_dates(self, symbols: list[str]) -> dict[str, str]:
        """Return the last saved date per symbol without loading the 1GB merged file."""
        result = {}
        for symbol in symbols:
            path = STOCKS_DIR / f"{symbol}.json"
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    records = (json.load(f).get("records") or [])
                dates = [str(r.get("trade_date") or r.get("date", "")).replace("-", "") for r in records]
                dates = [d for d in dates if d]
                if dates:
                    result[symbol] = max(dates)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return result

    # ── Step 1: 获取成分股 ──────────────────────────────────────────────
    def fetch_constituents(self) -> tuple[list[str], dict[str, str]]:
        """获取全部上市 A 股列表，返回 (ts_code列表, {ts_code: 中文名} 字典)。"""
        print("\n🔍 获取全部 A 股列表...")
        df = self.pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        if df is None or df.empty:
            raise RuntimeError("未能获取全部 A 股列表，请检查 Tushare 权限或 Token")
        # 沪深北交易所股票代码；排除基金、债券和指数
        df = df[df["ts_code"].str.endswith((".SH", ".SZ", ".BJ"), na=False)]
        if self.requested_symbols:
            df = df[df["ts_code"].isin(self.requested_symbols)]
            missing = sorted(self.requested_symbols - set(df["ts_code"].astype(str)))
            if missing:
                print(f"⚠️ 未在上市 A 股列表中找到：{', '.join(missing)}")
            if df.empty:
                raise RuntimeError("指定的 A 股均未在 Tushare 上市股票列表中找到")
        symbols = df["ts_code"].drop_duplicates().tolist()
        name_map = dict(zip(df["ts_code"], df["name"]))
        print(f"✅ 共 {len(symbols)} 只成分股，正在获取股票名称...")

        # 批量获取股票基本信息（名称）
        name_map = {}
        try:
            batch_size = 100
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i+batch_size]
                df_basic = self.pro.stock_basic(
                    ts_code=",".join(batch),
                    fields="ts_code,name"
                )
                if df_basic is not None and not df_basic.empty:
                    for _, row in df_basic.iterrows():
                        name_map[row["ts_code"]] = row["name"]
                time.sleep(0.2)
            print(f"✅ 获取到 {len(name_map)} 只股票名称")
        except Exception as e:
            print(f"⚠️  获取股票名称失败: {e}，将使用空名称")

        return symbols, name_map

    # ── Step 2: 获取交易日历 ───────────────────────────────────────────
    def fetch_trade_dates(self, start_date: str | None = None) -> list[str]:
        df = self.pro.trade_cal(
            exchange="SSE",
            start_date=start_date or self.start_date,
            end_date=self.end_date,
            is_open="1",
        )
        return df["cal_date"].tolist()

    # ── Step 3: 获取日线行情 ───────────────────────────────────────────
    def fetch_daily(self, symbols: list[str]) -> pd.DataFrame:
        """按日期循环拉取所有成分股日线行情（效率更高）"""
        existing_symbols = [symbol for symbol in symbols if symbol not in self.new_symbols]
        starts = [self.symbol_start_dates.get(symbol, self.start_date) for symbol in existing_symbols]
        scan_start = min(starts) if starts else self.end_date
        trade_dates = self.fetch_trade_dates(scan_start) if existing_symbols and scan_start <= self.end_date else []
        if not trade_dates and not self.new_symbols:
            print("  ℹ️ 未检测到交易日，跳过日线拉取。")
            return pd.DataFrame()
        all_data = []

        # Fetch newly-added symbols by code and date range in batches instead
        # of requesting every market-wide trading day since the fallback date.
        new_symbols = sorted(self.new_symbols.intersection(symbols))
        for offset in range(0, len(new_symbols), 10):
            batch = new_symbols[offset:offset + 10]
            try:
                frame = self.pro.daily(ts_code=",".join(batch), start_date=self.start_date,
                    end_date=self.end_date,
                    fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount")
                if frame is not None and not frame.empty:
                    all_data.append(frame)
            except Exception as exc:
                print(f"New-symbol daily range request failed: {exc}")
        print(f"Incremental daily: {len(new_symbols)} new symbols by range; {len(trade_dates)} missing-date checks for existing symbols")

        print(f"\n📈 拉取日线行情（共 {len(trade_dates)} 个交易日）...")
        for i, date in enumerate(trade_dates):
            active_symbols = {
                symbol for symbol in existing_symbols
                if date >= self.symbol_start_dates.get(symbol, self.start_date)
            }
            if not active_symbols:
                continue
            try:
                df = self.pro.daily(
                    trade_date=date,
                    fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
                )
                if df is not None and not df.empty:
                    df = df[df["ts_code"].isin(active_symbols)]
                    all_data.append(df)
            except Exception as e:
                print(f"  ⚠️  {date} 行情获取失败: {e}")
            time.sleep(0.3)
            if (i + 1) % 10 == 0:
                print(f"  进度: {i+1}/{len(trade_dates)}")

        if not all_data:
            print("  ℹ️ 在指定日期范围内未拉取到任何日线数据。")
            return pd.DataFrame()
        result = pd.concat(all_data, ignore_index=True)
        print(f"✅ 日线行情：{len(result)} 条，{result['ts_code'].nunique()} 只股票")
        return result

    # ── Step 4: 获取每日基本面因子 ─────────────────────────────────────
    def fetch_daily_basic(self, symbols: list[str]) -> pd.DataFrame:
        """PE/PB/市值/换手率等基本面因子"""
        existing_symbols = [symbol for symbol in symbols if symbol not in self.new_symbols]
        starts = [self.symbol_start_dates.get(symbol, self.start_date) for symbol in existing_symbols]
        scan_start = min(starts) if starts else self.end_date
        trade_dates = self.fetch_trade_dates(scan_start) if existing_symbols and scan_start <= self.end_date else []
        if not trade_dates and not self.new_symbols:
            print("  ℹ️ 未检测到交易日，跳过基本面因子拉取。")
            return pd.DataFrame()
        all_data = []

        new_symbols = sorted(self.new_symbols.intersection(symbols))
        for offset in range(0, len(new_symbols), 10):
            batch = new_symbols[offset:offset + 10]
            try:
                frame = self.pro.daily_basic(ts_code=",".join(batch), start_date=self.start_date,
                    end_date=self.end_date,
                    fields="ts_code,trade_date,pe,pe_ttm,pb,ps_ttm,turnover_rate,turnover_rate_f,total_mv,circ_mv,free_share")
                if frame is not None and not frame.empty:
                    all_data.append(frame)
            except Exception as exc:
                print(f"New-symbol basic range request failed: {exc}")
        print(f"Incremental basic: {len(new_symbols)} new symbols by range; {len(trade_dates)} missing-date checks for existing symbols")

        print(f"\n📊 拉取每日基本面因子...")
        for i, date in enumerate(trade_dates):
            active_symbols = {
                symbol for symbol in existing_symbols
                if date >= self.symbol_start_dates.get(symbol, self.start_date)
            }
            if not active_symbols:
                continue
            try:
                df = self.pro.daily_basic(
                    trade_date=date,
                    fields="ts_code,trade_date,pe,pe_ttm,pb,ps_ttm,turnover_rate,turnover_rate_f,total_mv,circ_mv,free_share",
                )
                if df is not None and not df.empty:
                    df = df[df["ts_code"].isin(active_symbols)]
                    all_data.append(df)
            except Exception as e:
                print(f"  ⚠️  {date} 基本面因子获取失败: {e}")
            time.sleep(0.3)
            if (i + 1) % 10 == 0:
                print(f"  进度: {i+1}/{len(trade_dates)}")

        result = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
        if result.empty:
            print("⚠️ 基本面接口未返回记录；将保留日线行情，基本面字段留空")
        else:
            print(f"✅ 基本面因子：{len(result)} 条")
        return result

    # ── Step 5: 合并 + 计算技术因子 ────────────────────────────────────
    def build_factor_table(self, df_daily: pd.DataFrame, df_basic: pd.DataFrame) -> pd.DataFrame:
        """合并日线行情与基本面因子，并追加技术因子"""
        print("\n🔧 合并数据并计算技术因子...")

        merge_keys = ["ts_code", "trade_date"]
        basic_fields = [
            "pe", "pe_ttm", "pb", "ps_ttm", "turnover_rate",
            "turnover_rate_f", "total_mv", "circ_mv", "free_share",
        ]
        missing_daily_keys = [key for key in merge_keys if key not in df_daily.columns]
        if missing_daily_keys:
            raise ValueError(f"日线数据缺少合并字段: {', '.join(missing_daily_keys)}")

        if df_basic is None or df_basic.empty:
            print("⚠️ 基本面数据为空，技术因子照常计算，基本面字段将保存为空值")
            df_basic = pd.DataFrame(columns=merge_keys + basic_fields)
        else:
            missing_basic_keys = [key for key in merge_keys if key not in df_basic.columns]
            if missing_basic_keys:
                raise ValueError(f"基本面数据缺少合并字段: {', '.join(missing_basic_keys)}")
            df_basic = df_basic.reindex(columns=merge_keys + basic_fields)

        df = pd.merge(
            df_daily,
            df_basic,
            on=["ts_code", "trade_date"],
            how="left",
        )

        # 按股票分组计算技术因子
        df = df.sort_values(["ts_code", "trade_date"])
        df = pd.concat(
            (_calc_tech_factors(group) for _, group in df.groupby("ts_code", sort=False)),
            ignore_index=True,
        )

        # 数值列保留4位小数，避免 JSON 体积过大
        float_cols = df.select_dtypes("float64").columns
        df[float_cols] = df[float_cols].round(4)

        # NaN → None（JSON 兼容）
        df = df.where(pd.notna(df), None)

        print(f"✅ 因子表构建完成：{df.shape[0]} 行 × {df.shape[1]} 列")
        return df

    # ── Step 6: 保存数据 ───────────────────────────────────────────────
    def save(self, df: pd.DataFrame, symbols: list[str], name_map: dict = None):
        """
        保存数据：
        1. data/Astocks/stocks/<ts_code>.json  每只股票独立 JSON
        2. data/Astocks/meta.json              元信息
        3. data/Astocks/merged.json            可选；仅 --write-merged 时生成
        """
        print(f"\n💾 保存数据...")
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name_map = name_map or {}
        columns = df.columns.tolist()

        merged_dict = {}   # ts_code -> [records]
        global_min = None
        global_max = None

        for ts_code, group in df.groupby("ts_code"):
            new_records = group.drop(columns="ts_code").to_dict(orient="records")
            # 确保所有 float nan / inf 转为 None（JSON null），避免 allow_nan=False 报错
            import math
            def _clean(v):
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return None
                return v
            new_records = [{k: _clean(v) for k, v in r.items()} for r in new_records]
            # 注入股票中文名称到每条记录
            stock_name = name_map.get(ts_code, "")

            # 读取已有文件并合并（按 trade_date 去重，保留最新抓取的字段）
            stock_file = STOCKS_DIR / f"{ts_code}.json"
            existing_records = []
            try:
                if stock_file.exists():
                    with open(stock_file, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                        existing_records = obj.get('records') or []
            except Exception:
                existing_records = []

            def _norm_date(v):
                if not v:
                    return None
                return v.replace('-', '')

            rec_map = {}
            # 先填入旧记录
            for r in existing_records:
                td = r.get('trade_date') or r.get('date')
                nd = _norm_date(td)
                if nd:
                    rec_map[nd] = r
            # 覆盖/添加新记录
            for r in new_records:
                td = r.get('trade_date') or r.get('date')
                nd = _norm_date(td)
                if nd:
                    rec_map[nd] = r

            # 按日期升序构建最终记录列表
            merged_records = [
                _compact_record(rec_map[k], strip_name=True)
                for k in sorted(rec_map.keys())
            ]

            if merged_records:
                start_d = _norm_date(merged_records[0].get('trade_date') or merged_records[0].get('date'))
                end_d = _norm_date(merged_records[-1].get('trade_date') or merged_records[-1].get('date'))
            else:
                start_d = self.start_date
                end_d = self.end_date

            # 写回单股文件（覆盖旧文件，内容为合并后的记录）
            with open(stock_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "ts_code":    ts_code,
                        "start_date": start_d,
                        "end_date":   end_d,
                        "updated_at": updated_at,
                        "name":        stock_name,
                        "columns":    columns,
                        "records":    merged_records,
                    },
                    f,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )

            merged_dict[ts_code] = merged_records

            # 更新全局范围
            if start_d:
                if (global_min is None) or (start_d < global_min):
                    global_min = start_d
            if end_d:
                if (global_max is None) or (end_d > global_max):
                    global_max = end_d

        # Keep unchanged stocks in merged/meta outputs during incremental runs.
        merged_name_map = dict(name_map)
        for stock_file in STOCKS_DIR.glob("*.json"):
            ts_code = stock_file.stem
            if ts_code in merged_dict:
                continue
            try:
                with stock_file.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
                merged_dict[ts_code] = payload.get("records") or []
                if payload.get("name"):
                    merged_name_map[ts_code] = payload["name"]
            except (OSError, ValueError, json.JSONDecodeError):
                continue

        saved_count = len(merged_dict)
        all_dates = [
            str(record.get("trade_date") or record.get("date", "")).replace("-", "")
            for records in merged_dict.values() for record in records
        ]
        all_dates = [d for d in all_dates if d]
        global_min = min(all_dates) if all_dates else global_min
        global_max = max(all_dates) if all_dates else global_max
        print(f"  ✅ 单股文件：{saved_count} 个 → {STOCKS_DIR}")

        # ── merged.json（可选，默认关闭）──────────────────────────────
        # 结构：{ "meta": {...}, "columns": [...], "data": { ts_code: [records] } }
        # Keep names once in a top-level map instead of repeating them per row.
        if getattr(self, 'write_merged', False):
            merged_dict = {
                symbol: [_compact_record(record, strip_name=True) for record in records]
                for symbol, records in merged_dict.items()
            }
            merged_payload = {
                "meta": {
                    "index_code":   INDEX_CODE,
                    "start_date":   (global_min or self.start_date),
                    "end_date":     (global_max or self.end_date),
                    "updated_at":   updated_at,
                    "stock_count":  saved_count,
                },
                "columns": [c for c in columns if c != "ts_code"],
                "names": merged_name_map,
                "data":    merged_dict,
            }
            with open(MERGED_FILE, "w", encoding="utf-8") as f:
                json.dump(merged_payload, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            print(f"  ✅ 合并文件 → {MERGED_FILE}")

        # ── meta.json ────────────────────────────────────────────────
        meta = {
            "index_code":   INDEX_CODE,
            "start_date":   (global_min or self.start_date),
            "end_date":     (global_max or self.end_date),
            "updated_at":   updated_at,
            "stock_count":  saved_count,
            "symbols":      sorted(merged_dict),
            "columns":      columns,
            "name_map":     merged_name_map,
        }
        with open(META_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 元信息文件 → {META_FILE}")

        self.build_frontend_partitions(write_daily=getattr(self, 'write_daily', False))

    # ── 主入口 ─────────────────────────────────────────────────────────
    def run(self):
        """完整流程：获取成分股 → 拉行情 → 拉因子 → 合并 → 保存"""
        print("=" * 60)
        print("🚀 全部 A 股数据获取任务启动")
        print("=" * 60)

        # 历史回补默认严格遵从 --start；仅显式请求时才启用增量模式。
        if self.incremental:
            latest = None
            if latest:
                try:
                    next_day = (datetime.strptime(latest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                    if next_day > self.start_date:
                        print(f"🔁 发现已有数据，调整起始日期：{self.start_date} -> {next_day}")
                        self.start_date = next_day
                except Exception:
                    pass

        # 若结束日期使用默认值，自动更新为今天
        # Incremental ranges are resolved per stock after fetching the symbol list.
        today = datetime.now().strftime("%Y%m%d")
        if self.end_date == _to_tushare_date(DEFAULT_END):
            self.end_date = today

        print(f"📅 实际使用日期范围: {self.start_date} ~ {self.end_date}")

        # 若起始日期晚于结束日期，说明无新数据可拉，优雅退出
        if self.start_date > self.end_date:
            print("ℹ️ 起始日期晚于结束日期，未检测到需要追加的数据，任务退出。")
            return

        symbols, name_map = self.fetch_constituents()
        if self.incremental:
            last_dates = self._existing_last_dates(symbols)
            self.symbol_start_dates = {
                symbol: (
                    (datetime.strptime(last_dates[symbol], "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                    if symbol in last_dates else self.start_date
                )
                for symbol in symbols
            }
            self.new_symbols = set(symbols) - set(last_dates)
            if self.symbol_start_dates:
                self.start_date = min(self.symbol_start_dates.values())
            print(f"Incremental update: {len(last_dates)} existing, {len(symbols) - len(last_dates)} new stocks")
        else:
            self.symbol_start_dates = {symbol: self.start_date for symbol in symbols}
            self.new_symbols = set(symbols)
        df_daily   = self.fetch_daily(symbols)
        if df_daily is None or df_daily.empty:
            print("ℹ️ 未拉取到日线数据，任务结束。")
            return
        df_basic   = self.fetch_daily_basic(symbols)
        df_factors = self.build_factor_table(df_daily, df_basic)
        self.save(df_factors, symbols, name_map)

        print("\n" + "=" * 60)
        print("🎉 全部完成！")
        print(f"   单股文件目录：{STOCKS_DIR}")
        if getattr(self, 'write_merged', False):
            print(f"   合并文件：    {MERGED_FILE}")
        print(f"   元信息文件：  {META_FILE}")
        print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="获取全部 A 股股票因子数据")
    parser.add_argument("--start", default=DEFAULT_START, help="开始日期 yyyymmdd 或 yyyy-mm-dd（默认20250101）")
    parser.add_argument("--end",   default=DEFAULT_END,   help="结束日期 yyyymmdd 或 yyyy-mm-dd（默认20260531）")
    parser.add_argument("--token", default=None,          help="Tushare Token（默认从 .env TUSHARE_TOKEN 读取）")
    parser.add_argument("--incremental", action="store_true", help="仅抓取本地最新日期之后的数据")
    parser.add_argument("--symbols", nargs="*", help="仅更新指定 A 股代码")
    parser.add_argument("--build-partitions", action="store_true", help="仅从现有单股历史文件生成按日期分段的前端 JSON")
    parser.add_argument("--write-daily", action="store_true", help="更新后额外生成旧版 daily/ 分片（默认不生成）")
    parser.add_argument("--write-merged", action="store_true", help="更新后额外生成合并文件 merged.json（默认不生成）")
    args = parser.parse_args()

    handler = AstocksHandler(
        token=args.token,
        start_date=args.start,
        end_date=args.end,
        incremental=args.incremental,
        symbols=args.symbols,
    )
    if args.build_partitions:
        handler.build_frontend_partitions(write_daily=True)
    else:
        handler.write_daily = args.write_daily
        handler.write_merged = args.write_merged
        handler.run()

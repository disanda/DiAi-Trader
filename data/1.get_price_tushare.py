import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd
import tushare as ts
from dotenv import load_dotenv
from collections import OrderedDict
load_dotenv()

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import importlib
from agent.general_tools import get_config_value

#from utils.ashare_symbol import ETF_25 # sse_50_symbols, all_nasdaq_100_symbols

def get_last_month_dates() -> tuple[str, str]:
    """Get the first and last day of last month.
    Returns:
        tuple[str, str]: (start_date, end_date) in 'YYYYMMDD' format
    """
    today = datetime.now()
    first_day_of_this_month = today.replace(day=1)
    last_day_of_last_month = first_day_of_this_month - timedelta(days=1)
    first_day_of_last_month = last_day_of_last_month.replace(day=1)

    start_date = first_day_of_last_month.strftime("%Y%m%d")
    end_date = last_day_of_last_month.strftime("%Y%m%d")

    return start_date, end_date

def calculate_batch_days(num_stocks: int, max_records: int = 6000) -> int:
    """Calculate how many days of data can be fetched per batch.
    Args:
        num_stocks: Number of stocks to fetch
        max_records: Maximum records per API call (default: 6000)
    Returns:
        int: Number of days per batch
    """
    return max(1, max_records // num_stocks)

def api_call_with_retry(api_func, pro_api_instance, max_retries: int = 3, retry_delay: int = 5, timeout: int = 120, **kwargs):
    """Call tushare API with retry mechanism and timeout handling.
    Args:
        api_func: The tushare API function to call
        pro_api_instance: The tushare pro_api instance (needed to set timeout)
        max_retries: Maximum number of retry attempts
        retry_delay: Delay in seconds between retries
        timeout: Request timeout in seconds
        **kwargs: Arguments to pass to the API function
        
    Returns:
        Result from the API call
        
    Raises:
        Exception: If all retries fail
    """
    import requests
    
    # Set timeout for the pro_api instance's underlying requests session
    if hasattr(pro_api_instance, 'api') and hasattr(pro_api_instance.api, 'timeout'):
        pro_api_instance.api.timeout = timeout
    
    for attempt in range(1, max_retries + 1):
        try:
            result = api_func(**kwargs)
            return result
            
        except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout, 
                requests.exceptions.ConnectionError) as e:
            if attempt < max_retries:
                wait_time = retry_delay * attempt
                print(f"⚠️ 网络超时错误 (尝试 {attempt}/{max_retries})，等待 {wait_time} 秒后重试...")
                print(f"错误详情: {str(e)}")
                time.sleep(wait_time)
            else:
                print(f"❌ 所有重试尝试均失败")
                raise
        except Exception as e:
            # Check if it's a timeout-related error in the error message
            error_str = str(e).lower()
            if 'timeout' in error_str or 'timed out' in error_str or 'read timeout' in error_str:
                if attempt < max_retries:
                    wait_time = retry_delay * attempt
                    print(f"⚠️ 网络超时错误 (尝试 {attempt}/{max_retries})，等待 {wait_time} 秒后重试...")
                    print(f"错误详情: {str(e)}")
                    time.sleep(wait_time)
                else:
                    print(f"❌ 所有重试尝试均失败")
                    raise
            else:
                # For other errors, also retry
                if attempt < max_retries:
                    wait_time = retry_delay * attempt
                    print(f"⚠️ API 调用错误 (尝试 {attempt}/{max_retries})，等待 {wait_time} 秒后重试...")
                    print(f"错误详情: {str(e)}")
                    time.sleep(wait_time)
                else:
                    print(f"❌ 所有重试尝试均失败")
                    raise
    
    raise Exception("所有重试尝试均失败")

# 1. 专门处理基准指数 → 输出 JSON
def get_benchmark_index_json(
    index_code: str = "000001.SH",
    start_date: str = "20200101",
    freq: str = "Daily",
    output_dir: Optional[Path] = None,
    ts_api = None,
) -> Optional[Path]:
    """
    获取并保存基准指数的日/周线数据，转成 Alpha Vantage 风格 JSON
    返回保存的文件路径（如果成功）
    """
    pro = ts_api
    suffix = "day" if freq == "Daily" else "Weekly"
    
    if output_dir is None:
        output_dir = Path(__file__).parent / f"a_stock_data/{index_code}_{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_path = output_dir / f"index_{freq}_{index_code}.json"
    
    try:
        api_func = pro.index_daily if freq == "Daily" else pro.index_weekly
        df = api_call_with_retry(
            api_func,
            pro_api_instance=pro,
            ts_code=index_code,
            start_date=start_date,
            end_date=datetime.now().strftime("%Y%m%d")
        )
        
        if df is None or df.empty:
            print(f"未获取到指数 {index_code} 的数据")
            return None
            
        convert_index_to_json(df, symbol=index_code, output_file=json_path, freq=freq)
        print(f"基准指数 JSON 已保存: {json_path}")
        return json_path
        
    except Exception as e:
        print(f"获取基准指数失败: {e}")
        return None

# 2. 专门处理自定义股票/ETF 列表 → 输出 CSV（合并或分开）
def get_custom_symbols_prices_csv(
    symbols: list[str],
    start_date: str = "20200101",
    freq: str = "Daily",
    output_dir: Optional[Path] = None,
    ts_api = None,
    group_name: str = "ZSG",          # 用于目录名，例如 ZSG_day
    save_merged: bool = True,         # 是否保存合并大表
    save_each_csv: bool = False,       # 是否每个标的单独保存 CSV（通常不建议，文件太多）
    Atype: str = 'ETF' # Ashare
) -> dict:
    """
    根据传入的股票/ETF 列表拉取行情，保存为 CSV
    返回 {'merged_csv': Path, 'each_csvs': [Path, ...]}
    """
    pro = ts_api
    suffix = "day" if freq == "Daily" else "Weekly"
    
    if output_dir is None:
        output_dir = Path(__file__).parent / f"a_stock_data/{group_name}_{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    result = {"merged_csv": None, "each_csvs": []}
    all_dfs = []
    
    if Atype == 'ETF':
        api_func = pro.fund_daily
    else:
        api_func = pro.daily if freq == "Daily" else pro.weekly
    
    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] 获取 {freq} 数据: {symbol}")
        try:
            df = api_call_with_retry(
                api_func,
                pro_api_instance=pro,
                ts_code=symbol,
                start_date=start_date,
                end_date=datetime.now().strftime("%Y%m%d")
            )

            if df is not None and not df.empty:
                all_dfs.append(df.copy())
                
                if save_each_csv:
                    csv_path = output_dir / f"{freq}_prices_{symbol.replace('.', '_')}.csv"
                    df.to_csv(csv_path, index=False)
                    result["each_csvs"].append(csv_path)
                    print(f"  → 保存个股CSV: {csv_path.name}")
                    
        except Exception as e:
            print(f"  获取 {symbol} 失败: {e}")
            continue
    
    # 保存合并表（最常用）
    if save_merged and all_dfs:
        merged_df = pd.concat(all_dfs, ignore_index=True)
        merged_path = output_dir / f"{freq}_prices_all.csv"
        merged_df.to_csv(merged_path, index=False)
        result["merged_csv"] = merged_path
        print(f"合并 CSV 已保存: {merged_path}")
    
    return result

def convert_index_to_json(
    df: pd.DataFrame,
    symbol: str = "000016.SH",
    output_file: Optional[Path] = None,
    freq: str = "Daily",
) -> Dict:
    """Convert index daily data to JSON format similar to Alpha Vantage format.

    Args:
        df: DataFrame from pro.index_daily() with columns: ts_code, trade_date, close, open, high, low, pre_close, change, pct_chg, vol, amount
        symbol: Index symbol
        output_file: Output JSON file path, if None will not save to file

    Returns:
        Dict: JSON-formatted data
    """
    if df.empty:
        print("Warning: Empty DataFrame provided")
        return {}

    # Sort by trade_date in descending order (latest first)
    df = df.sort_values(by="trade_date", ascending=False).reset_index(drop=True)

    # Get the last refreshed date
    last_refreshed = df.iloc[0]["trade_date"]
    last_refreshed_formatted = f"{last_refreshed[:4]}-{last_refreshed[4:6]}-{last_refreshed[6:]}"

    # Build the JSON structure
    json_data = {
        "Meta Data": {
            "1. Information": f"{freq} Prices (open, high, low, close) and Volumes",
            "2. Symbol": symbol,
            "3. Last Refreshed": last_refreshed_formatted,
            "4. Output Size": "Compact",
            "5. Time Zone": "Asia/Shanghai",
        },
        f"Time Series ({freq})": {},
    }

    # Convert each row to the time series format
    for _, row in df.iterrows():
        trade_date = row["trade_date"]
        date_formatted = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

        json_data[f"Time Series ({freq})"][date_formatted] = {
            "1. open": f"{row['open']:.4f}",
            "2. high": f"{row['high']:.4f}",
            "3. low": f"{row['low']:.4f}",
            "4. close": f"{row['close']:.4f}",
            "5. volume": str(int(row["vol"])) if pd.notna(row["vol"]) else "0",
        }

    # Save to file if output_file is specified
    if output_file:
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)
        print(f"JSON data saved to: {output_file}")

    return json_data

# def merge_data(existing: dict, new: dict, freq: str) -> dict:
#     if not existing or f"Time Series ({freq})" not in existing:
#         return new

#     ts_key = f"Time Series ({freq})"
#     old_dates = existing[ts_key]
#     new_dates = new[ts_key]

#     # 合併：新資料覆蓋同日期（雖然正常不會），優先保留新抓到的
#     merged_dates = {**old_dates, **new_dates}

#     # 轉成 OrderedDict 並按日期**降序**排列
#     sorted_items = sorted(
#         merged_dates.items(),
#         key=lambda x: datetime.strptime(x[0], "%Y-%m-%d"),
#         reverse=True
#     )
#     merged_dates_ordered = OrderedDict(sorted_items)

#     # 建新資料結構，保留舊的 meta，但更新時間
#     result = existing.copy()
#     result[ts_key] = merged_dates_ordered

#     if merged_dates_ordered:
#         latest_date = list(merged_dates_ordered.keys())[0]
#         result["Meta Data"]["3. Last Refreshed"] = latest_date

#     return result
def merge_data(existing: dict, new: dict, freq: str) -> dict:
    """合并新旧数据，增加 key 兼容性"""
    if not existing or f"Time Series ({freq})" not in existing:
        return new
    
    ts_key = f"Time Series ({freq})"
    
    old_dates = existing.get(ts_key, {})
    new_dates = new.get(ts_key, {})          # 使用 .get() 防止 KeyError
    
    # 新数据优先覆盖旧数据
    merged_dates = {**old_dates, **new_dates}
    
    # 按日期降序排序
    sorted_items = sorted(
        merged_dates.items(),
        key=lambda x: datetime.strptime(x[0], "%Y-%m-%d"),
        reverse=True
    )
    
    merged_dates_ordered = OrderedDict(sorted_items)
    
    # 构建返回结果
    result = existing.copy()
    result[ts_key] = merged_dates_ordered
    
    if merged_dates_ordered:
        latest_date = list(merged_dates_ordered.keys())[0]
        result["Meta Data"]["3. Last Refreshed"] = latest_date
    
    return result

def load_existing_data(filepath: str): # 加载已存在的数据文件
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return None
    return None

#Convert TuShare daily DataFrame to Alpha Vantage–style JSON.
# def convert_df_to_alpha_json(df: pd.DataFrame, symbol: str, freq: str) -> dict:
#     if df is None or df.empty:
#         return {}

#     df = df.sort_values("trade_date", ascending=False).reset_index(drop=True) # 按交易日倒序（最新在前）

#     last_date = df.iloc[0]["trade_date"]

#     json_data = {
#         "Meta Data": {
#             "1. Information": f"{freq} Prices (open, high, low, close) and Volumes",
#             "2. Symbol": symbol,
#             "3. Last Refreshed": f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:]}",
#             "4. Output Size": "Full size",
#             "5. Time Zone": "Asia/Shanghai",
#         },
#         "Time Series ({freq})": {}
#     }

#     for _, r in df.iterrows():
#         d = r["trade_date"]
#         date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"

#         json_data["Time Series ({freq})"][date_str] = {
#             "1. open": f"{r['open']:.4f}",
#             "2. high": f"{r['high']:.4f}",
#             "3. low": f"{r['low']:.4f}",
#             "4. close": f"{r['close']:.4f}",
#             "5. volume": (str(int(r["vol"])) if pd.notna(r["vol"]) else "0") # 将成交量单位由“手”改为“股” (1 lot = 100 shares)
#         }
#     return json_data

def convert_df_to_alpha_json(df: pd.DataFrame, symbol: str, freq: str) -> dict:
    """Convert TuShare daily DataFrame to Alpha Vantage–style JSON."""
    if df is None or df.empty:
        return {}
    
    df = df.sort_values("trade_date", ascending=False).reset_index(drop=True)
    last_date = df.iloc[0]["trade_date"]
    
    # 关键修复：使用 f-string 生成正确的 key
    ts_key = f"Time Series ({freq})"
    
    json_data = {
        "Meta Data": {
            "1. Information": f"{freq} Prices (open, high, low, close) and Volumes",
            "2. Symbol": symbol,
            "3. Last Refreshed": f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:]}",
            "4. Output Size": "Full size",
            "5. Time Zone": "Asia/Shanghai",
        },
        ts_key: {}                                   # ← 使用变量
    }
    
    for _, r in df.iterrows():
        d = r["trade_date"]
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        json_data[ts_key][date_str] = {
            "1. open": f"{r['open']:.4f}",
            "2. high": f"{r['high']:.4f}",
            "3. low": f"{r['low']:.4f}",
            "4. close": f"{r['close']:.4f}",
            "5. volume": (str(int(r["vol"])) if pd.notna(r["vol"]) else "0")
        }
    
    return json_data

def generate_each_stockfiles_easy(ts_api, freq: str = "Daily", Atype: str = 'ETF'):
    pro = ts_api
    suffix = "day" if freq == "Daily" else "Weekly"
    output_folder = Path(f"a_stock_data/{ashare_symbols_str}_{suffix}/each_stock")
    output_folder.mkdir(parents=True, exist_ok=True)

    if Atype == 'ETF':
        api_func = pro.fund_daily
    else:
        api_func = pro.daily if freq == "Daily" else pro.weekly

    for symbol in ashare_symbols:
        print(f"Fetching {freq}: {symbol}")
        df = api_func(ts_code=symbol, start_date="20250101", end_date=datetime.now().strftime("%Y%m%d"))
        
        # 转换数据
        json_data = convert_df_to_alpha_json(df, symbol, freq)
        
        file_path = output_folder / f"{freq}_prices_{symbol}.json"
        existing = load_existing_data(str(file_path))
        merged = merge_data(existing, json_data, freq)
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=4)

# def generate_each_stockfiles(ts_api, freq: str = "Daily", Atype: str = 'Ashare'):
#     pro = ts_api
#     suffix = "day" if freq == "Daily" else "Weekly"
#     output_folder = Path(f"a_stock_data/{ashare_symbols_str}_{suffix}/each_stock")
#     output_folder.mkdir(parents=True, exist_ok=True)

#     if Atype == 'ETF':
#         api_func = pro.fund_daily
#     else:
#         api_func = pro.daily if freq == "Daily" else pro.weekly

#     today_str = datetime.now().strftime("%Y%m%d")
#     start_fetch = "20250101"  # ← 可改成更聰明的起點，例如讀舊檔最新日期+1天

#     for symbol in ashare_symbols:
#         json_path = output_folder / f"{freq}_prices_{symbol}.json"
#         print(f"處理 {symbol} → {json_path.name}")

#         # 1. 讀取舊資料（若存在）
#         existing_data = None
#         existing_latest_date = None

#         if json_path.exists():
#             try:
#                 with open(json_path, "r", encoding="utf-8") as f:
#                     existing_data = json.load(f)
#                 time_series = existing_data.get(f"Time Series ({freq})", {})
#                 if time_series:
#                     latest_key = list(time_series.keys())[0]  # 假設已降序
#                     existing_latest_date = latest_key.replace("-", "")
#                     print(f"  已存在資料，最晚日期: {latest_key}")
#             except Exception as e:
#                 print(f"  讀取舊JSON失敗，將重新全取: {e}")

#         # 2. 決定這次要抓的起點（增量優先）
#         fetch_start = start_fetch
#         if existing_latest_date and existing_latest_date > fetch_start:
#             # 從舊資料最後一天的「下一交易日」開始抓
#             fetch_start = existing_latest_date

#         # 3. 抓取新資料（可能為空）
#         print(f"  請求範圍: {fetch_start} ~ {today_str}")
#         try:
#             df_new = api_call_with_retry(
#                 api_func,
#                 pro_api_instance=pro,
#                 ts_code=symbol,
#                 start_date=fetch_start,
#                 end_date=today_str
#             )
#             if df_new is None or df_new.empty:
#                 print("  無新資料")
#                 if existing_data:
#                     continue  # 保留舊檔
#                 else:
#                     print("  完全無資料，跳過")
#                     continue

#             df_new = df_new.sort_values("trade_date", ascending=False)
#             print(f"  新抓到 {len(df_new)} 筆資料")
#         except Exception as e:
#             print(f"  抓取失敗: {e}")
#             continue

#         # 4. 轉成新格式的 dict
#         new_json = convert_df_to_alpha_json(df_new, symbol, freq)
#        #打印测试
#         # print(f"DEBUG: new_json keys = {list(new_json.keys())}")   # ← 加这行
#         # 5. 合併（核心邏輯）
#         if existing_data:
#             merged = merge_data(existing_data, new_json, freq)
#         else:
#             merged = new_json

#         # 6. 存檔
#         with open(json_path, "w", encoding="utf-8") as f:
#             json.dump(merged, f, ensure_ascii=False, indent=4)

#         print(f"  已更新 → {json_path.name}\n")
def generate_each_stockfiles(ts_api, ashare_symbols: list, ashare_symbols_str: str,
                             freq: str = "Daily", Atype: str = 'Ashare'):
    """
    生成每个股票单独的 JSON 文件（支持增量更新）
    参数说明：
        ashare_symbols: 当前组的股票列表
        ashare_symbols_str: 当前组的名称（用于文件夹命名）
    """
    pro = ts_api
    suffix = "day" if freq == "Daily" else "Weekly"
    output_folder = Path(f"a_stock_data/{ashare_symbols_str}_{suffix}/each_stock")
    output_folder.mkdir(parents=True, exist_ok=True)
    
    if Atype == 'ETF':
        api_func = pro.fund_daily
    else:
        api_func = pro.daily if freq == "Daily" else pro.weekly
    
    today_str = datetime.now().strftime("%Y%m%d")
    start_fetch = "20250101"

    print(f"开始生成 {len(ashare_symbols)} 只股票的独立 JSON 文件...")

    for symbol in ashare_symbols:
        json_path = output_folder / f"{freq}_prices_{symbol}.json"
        print(f"處理 {symbol} → {json_path.name}")
        
        try:
            # 1. 读取旧数据（如果存在）
            existing_data = None
            existing_latest_date = None
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                    time_series = existing_data.get(f"Time Series ({freq})", {})
                    if time_series:
                        latest_key = list(time_series.keys())[0]
                        existing_latest_date = latest_key.replace("-", "")
                        print(f"  已存在資料，最晚日期: {latest_key}")
                except Exception as e:
                    print(f"  读取旧JSON失败，将重新获取: {e}")

            # 2. 决定抓取起点
            fetch_start = start_fetch
            if existing_latest_date and existing_latest_date > fetch_start:
                fetch_start = existing_latest_date

            # 3. 抓取新数据
            print(f"  请求範圍: {fetch_start} ~ {today_str}")
            df_new = api_call_with_retry(
                api_func,
                pro_api_instance=pro,
                ts_code=symbol,
                start_date=fetch_start,
                end_date=today_str
            )

            if df_new is None or df_new.empty:
                print("  無新資料")
                if existing_data:
                    print("  保留旧数据")
                    continue
                else:
                    print("  完全無資料，跳过")
                    continue

            df_new = df_new.sort_values("trade_date", ascending=False)
            print(f"  新抓到 {len(df_new)} 筆資料")

            # 4. 转换为 JSON 格式
            new_json = convert_df_to_alpha_json(df_new, symbol, freq)

            # 5. 合并数据
            if existing_data:
                merged = merge_data(existing_data, new_json, freq)
            else:
                merged = new_json

            # 6. 保存文件
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=4)
            print(f"  已更新 → {json_path.name}\n")

        except Exception as e:
            print(f"  ❌ 处理 {symbol} 时发生错误: {type(e).__name__}: {e}")
            # 可选：打印详细错误堆栈
            # import traceback
            # traceback.print_exc()
            continue  # 继续处理下一只股票

def test_get_index_weight(index_code: str = "000016.SH"):
    """
    测试获取指数成分股及权重数据
    """
    # 1. 计算日期：通常权重数据按月更新，获取上个月的数据最为稳妥
    today = datetime.now()
    first_day_this_month = today.replace(day=1)
    last_day_last_month = first_day_this_month - timedelta(days=1)
    start_date = last_day_last_month.replace(day=1).strftime("%Y%m%d")
    end_date = last_day_last_month.strftime("%Y%m%d")

    print(f"--- 正在请求 {index_code} 的权重数据 ---")
    print(f"查询区间: {start_date} 至 {end_date}")

    try:
        # 2. 调用 Tushare 接口
        # index_code: 指数代码
        # start_date / end_date: 权重变化的区间
        df = pro.index_weight(
            index_code=index_code, 
            start_date=start_date, 
            end_date=end_date
        )

        if df is not None and not df.empty:
            # 3. 数据清洗：同一个月内可能有多条变动记录，通常取最后一天（最新的），修改排序逻辑：先按日期排，日期相同按权重排
            df = df.sort_values(by=["trade_date", "weight"], ascending=[False, False])
            df = df.reset_index(drop=True) # 立即重置索引，让第一列变成整齐的 0, 1, 2...
            latest_date = df.iloc[0]["trade_date"]
            df_latest = df[df["trade_date"] == latest_date]

            print(f"✅ 成功获取数据！交易日期: {latest_date}")
            print(f"成分股总数: {len(df_latest)}")
            print("\n前 50 条成分股及权重预览:")
            print(df_latest[['con_code', 'weight', 'trade_date']].head(50))
            
            # 返回提取的代码列表，这可以替代你的 
            symbols_list = df_latest["con_code"].tolist()
            return symbols_list
        else:
            print("❌ 未获取到数据，请检查接口权限或日期区间。")
            return []

    except Exception as e:
        print(f"💥 接口调用报错: {e}")
        return []

def convert_a_stock_to_jsonl(
    input_path: str = "a_stock_data/",
    freq: str = 'day',# week, day
    ashare_symbols_str: str = "sse_50",
    Atype: str = 'ETF'
) -> None:
    """Convert A-share CSV data to JSONL format compatible with the trading system.

    The output format matches the Alpha Vantage format used for NASDAQ data:
    - Each line is a JSON object for one stock
    - Contains "Meta Data" and "Time Series (Daily)" fields
    - Uses "1. buy price" (open), "2. high", "3. low", "4. sell price" (close), "5. volume"
    - Includes stock name from sse_50_weight.csv for better AI understanding

    Args:
        csv_path: Path to the A-share daily price CSV file (default: A_stock_data/daily_prices_sse_50.csv)
        output_path: Path to output JSONL file (default: A_stock_data/merged.jsonl)
        stock_name_csv: Path to SSE 50 weight CSV containing stock names (default: A_stock_data/sse_50_weight.csv)
    """

    # 1. 修复路径：必须加 f 前缀，并将 freq 映射到文件夹后缀
    suffix = "Daily" if freq == 'day' else "Weekly"
    
    # 路径根据 1.1 脚本生成的结构进行适配
    csv_path = Path(input_path) / f"{ashare_symbols_str}_{freq}" / f"{suffix}_prices_all.csv"
    stock_name_csv = Path(input_path) / f"{ashare_symbols_str}_{freq}" / "ashare_names.csv"
    output_path = Path(input_path) / f"{ashare_symbols_str}_{freq}" / "merged.jsonl"

    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        return

    print(f"Reading CSV file: {csv_path}")

    # Read CSV data
    df = pd.read_csv(csv_path)

    if Atype == 'ETF':
        index_code = "ts_code"
        index_name = "extname"
    elif Atype == 'Ashare_New':
        index_code = "ts_code"
        index_name = "name"
    else:
        index_code = "con_code"
        index_name = "stock_name"

    # Read stock name mapping
    stock_name_map = {}
    if stock_name_csv.exists():
        print(f"Reading stock names from: {stock_name_csv}")
        name_df = pd.read_csv(stock_name_csv)
        # Create mapping from con_code (ts_code) to stock_name
        stock_name_map = dict(zip(name_df[index_code], name_df[index_name]))
        print(f"Loaded {len(stock_name_map)} stock names")
    else:
        print(f"Warning: Stock name file not found: {stock_name_csv}")

    print(f"Total records: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Group by stock symbol
    grouped = df.groupby(index_code)
    print(f"Processing {len(grouped)} stocks...")

    with open(output_path, "w", encoding="utf-8") as fout:
        for index_code, group_df in grouped:
            # Sort by date ascending
            group_df = group_df.sort_values("trade_date", ascending=True)

            # Get latest date for Meta Data
            latest_date = str(group_df["trade_date"].max())
            latest_date_formatted = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"

            # Build Time Series (Daily) data
            time_series = {}

            for idx, row in group_df.iterrows():
                date_str = str(row["trade_date"])
                date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

                # For the latest date, only include buy price (to prevent future information leakage)
                if date_str == latest_date:
                    time_series[date_formatted] = {"1. buy price": str(row["open"])}
                else:
                    time_series[date_formatted] = {
                        "1. buy price": str(row["open"]),
                        "2. high": str(row["high"]),
                        "3. low": str(row["low"]),
                        "4. sell price": str(row["close"]),
                        "5. volume": (
                            str(int(row["vol"] * 100)) if pd.notna(row["vol"]) else "0"
                        ),  # Convert to shares (vol is in 手, 1手=100股)
                    }

            # Get stock name from mapping
            index_name = stock_name_map.get(index_code, "Unknown")

            # Build complete JSON object
            json_obj = {
                "Meta Data": {
                    "1. Information": f"{suffix} Prices (buy price, high, low, sell price) and Volumes",
                    "2. Symbol": index_code,
                    "2.1. Name": index_name,
                    "3. Last Refreshed": latest_date_formatted,
                    "4. Output Size": "Full Size",
                    "5. Time Zone": "Asia/Shanghai",
                },
                "Time Series (Daily)": time_series,
            }

            # Write to JSONL file
            fout.write(json.dumps(json_obj, ensure_ascii=False) + "\n")

    print(f"✅ Data conversion completed: {output_path}")
    print(f"✅ Total stocks: {len(grouped)}")
    print(f"✅ File size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")

def save_etf_basic_info(etf_list: list[str], output_path: str, pro=None, Atype = 'ETF'):
    """
    批量获取ETF基础信息并保存为CSV
    
    参数:
    etf_list    : list[str]   例如 ['159941.SZ', '510300.SH', '513050.SH']
    output_path : str         输出csv路径，例如 "etf_info.csv"
    pro         : tushare pro 对象（需提前 ts.pro_api() 初始化）
    """
    if pro is None:
        raise ValueError("请先初始化 pro = ts.pro_api() 并传入")
    
    results = []

    if Atype == 'ETF':
        pro_fun = pro.etf_basic
        cols_order = [
            'ts_code', 'csname', 'extname', 'cname', 
            'index_code', 'index_name', 'setup_date', 'list_date', 'list_status', 
            'exchange', 'mgr_name', 'custod_name', 'mgt_fee', 'etf_type'
        ] # 常用字段排序（只保留存在的列）
    elif Atype == 'Ashare_Date':
        pro_fun = pro.bak_basic
        cols_order = ['ts_code', 'trade_date', 'name', 'industry',
            'area', 'pe', 'float_share', 'total_share',
            'total_assets', 'liquid_assets', 'fixed_assets',
            'reserved', 'reserved_pershare', 'eps',
            'bvps', 'pb', 'list_date', 'undp', 'per_undp',
            'rev_yoy', 'profit_yoy', 'gpr', 'npr', 'holder_num']
    else:
        pro_fun = pro.stock_basic
        cols_order = [
            'ts_code', 'symbol', 'name', 'area', 
            'industry', 'fullname', 'enname', 'cnspell', 'market', 
            'exchange', 'curr_type', 'list_status', 'list_date', 
            'delist_date', 'is_hs', 'act_name', 'act_ent_type'
        ]
    
    print(f"开始获取 {len(etf_list)} 个股票信息...")
    
    for i, code in enumerate(etf_list, 1):
        try:
            df = pro_fun(ts_code=code)
            if not df.empty:
                results.append(df)
                print(f"[{i}/{len(etf_list)}] {code} 成功")
            else:
                print(f"[{i}/{len(etf_list)}] {code} 无数据")
        except Exception as e:
            print(f"[{i}/{len(etf_list)}] {code} 失败: {str(e)}")
    
    if not results:
        print("没有任何数据获取成功")
        return None
    
    # 合并
    df_all = pd.concat(results, ignore_index=True)
    

    available_cols = [c for c in cols_order if c in df_all.columns]
    df_all = df_all[available_cols]
    
    # 简单格式处理
    for col in ['setup_date', 'list_date']:
        if col in df_all.columns:
            df_all[col] = pd.to_datetime(df_all[col], format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
    
    if 'mgt_fee' in df_all.columns:
        df_all['mgt_fee'] = df_all['mgt_fee'].round(4)
    
    # 保存（utf-8-sig 防止中文乱码）
    output_path_file = output_path / 'ashare_names.csv'
    df_all.to_csv(output_path_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存 {len(df_all)} 条记录 → {output_path_file}")
    
    return df_all

if __name__ == "__main__":
    # ==================== 配置部分 ====================
    json_config_path = str(Path(__file__).parent / "stocks.json")
    
    # === 关键修复：正确读取整个 JSON 文件 ===
    try:
        config_file = Path(json_config_path)
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        
        if isinstance(config_data, dict) and config_data:
            group_names = list(config_data.keys())
            print(f"✅ 从 stocks.json 中成功读取到 {len(group_names)} 个组：")
            print(group_names)
        else:
            print("❌ stocks.json 格式不正确或为空")
            group_names = ["sse_50", "ETF_25", "ZSG_17"]
    except Exception as e:
        print(f"❌ 读取 stocks.json 失败: {e}")
        group_names = ["sse_50", "ETF_25", "ZSG_17"]

    print("-" * 90)

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("Error: TUSHARE_TOKEN not found")
        sys.exit(1)
    
    ts.set_token(token)
    pro = ts.pro_api()

    FREQ = "Daily"
    suffix = "day" if FREQ == "Daily" else "Weekly"
    START_DATE = "20250101"

    # ==================== 循环处理每个组 ====================
    for ashare_symbols_str in group_names:
        print(f"\n{'='*95}")
        print(f"开始处理组: {ashare_symbols_str}")

        ashare_symbols = get_config_value(
            key=ashare_symbols_str, 
            json_config_path=json_config_path
        )

        if not ashare_symbols or not isinstance(ashare_symbols, list):
            print(f"❌ 组 '{ashare_symbols_str}' 数据格式错误或为空，跳过")
            continue

        print(f"   → 共 {len(ashare_symbols)} 只标的")

        base_path = Path(__file__).parent / "A_stock_data" / f"{ashare_symbols_str}_{suffix}"
        Atype = "ETF" if any(x in ashare_symbols_str.upper() for x in ["ETF"]) else "Ashare"   # TEST也按A股处理

        # 1. 获取基准指数 JSON
        print(f"\nFetching benchmark index {FREQ} data...")
        get_benchmark_index_json(
            index_code="000016.SH",
            start_date=START_DATE,
            freq=FREQ,
            output_dir=base_path,
            ts_api=pro
        )

        # 2. 获取价格 CSV
        print(f"Fetching prices data...")
        get_custom_symbols_prices_csv(
            symbols=ashare_symbols,
            start_date=START_DATE,
            freq=FREQ,
            output_dir=base_path,
            ts_api=pro,
            group_name=ashare_symbols_str,
            Atype=Atype
        )

        # 3. 生成每个股票单独 JSON
        generate_each_stockfiles(pro, ashare_symbols, ashare_symbols_str, freq=FREQ, Atype=Atype)

        # 4. 保存名称映射
        save_etf_basic_info(ashare_symbols, base_path, pro, Atype=Atype)

        # 5. 生成 merged.jsonl
        print(f"\nGenerating merged.jsonl for {ashare_symbols_str}...")
        convert_a_stock_to_jsonl(
            freq='day',
            ashare_symbols_str=ashare_symbols_str,
            Atype="Ashare_New" if Atype == "Ashare" else "ETF"
        )

    print(f"\n{'='*95}")
    print("✅ 所有组已处理完成！")

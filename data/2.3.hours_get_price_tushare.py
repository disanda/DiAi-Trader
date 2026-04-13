import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd
import tushare as ts
from dotenv import load_dotenv
load_dotenv()

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from utils.ashare_symbol import sse_50_symbols # all_nasdaq_100_symbols

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

def get_daily_price_a_stock_60min(
    index_code: str = "000016.SH",
    output_dir: Optional[Path] = None,
    start_date: str = "2025-01-01 09:00:00",
    fallback_csv: Optional[Path] = None,
    ts_api = None,
) -> Optional[pd.DataFrame]:
    pro = ts_api
    
    # 1. 获取指数成分股名单 (逻辑不变)
    index_start_date, index_end_date = get_last_month_dates()
    try:
        print(f"正在获取指数成分股名单: {index_code}")
        df_weight = api_call_with_retry(
            pro.index_weight,
            pro_api_instance=pro,
            index_code=index_code,
            start_date=index_start_date,
            end_date=index_end_date
        )

        if df_weight.empty:
            if fallback_csv and Path(fallback_csv).exists():
                df_weight = pd.read_csv(fallback_csv)
            else:
                return None

        code_list = df_weight["con_code"].tolist()
        all_stock_data = []

        # 2. 循环获取每一只股票的 60 分钟线
        # 注意：stk_mins 必须一只一只获取
        end_dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for symbol in code_list:
            print(f"正在获取 {symbol} 的 60分钟线数据...")
            
            # 使用 stk_mins 接口
            df_min = api_call_with_retry(
                pro.stk_mins,
                pro_api_instance=pro,
                ts_code=symbol,
                start_date=start_date,
                end_date=end_dt_str,
                freq='60min' # 指定 60 分钟
            )

            if not df_min.empty:
                all_stock_data.append(df_min)
            
            # 分钟线接口流控严格，强制休眠
            time.sleep(0.2) 

        if not all_stock_data:
            return None

        # 3. 合并所有股票数据
        df_final = pd.concat(all_stock_data, ignore_index=True)

        # 4. 排序：按时间正序，按代码排序
        df_final = df_final.sort_values(by=["trade_time", "ts_code"]).reset_index(drop=True)

        # 5. 保存 CSV
        if output_dir is None:
            output_dir = Path(__file__).parent / "A_stock_data"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        index_name = "sse_50_60min"
        output_file = output_dir / f"prices_{index_name}.csv"
        df_final.to_csv(output_file, index=False, encoding="utf-8")
        
        print(f"✅ 所有成分股 60min 数据已保存至: {output_file}")
        return df_final

    except Exception as e:
        print(f"❌ 运行错误: {str(e)}")
        return None

def convert_index_daily_to_json(
    df: pd.DataFrame,
    symbol: str = "000016.SH",
    output_file: Optional[Path] = None,
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
            "1. Information": "Daily Prices (open, high, low, close) and Volumes",
            "2. Symbol": symbol,
            "3. Last Refreshed": last_refreshed_formatted,
            "4. Output Size": "Compact",
            "5. Time Zone": "Asia/Shanghai",
        },
        "Time Series (Daily)": {},
    }

    # Convert each row to the time series format
    for _, row in df.iterrows():
        trade_date = row["trade_date"]
        date_formatted = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

        json_data["Time Series (Daily)"][date_formatted] = {
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

def convert_index_60min_to_json(
    df: pd.DataFrame,
    symbol: str = "000016.SH",
    output_file: Optional[Path] = None,
) -> Dict:
    if df.empty:
        return {}

    # 1. 关键改动：按 trade_time 排序
    df = df.sort_values(by="trade_time", ascending=False).reset_index(drop=True)
    last_refreshed = str(df.iloc[0]["trade_time"])

    json_data = {
        "Meta Data": {
            "1. Information": "60-minute Prices for Index",
            "2. Symbol": symbol,
            "3. Last Refreshed": last_refreshed,
            "4. Interval": "60min",
            "5. Time Zone": "Asia/Shanghai",
        },
        "Time Series (60min)": {}, # 2. 关键改动：Key 名修改
    }

    for _, row in df.iterrows():
        # 分钟线接口返回的 trade_time 已经是 YYYY-MM-DD HH:MM:SS 格式
        time_str = str(row["trade_time"])
        json_data["Time Series (60min)"][time_str] = {
            "1. open": f"{row['open']:.4f}",
            "2. high": f"{row['high']:.4f}",
            "3. low": f"{row['low']:.4f}",
            "4. close": f"{row['close']:.4f}",
            "5. volume": str(int(row["vol"])) if pd.notna(row["vol"]) else "0",
        }

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)
    return json_data

from collections import OrderedDict
def merge_min_data(existing_data: dict, new_data: dict):
    # 将原来的 "Time Series (Daily)" 替换为动态或具体的 "Time Series (60min)"
    ts_key = "Time Series (60min)"
    
    if existing_data is None or ts_key not in existing_data:
        return new_data
    
    existing_times = existing_data[ts_key]
    new_times = new_data[ts_key]
    
    merged_times = existing_times.copy()
    for time_key in new_times:
        if time_key not in merged_times:
            merged_times[time_key] = new_times[time_key]
    
    # 按时间字符串排序（降序）
    sorted_times = OrderedDict(sorted(merged_times.items(), key=lambda x: x[0], reverse=True))
    
    merged_data = existing_data.copy()
    merged_data[ts_key] = sorted_times
    merged_data["Meta Data"]["3. Last Refreshed"] = list(sorted_times.keys())[0]
    
    return merged_data

def load_existing_data(filepath: str): # 加载已存在的数据文件
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return None
    return None

#Convert TuShare daily DataFrame to Alpha Vantage–style JSON.
def convert_daily_60min_df_to_alpha_json(df: pd.DataFrame, symbol: str) -> dict:
    if df is None or df.empty:
        return {}

    #df = df.sort_values("trade_date", ascending=False).reset_index(drop=True) # 按交易日倒序（最新在前）
    #last_date = df.iloc[0]["trade_date"]

    df = df.sort_values("trade_time", ascending=False).reset_index(drop=True) # 按交易时间倒序排列
    last_time = df.iloc[0]["trade_time"] # 获取最后更新时间, 格式通常为 "2023-08-25 15:00:00"

    json_data = {
        "Meta Data": {
            "1. Information": "60-minute Prices (open, high, low, close) and Volumes",
            "2. Symbol": symbol,
            "3. Last Refreshed": last_time,
            "4. Interval": "60min",
            "5. Time Zone": "Asia/Shanghai",
        },
        "Time Series (60min)": {}
    }

    for _, r in df.iterrows():
        time_str = str(r["trade_time"]) #直接使用 trade_time 作为 key
        json_data["Time Series (60min)"][time_str] = {
            "1. open": f"{r['open']:.4f}",
            "2. high": f"{r['high']:.4f}",
            "3. low": f"{r['low']:.4f}",
            "4. close": f"{r['close']:.4f}",
            "5. volume": (str(int(r["vol"])) if pd.notna(r["vol"]) else "0") # 将成交量单位由“手”改为“股” (1 lot = 100 shares)
        }
    return json_data

def generate_each_stockfiles_60min(ts_api,start_dt, end_dt = None):
    pro = ts_api
    output_file = "a_stock_data/sse_50_hour/each_stock" 
    os.makedirs(output_file, exist_ok=True) # 生成各股文件及文件夹

    # 设定开始和结束日期 (stk_mins 支持标准日期格式)
    if end_dt == None:
        end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for symbol in sse_50_symbols:
        print(f"Fetching 60min data for {symbol}")

        try:
            df = pro.stk_mins(ts_code=symbol, start_date=start_dt, end_date=end_dt)
            if df is None or df.empty:
                print(f"No data for {symbol}")
                continue

            json_data = convert_daily_60min_df_to_alpha_json(df, symbol)
            output_file_subfile = output_file + f"/daily_60mins_prices_{symbol}.json"

            # 加载并合并
            existing = load_existing_data(output_file_subfile)

            # 注意：这里需要确保你的 merge_data 函数能处理 "Time Series (60min)" 这个 key
            merged = merge_min_data(existing, json_data)

            with open(output_file_subfile, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=4)

            time.sleep(0.5) # 分钟数据接口通常流控较严，增加延迟

        except Exception as e:
            print(f"Error fetching {symbol}: {e}")

if __name__ == "__main__":

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("Error: TUSHARE_TOKEN not found")
    ts.set_token(token)
    pro = ts.pro_api()

    daily_60min_start_date = "2025-01-01 09:00:00"

    fallback_path = Path(__file__).parent / "A_stock_data" / "sse_50_weight.csv"

    # Get constituent stocks daily prices, 获取指数数据，保存为csv
    df = get_daily_price_a_stock_60min(index_code="000016.SH", start_date=daily_60min_start_date, fallback_csv=fallback_path, ts_api = pro)

    # Get index daily data and convert to JSON，获取指数数据，保存为json
    print("\n" + "=" * 50)
    print("Fetching index daily data...")
    print("=" * 50)
    df_index = convert_index_60min_to_json(index_code="000016.SH", start_date=daily_60min_start_date, ts_api = pro)

    generate_each_stockfiles_60min(pro)


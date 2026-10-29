import os

from dotenv import load_dotenv
load_dotenv()
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from agent.general_tools import get_config_value
from agent.market_data import available_dates, get_record, name_mapping

# 运行时变量， "model_data_path": "./data/agent_data_astock/sse_50_hour"
#model_data_path = get_config_value("MODEL_DATA_PATH", "./data/agent_data_astock/sse_50_day") 
#Ashare_data_path = get_config_value("Ashare_DATA_PATH", "./data/agent_data_astock/sse_50_day/merged.jsonl") 

def _normalize_timestamp_str(ts: str) -> str:
    """
    Normalize timestamp string to zero-padded HH for robust string/chrono comparisons.
    - If ts has time part like 'YYYY-MM-DD H:MM:SS', pad hour to 'HH'.
    - If ts is date-only, return as-is.
    """
    try:
        if " " not in ts:
            return ts
        date_part, time_part = ts.split(" ", 1)
        parts = time_part.split(":")
        if len(parts) != 3:
            return ts
        hour, minute, second = parts
        hour = hour.zfill(2)
        return f"{date_part} {hour}:{minute}:{second}"
    except Exception:
        return ts

def _parse_timestamp_to_dt(ts: str) -> datetime:
    """
    Parse timestamp string to datetime, supporting both date-only and datetime.
    Assumes ts is already normalized if time exists.
    """
    if " " in ts:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    return datetime.strptime(ts, "%Y-%m-%d")

def get_market_type() -> str:
    return "cn"

def is_trading_day(date: str, market: str = "cn") -> bool:
    """
    Check if a given date is a trading day by looking up merged.jsonl.

    Args:
        date: Date string in "YYYY-MM-DD" format
        market: Market type ("us", "cn", or "crypto")

    Returns:
        True if the date exists in merged.jsonl (is a trading day), False otherwise
    """

    canonical_dates = available_dates(market)
    if canonical_dates:
        return date[:10] in canonical_dates

    merged_file_path = get_config_value("Ashare_DATA_PATH", "./data/Astocks")
    merged_file_path = Path(merged_file_path)
    if not merged_file_path.exists():
        print(f"⚠️  Warning: {merged_file_path} not found, cannot validate trading day")
        return False

    try:
        with open(merged_file_path, "r", encoding="utf-8") as f:
            # Read first line to check if date exists
            for line in f:
                try:
                    data = json.loads(line.strip())
                    # Check for daily time series first
                    time_series = data.get("Time Series (Daily)", {})
                    if date in time_series:
                        return True

                    # If no daily data, check for hourly data (e.g., "Time Series (60min)")
                    for key, value in data.items():
                        if key.startswith("Time Series") and isinstance(value, dict):
                            # Check if any hourly timestamp starts with the date
                            for timestamp in value.keys():
                                if timestamp.startswith(date):
                                    return True
                except json.JSONDecodeError:
                    continue
            # If we get here, checked all stocks and date was not found in any
            return False
    except Exception as e:
        print(f"⚠️  Error checking trading day: {e}")
        return False

def get_all_trading_days(market: str = "cn") -> List[str]:
    """
    Get all available trading days from merged.jsonl.

    Args:
        market: Market type ("us" or "cn")

    Returns:
        Sorted list of trading dates in "YYYY-MM-DD" format
    """

    canonical_dates = available_dates(market)
    if canonical_dates:
        return canonical_dates

    merged_file_path = get_config_value("Ashare_DATA_PATH", "./data/Astocks")
    merged_file_path = Path(merged_file_path)
    if not merged_file_path.exists():
        print(f"⚠️  Warning: {merged_file_path} not found")
        return []

    trading_days = set()
    try:
        with open(merged_file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    time_series = data.get("Time Series (Daily)", {})
                    # Add all dates from this stock's time series
                    trading_days.update(time_series.keys())
                except json.JSONDecodeError:
                    continue
        return sorted(list(trading_days))
    except Exception as e:
        print(f"⚠️  Error reading trading days: {e}")
        return []


def get_stock_name_mapping(market: str = "cn") -> Dict[str, str]:
    """
    Get mapping from stock symbols to names.

    Args:
        market: Market type ("us" or "cn")

    Returns:
        Dictionary mapping symbols to names, e.g. {"600519.SH": "贵州茅台"}
    """

    canonical_names = name_mapping(market)
    if canonical_names:
        return canonical_names

    merged_file_path = get_config_value("Ashare_DATA_PATH", "./data/Astocks")
    merged_file_path = Path(merged_file_path)
    if not merged_file_path.exists():
        return {}

    name_map = {}
    try:
        with open(merged_file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    meta = data.get("Meta Data", {})
                    symbol = meta.get("2. Symbol")
                    name = meta.get("2.1. Name", "")
                    if symbol and name:
                        name_map[symbol] = name
                except json.JSONDecodeError:
                    continue
        return name_map
    except Exception as e:
        print(f"⚠️  Error reading stock names: {e}")
        return {}


def format_price_dict_with_names(price_dict: Dict[str, Optional[float]], market: str = "cn") -> Dict[str, Optional[float]]:
    """
    Format price dictionary to include stock names for display.

    Args:
        price_dict: Original price dictionary with keys like "600519.SH_price"
        market: Market type ("us" or "cn")

    Returns:
        New dictionary with keys like "600519.SH (贵州茅台)_price" for CN market,
        unchanged for US market
    """
    if market != "cn":
        return price_dict

    name_map = get_stock_name_mapping(market)
    if not name_map:
        return price_dict

    formatted_dict = {}
    for key, value in price_dict.items():
        if key.endswith("_price"):
            symbol = key[:-6]  # Remove "_price" suffix
            stock_name = name_map.get(symbol, "")
            if stock_name:
                new_key = f"{symbol} ({stock_name})_price"
            else:
                new_key = key
            formatted_dict[new_key] = value
        else:
            formatted_dict[key] = value

    return formatted_dict


def get_yesterday_date(today_date: str, merged_path: Optional[str] = None, market: str = "cn") -> str:
    """
    获取输入日期的上一个交易日或时间点。
    从 merged.jsonl 读取所有可用的交易时间，然后找到 today_date 的上一个时间。
    
    Args:
        today_date: 日期字符串，格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS。
        merged_path: 可选，自定义 merged.jsonl 路径；默认根据 market 参数读取对应市场的 merged.jsonl。
        market: 市场类型，"us" 为美股，"cn" 为A股

    Returns:
        yesterday_date: 上一个交易日或时间点的字符串，格式与输入一致。
    """
    # 解析输入日期/时间
    if ' ' in today_date:
        input_dt = datetime.strptime(today_date, "%Y-%m-%d %H:%M:%S")
        date_only = False
    else:
        input_dt = datetime.strptime(today_date, "%Y-%m-%d")
        date_only = True
    
    if date_only:
        earlier = [value for value in available_dates(market) if value < today_date[:10]]
        if earlier:
            return earlier[-1]

    # Hourly simulations can still use an explicitly configured legacy JSONL file.
    merged_file_path = get_config_value("Ashare_DATA_PATH", "./data/Astocks")
    merged_file_path = Path(merged_file_path)
    if not merged_file_path.exists():
        # 如果文件不存在，根据输入类型回退
        print(f"merged.jsonl file does not exist at {merged_file_path}")
        if date_only:
            yesterday_dt = input_dt - timedelta(days=1)
            while yesterday_dt.weekday() >= 5:
                yesterday_dt -= timedelta(days=1)
            return yesterday_dt.strftime("%Y-%m-%d")
        else:
            yesterday_dt = input_dt - timedelta(hours=1)
            return yesterday_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # 从 merged.jsonl 读取所有可用的交易时间
    all_timestamps = set()
    
    with merged_file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                # 查找所有以 "Time Series" 开头的键
                for key, value in doc.items():
                    if key.startswith("Time Series"):
                        if isinstance(value, dict):
                            all_timestamps.update(value.keys())
                        break
            except Exception:
                continue
    
    if not all_timestamps:
        # 如果没有找到任何时间戳，根据输入类型回退
        if date_only:
            yesterday_dt = input_dt - timedelta(days=1)
            while yesterday_dt.weekday() >= 5:
                yesterday_dt -= timedelta(days=1)
            return yesterday_dt.strftime("%Y-%m-%d")
        else:
            yesterday_dt = input_dt - timedelta(hours=1)
            return yesterday_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # 将所有时间戳转换为 datetime 对象，并找到小于 today_date 的最大时间戳
    previous_timestamp = None
    
    for ts_str in all_timestamps:
        try:
            ts_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            if ts_dt < input_dt:
                if previous_timestamp is None or ts_dt > previous_timestamp:
                    previous_timestamp = ts_dt
        except Exception:
            continue
    
    # 如果没有找到更早的时间戳，根据输入类型回退
    if previous_timestamp is None:
        if date_only:
            yesterday_dt = input_dt - timedelta(days=1)
            while yesterday_dt.weekday() >= 5:
                yesterday_dt -= timedelta(days=1)
            return yesterday_dt.strftime("%Y-%m-%d")
        else:
            yesterday_dt = input_dt - timedelta(hours=1)
            return yesterday_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 返回结果
    if date_only:
        return previous_timestamp.strftime("%Y-%m-%d")
    else:
        return previous_timestamp.strftime("%Y-%m-%d %H:%M:%S")

def get_open_prices(
    today_date: str,
    symbols: List[str],
    merged_path: Optional[str] = None,
    market: str = "cn",
) -> Dict[str, Optional[float]]:
    """
    从 merged.jsonl 中读取指定日期 / 时间点的开盘价
    自动适配 Daily / 60min 数据

    返回：
        { "{symbol}_price": float | None }
    """
    wanted = set(symbols)
    results: Dict[str, Optional[float]] = {f"{s}_price": None for s in symbols}

    if len(today_date.strip()) <= 10:
        for symbol in symbols:
            row = get_record(symbol, today_date, market)
            if row:
                value = row.get("open")
                try:
                    results[f"{symbol}_price"] = float(value) if value is not None else None
                except (TypeError, ValueError):
                    pass
        return results

    merged_file_path = get_config_value(
        "Ashare_DATA_PATH",
        "./data/Astocks",
    )
    merged_file_path = Path(merged_file_path)
    print(merged_file_path)

    if not merged_file_path.exists():
        return results

    # ---- 解析 today_date ----
    date_str = today_date.strip()
    is_hour_request = len(date_str) > 10  # 是否带时间

    day_part = date_str[:10]  # YYYY-MM-DD
    minute_part = date_str[:16] if is_hour_request else None  # YYYY-MM-DD HH:MM

    with merged_file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except Exception:
                continue

            meta = doc.get("Meta Data", {})
            sym = meta.get("2. Symbol")
            if sym not in wanted:
                continue

            # ---- 判断频率 ----
            if "Time Series (60min)" in doc:
                series = doc["Time Series (60min)"]
                freq = "hour"
            elif "Time Series (Daily)" in doc:
                series = doc["Time Series (Daily)"]
                freq = "daily"
            else:
                continue

            bar = None

            # ---- Hour 数据处理 ----
            if freq == "hour":
                if is_hour_request:
                    # 精确匹配
                    bar = series.get(date_str)

                    # 去掉秒再匹配
                    if bar is None and minute_part:
                        bar = next(
                            (series[k] for k in series if k.startswith(minute_part)),
                            None,
                        )

                    # 回退：当天最近一根 bar
                    if bar is None:
                        candidates = sorted(
                            k for k in series.keys() if k.startswith(day_part)
                        )
                        if candidates:
                            bar = series[candidates[-1]]

                else:
                    # 只给了日期，取当天最后一根
                    candidates = sorted(
                        k for k in series.keys() if k.startswith(day_part)
                    )
                    if candidates:
                        bar = series[candidates[-1]]

            # ---- Daily 数据处理 ----
            elif freq == "daily":
                # 有时间也自动截断
                bar = series.get(day_part)

            # ---- 提取价格 ----
            if isinstance(bar, dict):
                val = (
                    bar.get("1. buy price")
                    or bar.get("1. open")
                    or bar.get("1. Open")
                )
                try:
                    results[f"{sym}_price"] = float(val) if val is not None else None
                except Exception:
                    results[f"{sym}_price"] = None

    return results

def get_trade_price(today_date, symbol, market, mode="daily"):
    if mode == "daily":
        return get_open_prices(today_date[:10], [symbol], market)[f"{symbol}_price"]
    else:
        return get_open_prices(today_date, [symbol], market)[f"{symbol}_price"]

def get_yesterday_open_and_close_price(
    today_date: str, symbols: List[str], merged_path: Optional[str] = None, market: str = "cn"
) -> Tuple[Dict[str, Optional[float]], Dict[str, Optional[float]]]:
    """
    从 data/merged.jsonl 中读取指定日期与股票的昨日买入价和卖出价。

    Args:
        today_date: 日期字符串，格式 YYYY-MM-DD，代表今天日期。
        symbols: 需要查询的股票代码列表。
        merged_path: 可选，自定义 merged.jsonl 路径；默认读取项目根目录下 data/merged.jsonl。
        market: 市场类型，"us" 为美股，"cn" 为A股

    Returns:
        (买入价字典, 卖出价字典) 的元组；若未找到对应日期或标的，则值为 None。
    """
    wanted = set(symbols)
    buy_results: Dict[str, Optional[float]] = {}
    sell_results: Dict[str, Optional[float]] = {}

    yesterday_date = get_yesterday_date(today_date, merged_path=merged_path, market=market)

    if len(today_date.strip()) <= 10:
        for symbol in symbols:
            row = get_record(symbol, yesterday_date, market)
            buy_results[f'{symbol}_price'] = None
            sell_results[f'{symbol}_price'] = None
            if not row:
                continue
            try:
                buy = row.get('open')
                close = row.get('close')
                buy_results[f'{symbol}_price'] = float(buy) if buy is not None else None
                sell_results[f'{symbol}_price'] = float(close) if close is not None else None
            except (TypeError, ValueError):
                pass
        return buy_results, sell_results

    merged_file_path = Path(get_config_value("Ashare_DATA_PATH", "./data/Astocks"))
    if not merged_file_path.is_file():
        return buy_results, sell_results

    with merged_file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except Exception:
                continue
            meta = doc.get("Meta Data", {}) if isinstance(doc, dict) else {}
            sym = meta.get("2. Symbol")
            if sym not in wanted:
                continue
            # 查找所有以 "Time Series" 开头的键
            series = None
            for key, value in doc.items():
                if key.startswith("Time Series"):
                    series = value
                    break
            if not isinstance(series, dict):
                continue

            # 尝试获取昨日买入价和卖出价
            bar = series.get(yesterday_date)
            if isinstance(bar, dict):
                buy_val = bar.get("1. buy price")  # 买入价字段
                sell_val = bar.get("4. sell price")  # 卖出价字段

                try:
                    buy_price = float(buy_val) if buy_val is not None else None
                    sell_price = float(sell_val) if sell_val is not None else None
                    buy_results[f"{sym}_price"] = buy_price
                    sell_results[f"{sym}_price"] = sell_price
                except Exception:
                    buy_results[f"{sym}_price"] = None
                    sell_results[f"{sym}_price"] = None
            else:
                # 如果昨日没有数据，尝试向前查找最近的交易日
                # raise ValueError(f"No data found for {sym} on {yesterday_date}")
                # print(f"No data found for {sym} on {yesterday_date}")
                buy_results[f'{sym}_price'] = None
                sell_results[f'{sym}_price'] = None
                # today_dt = datetime.strptime(today_date, "%Y-%m-%d")
                # yesterday_dt = today_dt - timedelta(days=1)
                # current_date = yesterday_dt
                # found_data = False
                
                # # 最多向前查找5个交易日
                # for _ in range(5):
                #     current_date -= timedelta(days=1)
                #     # 跳过周末
                #     while current_date.weekday() >= 5:
                #         current_date -= timedelta(days=1)
                    
                #     check_date = current_date.strftime("%Y-%m-%d")
                #     bar = series.get(check_date)
                #     if isinstance(bar, dict):
                #         buy_val = bar.get("1. buy price")
                #         sell_val = bar.get("4. sell price")
                        
                #         try:
                #             buy_price = float(buy_val) if buy_val is not None else None
                #             sell_price = float(sell_val) if sell_val is not None else None
                #             buy_results[f'{sym}_price'] = buy_price
                #             sell_results[f'{sym}_price'] = sell_price
                #             found_data = True
                #             break
                #         except Exception:
                #             continue
                
                # if not found_data:
                #     buy_results[f'{sym}_price'] = None
                #     sell_results[f'{sym}_price'] = None

    return buy_results, sell_results


def get_yesterday_profit(
    today_date: str,
    yesterday_buy_prices: Dict[str, Optional[float]],
    yesterday_sell_prices: Dict[str, Optional[float]],
    yesterday_init_position: Dict[str, float],
    stock_symbols: Optional[List[str]] = None,
) -> Dict[str, float]:
    """
    获取持仓收益（适用于日线和小时级交易）
    
    收益计算方式为：(前一时间点收盘价 - 前一时间点开盘价) × 当前持仓数量
    
    对于日线交易：计算昨日的收益
    对于小时级交易：计算上一小时的收益
    
    Args:
        today_date: 日期/时间字符串，格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS
        yesterday_buy_prices: 前一时间点开盘价格字典，格式为 {symbol_price: price}
        yesterday_sell_prices: 前一时间点收盘价格字典，格式为 {symbol_price: price}
        yesterday_init_position: 前一时间点初始持仓字典，格式为 {symbol: quantity}
        stock_symbols: 股票代码列表，默认为 all_nasdaq_100_symbols

    Returns:
        {symbol: profit} 的字典；若未找到对应日期或标的，则值为 0.0。
    """
    profit_dict = {}

    # 使用传入的股票列表或默认的纳斯达克100列表
    if stock_symbols is None:
        stock_symbols = all_nasdaq_100_symbols

    # 遍历所有股票代码
    for symbol in stock_symbols:
        symbol_price_key = f"{symbol}_price"

        # 获取昨日开盘价和收盘价
        buy_price = yesterday_buy_prices.get(symbol_price_key)
        sell_price = yesterday_sell_prices.get(symbol_price_key)

        # 获取昨日持仓权重
        position_weight = yesterday_init_position.get(symbol, 0.0)

        # 计算收益：(收盘价 - 开盘价) * 持仓权重
        if buy_price is not None and sell_price is not None and position_weight > 0:
            profit = (sell_price - buy_price) * position_weight
            profit_dict[symbol] = round(profit, 4)  # 保留4位小数
        else:
            profit_dict[symbol] = 0.0

    return profit_dict

def get_today_init_position(today_date: str, signature: str) -> Dict[str, float]:
    """
    获取今日开盘时的初始持仓（即文件中上一个交易日代表的持仓）。从../data/agent_data/{signature}/position/position.jsonl中读取。
    如果同一日期有多条记录，选择id最大的记录作为初始持仓。

    Args:
        today_date: 日期字符串，格式 YYYY-MM-DD，代表今天日期。
        signature: 模型名称，用于构建文件路径。

    Returns:
        {symbol: weight} 的字典；若未找到对应日期，则返回空字典。
    """
    MODEL_DATA_PATH = get_config_value("MODEL_DATA_PATH", "./data/agent_data_astock/sse_50_day")
    position_file = Path(MODEL_DATA_PATH) / signature / "position" / "position.jsonl"

    position_file = Path(position_file)
    if not position_file.exists():
        print(f"Position file {position_file} does not exist")
        return {}
    
    # 获取市场类型，智能判断
    market = get_market_type()
    yesterday_date = get_yesterday_date(today_date, market=market)
    
    max_id = -1
    latest_positions = {}
    all_records = []
  
    with position_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                record_date = doc.get("date")
                if record_date and record_date < today_date:
                    all_records.append(doc)
            except Exception:
                continue

    if not all_records:
        return {}

    # Sort by date (descending) then by id (descending) to get the most recent record
    all_records.sort(key=lambda x: (x.get("date", ""), x.get("id", 0)), reverse=True)

    return all_records[0].get("positions", {})


def get_latest_position(today_date: str, signature: str) -> Tuple[Dict[str, float], int]:
    """
    获取最新持仓。从 ../data/agent_data/{signature}/position/position.jsonl 中读取。
    优先选择当天 (today_date) 中 id 最大的记录；
    若当天无记录，则回退到上一个交易日，选择该日中 id 最大的记录。

    Args:
        today_date: 日期字符串，格式 YYYY-MM-DD，代表今天日期。
        signature: 模型名称，用于构建文件路径。

    Returns:
        (positions, max_id):
          - positions: {symbol: weight} 的字典；若未找到任何记录，则为空字典。
          - max_id: 选中记录的最大 id；若未找到任何记录，则为 -1.
    """

    base_dir = Path(__file__).resolve().parents[1]

    # Get log_path from config, default to "agent_data" for backward compatibility
    MODEL_DATA_PATH = get_config_value("MODEL_DATA_PATH", "./data/agent_data_astock/sse_50_day")

    # Handle different path formats:
    # - If it's an absolute path (like temp directory), use it directly
    # - If it's a relative path starting with "./data/", remove the prefix and prepend base_dir/data
    # - Otherwise, treat as relative to base_dir/data
    position_file = Path(MODEL_DATA_PATH) / signature / "position" / "position.jsonl"
    if not position_file.exists():
        return {}, -1

    # 获取市场类型，智能判断
    market = get_market_type()
    
    # Step 1: 先查找当天的记录
    max_id_today = -1
    latest_positions_today: Dict[str, float] = {}
    
    with position_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                if doc.get("date") == today_date:
                    current_id = doc.get("id", -1)
                    if current_id > max_id_today:
                        max_id_today = current_id
                        latest_positions_today = doc.get("positions", {})
            except Exception:
                continue
    
    # 如果当天有记录，直接返回
    if max_id_today >= 0 and latest_positions_today:
        return latest_positions_today, max_id_today
    
    # Step 2: 当天没有记录，则回退到上一个交易日
    prev_date = get_yesterday_date(today_date, market=market)
    
    max_id_prev = -1
    latest_positions_prev: Dict[str, float] = {}

    with position_file.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                if doc.get("date") == prev_date:
                    current_id = doc.get("id", -1)
                    if current_id > max_id_prev:
                        max_id_prev = current_id
                        latest_positions_prev = doc.get("positions", {})
            except Exception:
                continue
    
    # 如果前一天也没有记录，尝试找文件中最新的非空记录（按实际时间和id排序）
    if max_id_prev < 0 or not latest_positions_prev:
        all_records: List[Dict[str, Any]] = []
        norm_today = _normalize_timestamp_str(today_date)
        today_dt = _parse_timestamp_to_dt(norm_today)
        with position_file.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    doc = json.loads(line)
                    doc_date = doc.get("date")
                    if not doc_date:
                        continue
                    norm_doc_date = _normalize_timestamp_str(doc_date)
                    doc_dt = _parse_timestamp_to_dt(norm_doc_date)
                    # 仅考虑早于today_date的记录
                    if doc_dt < today_dt:
                        positions = doc.get("positions", {})
                        # 跳过空持仓记录
                        if positions:
                            all_records.append(doc)
                except Exception:
                    continue
        
        if all_records:
            # 先按实际时间排序，再按id排序，取最新的一条
            all_records.sort(
                key=lambda x: (
                    _parse_timestamp_to_dt(_normalize_timestamp_str(x.get("date", "1900-01-01"))),
                    x.get("id", 0),
                ),
                reverse=True,
            )
            latest_positions_prev = all_records[0].get("positions", {})
            max_id_prev = all_records[0].get("id", -1)
    
    return latest_positions_prev, max_id_prev

def add_no_trade_record(today_date: str, signature: str):
    """
    添加不交易记录
    从 ../data/agent_data/{signature}/position/position.jsonl 中前一日最后一条持仓，并更新在今日的position.jsonl文件中。
    Args:
        today_date: 日期字符串，格式 YYYY-MM-DD，代表今天日期。
        signature: 模型名称，用于构建文件路径。

    Returns:
        None
    """
    save_item = {}
    current_position, current_action_id = get_latest_position(today_date, signature)
    
    save_item["date"] = today_date
    save_item["id"] = current_action_id + 1
    save_item["this_action"] = {"action": "no_trade", "symbol": "", "amount": 0}
    save_item["positions"] = current_position

    base_dir = Path(__file__).resolve().parents[1]

    # Get log_path from config, default to "agent_data" for backward compatibility
    log_path = get_config_value("LOG_PATH", "./data/agent_data")

    # Handle different path formats:
    # - If it's an absolute path (like temp directory), use it directly
    # - If it's a relative path starting with "./data/", remove the prefix and prepend base_dir/data
    # - Otherwise, treat as relative to base_dir/data
 
    MODEL_DATA_PATH = get_config_value("MODEL_DATA_PATH", "./data/agent_data_astock/sse_50_day")
    position_file = Path(MODEL_DATA_PATH) / signature / "position" / "position.jsonl"
    with position_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(save_item) + "\n")
    return

if __name__ == "__main__":
    today_date = get_config_value("TODAY_DATE")
    signature = get_config_value("SIGNATURE")
    if signature is None:
        raise ValueError("SIGNATURE environment variable is not set")
    print(today_date, signature)
    yesterday_date = get_yesterday_date(today_date)
    print(yesterday_date)
    a = get_open_prices(today_date="2025-11-17 11:30:00", symbols=["600028.SH", "600030.SH"])# 必须用中括号包裹
    print(a)
    # today_buy_price = get_open_prices(today_date, all_nasdaq_100_symbols)
    # print(today_buy_price)
    # yesterday_buy_prices, yesterday_sell_prices = get_yesterday_open_and_close_price(today_date, all_nasdaq_100_symbols)
    # print(yesterday_sell_prices)
    # today_init_position = get_today_init_position(today_date, signature='qwen3-max')
    # print(today_init_position)
    # latest_position, latest_action_id = get_latest_position('2025-10-24', 'qwen3-max')
    # print(latest_position, latest_action_id)
    latest_position, latest_action_id = get_latest_position('2025-09-01 10:30:00', 'glm-4.5-air')
    print(latest_position, latest_action_id)
    
    # yesterday_profit = get_yesterday_profit(today_date, yesterday_buy_prices, yesterday_sell_prices, today_init_position)
    # # print(yesterday_profit)
    # add_no_trade_record(today_date, signature)

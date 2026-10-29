import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()
mcp = FastMCP("LocalPrices")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from agent.general_tools import get_config_value
from agent.market_data import get_record, load_symbol

# 运行时变量， "model_data_path": "./data/agent_data_astock/sse_50_hour"
#model_data_path = get_config_value("MODEL_DATA_PATH", "./data/agent_data_astock/sse_50_day") 
#merged_file_path = get_config_value("Ashare_DATA_PATH", "./data/agent_data_astock/sse_50_day/merged.jsonl")

def _validate_date_daily(date_str: str) -> None:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("date must be in YYYY-MM-DD format") from exc

def _validate_date_hourly(date_str: str) -> None:
    try:
        datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("date must be in YYYY-MM-DD HH:MM:SS format") from exc

@mcp.tool()
def get_trading_journal(date: str) -> Dict[str, Any]:
    """
    Retrieve the trading journal content for a specific date.

    This function reads the Markdown journal file for the given date from the configured path.
    The journal contains trading reviews, strategies, and summaries.

    Args:
        date: Date in 'YYYY-MM-DD' format. REQUIRED.

    Returns:
        Dictionary containing the date and journal content if found,
        or an error message if the file does not exist or cannot be read.

    Example usage:
        get_trading_journal(date="2025-12-24")
    """
    try:
        _validate_date_daily(date)
    except ValueError as e:
        return {"error": str(e), "date": date}

    signature = get_config_value("SIGNATURE")
    if not signature:
        return {"error": "SIGNATURE not configured", "date": date}

    model_data_path = get_config_value("MODEL_DATA_PATH", "./data/agent_data_astock/sse_50_day")
    journal_dir = Path(model_data_path) / signature / "daily_journals"
    date_str = date.replace("-", "")
    journal_path = journal_dir / f"journal_{date_str}.md"

    if not journal_path.exists():
        return {
            "error": f"Journal file not found for date {date}",
            "path": str(journal_path),
            "date": date,
        }
    try:
        content = journal_path.read_text(encoding="utf-8")
        return {
            "date": date,
            "journal_content": content,
        }
    except Exception as e:
        return {
            "error": f"Failed to read journal file: {str(e)}",
            "path": str(journal_path),
            "date": date,
        }

@mcp.tool()
def get_price_local(symbol: str, date: str) -> Dict[str, Any]:
    """
    Read OHLCV data for specified stock and date. Get historical information for specified stock.
    
    Automatically detects date format and calls appropriate function:
    - Daily data: YYYY-MM-DD format (e.g., '2025-10-30')
    - Hourly data: YYYY-MM-DD HH:MM:SS format (e.g., '2025-10-30 14:30:00')

    Args:
        symbol: Stock symbol, e.g. 'IBM' or '600519.SH'. REQUIRED.
        date: Date in 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' format. 
              If not provided, uses TODAY_DATE from config. REQUIRED.

    Returns:
        Dictionary containing symbol, date and ohlcv data.
        
    Example usage:
        get_price_local(symbol="600519.SH", date="2025-10-30")
        get_price_local(symbol="600519.SH", date="2025-10-30 14:30:00")
    """

    # ⭐ 如果没有提供date，尝试从配置获取
    if date is None:
        date = get_config_value("TODAY_DATE", None)
        if date is None:
            return {
                "error": "date parameter is required. Please provide date in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format.",
                "symbol": symbol,
                "hint": "You must specify the date parameter explicitly."
            }
        print(f"📅 Using TODAY_DATE from config: {date}")
    
    # ⭐ 参数验证
    if not symbol:
        return {
            "error": "symbol parameter is required and cannot be empty",
            "provided_symbol": symbol
        }

    # Detect date format
    result = None
    if ' ' in date or 'T' in date:
        # Contains time component, use hourly
        result =  get_price_local_hourly(symbol, date)
    else:
        # Date only, use daily
        result = get_price_local_daily(symbol, date)
    
    # log_file = get_config_value("LOG_FILE")
    # signature = get_config_value("SIGNATURE")
    
    # log_entry = {
    #     "signature": signature,
    #     "new_messages": [{"role": "tool:get_price_local", "content": result}]
    # }
    # with open(log_file, "a", encoding="utf-8") as f:
    #     f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    return result

def get_price_local_daily(symbol: str, date: str) -> Dict[str, Any]:
    """
    Read OHLCV data for specified stock and date. Get historical information for specified stock.

    Args:
        symbol: Stock symbol, e.g. 'IBM' or '600243.SHH'.
        date: Date in 'YYYY-MM-DD' format.

    Returns:
        Dictionary containing symbol, date and ohlcv data.
    """

    try:
        _validate_date_daily(date)
    except Exception as e:
        return {"error": str(e), "symbol": symbol, "date": date}

    row = get_record(symbol, date)
    if row is not None:
        return {
            "symbol": symbol, "date": date,
            "ohlcv": {
                "open": row.get("open"), "high": row.get("high"),
                "low": row.get("low"), "close": row.get("close"),
                "volume": row.get("vol", row.get("volume")),
            },
        }
    payload = load_symbol(symbol)
    if payload is not None:
        dates = [str(item.get("trade_date") or item.get("date")) for item in payload.get("records") or []]
        return {"error": f"Data not found for date {date}. Sample available dates: {sorted(dates, reverse=True)[:5]}", "symbol": symbol, "date": date}

    data_path = Path(get_config_value("Ashare_DATA_PATH", "./data/Astocks"))
    if data_path.is_dir() or not data_path.exists():
        return {"error": f"No canonical market data found for {symbol}", "symbol": symbol, "date": date}

    with data_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            meta = doc.get("Meta Data", {})
            if meta.get("2. Symbol") != symbol:
                continue
            series = doc.get("Time Series (Daily)", {})
            day = series.get(date)
            if day is None:
                sample_dates = sorted(series.keys(), reverse=True)[:5]
                return {
                    "error": f"Data not found for date {date}. Please verify the date exists in data. Sample available dates: {sample_dates}",
                    "symbol": symbol,
                    "date": date,
                }
            else:
                return {
                "symbol": symbol,
                "date": date,
                "ohlcv": {
                    "open": day.get("1. buy price"),
                    "high": day.get("2. high"),
                    "low": day.get("3. low"), 
                    "close": day.get("4. sell price"),
                    "volume": day.get("5. volume"),
                    },
                }
    return {"error": f"No records found for stock {symbol} in local data", "symbol": symbol, "date": date}

def get_price_local_hourly(symbol: str, date: str) -> Dict[str, Any]:
    """
    Read OHLCV data for specified stock and date. Get historical information for specified stock.

    Args:
        symbol: Stock symbol, e.g. 'IBM' or '600243.SHH'.
        date: Date in 'YYYY-MM-DD' format.

    Returns:
        Dictionary containing symbol, date and ohlcv data.
    """

    try:
        data_path = get_config_value("Ashare_DATA_PATH", "./data/agent_data_astock/sse_50_day/merged.jsonl")
        _validate_date_hourly(date)
    except Exception as e:
        return {"error": str(e), "symbol": symbol, "date": date}

    data_path = Path(data_path)
    if not data_path.exists():
        return {"error": f"Data file not found: {data_path}", "symbol": symbol, "date": date}

    with data_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            meta = doc.get("Meta Data", {})
            if meta.get("2. Symbol") != symbol:
                continue
            series = doc.get("Time Series (60min)", {})
            day = series.get(date)
            if day is None:
                sample_dates = sorted(series.keys(), reverse=True)[:5]
                return {
                    "error": f"Data not found for date {date}. Please verify the date exists in data. Sample available dates: {sample_dates}",
                    "symbol": symbol,
                    "date": date
                }
            else:
                return {
                    "symbol": symbol,
                    "date": date,
                    "ohlcv": {
                        "open": day.get("1. buy price"),
                        "high": day.get("2. high"),
                        "low": day.get("3. low"), 
                        "close": day.get("4. sell price"),
                        "volume": day.get("5. volume"),
                    },
                }

    return {"error": f"No records found for stock {symbol} in local data", "symbol": symbol, "date": date}

def get_price_local_function(symbol: str, date: str, filename: str = "merged.jsonl") -> Dict[str, Any]:
    """
    Read OHLCV data for specified stock and date from local JSONL data.

    Args:
        symbol: Stock symbol, e.g. 'IBM' or '600243.SHH'.
        date: Date in 'YYYY-MM-DD' format.
        filename: Data filename, defaults to 'merged.jsonl' (located in data/ under project root).

    Returns:
        Dictionary containing symbol, date and ohlcv data.
    """
    try:
        _validate_date_daily(date)
    except ValueError as e:
        return {"error": str(e), "symbol": symbol, "date": date}

    data_path = get_config_value("Ashare_DATA_PATH", "./data/agent_data_astock/sse_50_day/merged.jsonl")
    data_path = Path(data_path)
    if not data_path.exists():
        return {"error": f"Data file not found: {data_path}", "symbol": symbol, "date": date}

    with data_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            meta = doc.get("Meta Data", {})
            if meta.get("2. Symbol") != symbol:
                continue
            series = doc.get("Time Series (Daily)", {})
            day = series.get(date)
            if day is None:
                sample_dates = sorted(series.keys(), reverse=True)[:5]
                return {
                    "error": f"Data not found for date {date}. Please verify the date exists in data. Sample available dates: {sample_dates}",
                    "symbol": symbol,
                    "date": date,
                }
            return {
                "symbol": symbol,
                "date": date,
                "ohlcv": {
                    "buy price": day.get("1. buy price"),
                    "high": day.get("2. high"),
                    "low": day.get("3. low"),
                    "sell price": day.get("4. sell price"),
                    "volume": day.get("5. volume"),
                },
            }

    return {"error": f"No records found for stock {symbol} in local data", "symbol": symbol, "date": date}

if __name__ == "__main__":
    port = int(os.getenv("GETPRICE_HTTP_PORT", "8002"))
    mcp.run(transport="streamable-http", port=port)

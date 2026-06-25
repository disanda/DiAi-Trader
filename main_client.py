import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from agent.base_agent_astock import BaseAgentAStock

from agent.general_tools import get_config_value, write_config_value, _resolve_runtime_env_path
import importlib
import sys

ashare_symbols_str = get_config_value("Ashare_symbols") # Ashare_symbols = ETF_25, all_nasdaq_100_symbols
module = importlib.import_module("utils.ashare_symbol")
ashare_symbols = getattr(module, ashare_symbols_str)

# Agent class mapping table - for dynamic import and instantiation
AGENT_REGISTRY = {
    "BaseAgentAStock": {
        "module": "agent.base_agent_astock",
        "class": "BaseAgentAStock"
    },
    "BaseAgentAStock_Hour": {
        "module": "agent.base_agent_astock_hour",
        "class": "BaseAgentAStock_Hour"
    },
}

mcp_service_configs = {            
            "math": {
                "transport": "streamable_http",
                "url": f"http://127.0.0.1:{os.getenv('MATH_HTTP_PORT', '8000')}/mcp",
            },
            "trade": {
                "transport": "streamable_http",
                "url": f"http://127.0.0.1:{os.getenv('TRADE_HTTP_PORT', '8001')}/mcp",
            },
            "price": {
                "transport": "streamable_http",
                "url": f"http://127.0.0.1:{os.getenv('GETPRICE_HTTP_PORT', '8002')}/mcp",
            },
            "price_online": {
                "transport": "streamable_http",
                "url": f"http://127.0.0.1:{os.getenv('GETPRICE_ONLINE_HTTP_PORT', '8003')}/mcp",
            }
}

def get_agent_class(agent_type):
    """
    Dynamically import and return the corresponding class based on agent type name

    Args:
        agent_type: Agent type name (e.g., "BaseAgent")

    Returns:
        Agent class

    Raises:
        ValueError: If agent type is not supported
        ImportError: If unable to import agent module
    """
    if agent_type not in AGENT_REGISTRY:
        supported_types = ", ".join(AGENT_REGISTRY.keys())
        raise ValueError(f"❌ Unsupported agent type: {agent_type}\n" f"   Supported types: {supported_types}")

    agent_info = AGENT_REGISTRY[agent_type]
    module_path = agent_info["module"]
    print(module_path)
    class_name = agent_info["class"]

    try:
        # Dynamic import module
        import importlib
        module = importlib.import_module(module_path)
        agent_class = getattr(module, class_name)
        print(f"✅ Successfully loaded Agent class: {agent_type} (from {module_path})")
        return agent_class
    except ImportError as e:
        raise ImportError(f"❌ Unable to import agent module {module_path}: {e}")
    except AttributeError as e:
        raise AttributeError(f"❌ Class {class_name} not found in module {module_path}: {e}")

def load_config(config_path=None): # Args: config_path: Configuration file path, if None use default config
    if config_path is None:
        # Default configuration file path
        config_path = Path(__file__).parent / "configs" / "astock_config.json"
    else:
        config_path = Path(config_path)
    print(config_path)

    if not config_path.exists():
        print(f"❌ Configuration file does not exist: {config_path}")
        exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        print(f"✅ Successfully loaded configuration file: {config_path}")
        return config # Returns: dict: Configuration dictionary
    except json.JSONDecodeError as e:
        print(f"❌ Configuration file JSON format error: {e}")
        exit(1)
    except Exception as e:
        print(f"❌ Failed to load configuration file: {e}")
        exit(1)

async def main(config_path=None): # config_path: Configuration file path, if None use default config
    config = load_config(config_path) # Load configuration file

    # Get Agent type
    agent_type = config.get("agent_type", "BaseAgent") # Get Agent type，第二项是缺失的默认值
    try:
        AgentClass = get_agent_class(agent_type)
    except (ValueError, ImportError, AttributeError) as e:
        print(str(e))
        exit(1)

    market = "cn"
    print(f"🌍 Market type: A-shares (China)")

    INIT_DATE = config["date_range"]["init_date"] # # Get date range from configuration file
    END_DATE = config["date_range"]["end_date"]

    # Environment variables can override dates in configuration file
    if os.getenv("INIT_DATE"):
        INIT_DATE = os.getenv("INIT_DATE")
        print(f"⚠️  Using environment variable to override INIT_DATE: {INIT_DATE}")
    if os.getenv("END_DATE"):
        END_DATE = os.getenv("END_DATE")
        print(f"⚠️  Using environment variable to override END_DATE: {END_DATE}")

    # Validate date range, Support both YYYY-MM-DD and YYYY-MM-DD HH:MM:SS formats
    if ' ' in INIT_DATE:
        INIT_DATE_obj = datetime.strptime(INIT_DATE, "%Y-%m-%d %H:%M:%S")
    else:
        INIT_DATE_obj = datetime.strptime(INIT_DATE, "%Y-%m-%d")
    
    if ' ' in END_DATE:
        END_DATE_obj = datetime.strptime(END_DATE, "%Y-%m-%d %H:%M:%S")
    else:
        END_DATE_obj = datetime.strptime(END_DATE, "%Y-%m-%d")
    
    if INIT_DATE_obj > END_DATE_obj:
        print("❌ INIT_DATE is greater than END_DATE")
        exit(1)

    enabled_models = [model for model in config["models"] if model.get("enabled", True)] # Get model list from configuration file (only select enabled models)
    agent_config = config.get("agent_config", {}) # Get agent configuration
    log_config = config.get("log_config", {})
    max_steps = agent_config.get("max_steps", 10)
    max_retries = agent_config.get("max_retries", 3)
    base_delay = agent_config.get("base_delay", 0.5)
    initial_cash = agent_config.get("initial_cash", 10000.0)
    verbose = agent_config.get("verbose", False)
    model_data_path = log_config.get("model_data_path", "./data/agent_data_astock/sse_50_day")
    Ashare_data_path = log_config.get("Ashare_data_path", "./data/a_stock_data/sse_50_day/merged.jsonl")

    model_names = [m.get("name", m.get("signature")) for m in enabled_models] # Display enabled model information

    print(f"🚀 Starting trading experiment, 📅 Date range: {INIT_DATE} to {END_DATE}, 🤖 Agent type: {agent_type}, Model list: {model_names}")
    print(f"⚙️  Agent config: max_steps={max_steps}, max_retries={max_retries}, base_delay={base_delay}, initial_cash={initial_cash}, verbose={verbose}")

    for model_config in enabled_models: # Read basemodel and signature directly from configuration file
        model_name = model_config.get("name", "unknown")
        basemodel = model_config.get("basemodel")
        signature = model_config.get("signature")
        openai_base_url = model_config.get("openai_base_url",None)
        openai_api_key = model_config.get("openai_api_key",None)
        
        if not basemodel: # Validate required fields
            print(f"❌ Model {model_name} missing basemodel field")
            continue
        if not signature:
            print(f"❌ Model {model_name} missing signature field")
            continue

        print("=" * 60)
        print(f"🤖 Processing model: {model_name}, 📝 Signature: {signature}, 🔧 BaseModel: {basemodel}")

        # 统一拼接逻辑：基础路径 / 类型 / 签名
        position_file = Path(model_data_path) / "position" / "position.jsonl"

        # If position file doesn't exist, reset config to start from INIT_DATE
        if not position_file.exists(): # Clear the shared config file for fresh start
            runtime_env_path = _resolve_runtime_env_path()
            if os.path.exists(runtime_env_path):
                os.remove(runtime_env_path)
                print(f"🔄 Position file not found, cleared config for fresh start from {INIT_DATE}")

        write_config_value("SIGNATURE", signature) # Write config values to shared config file (from .env RUNTIME_ENV_PATH)
        write_config_value("IF_TRADE", False)
        write_config_value("MARKET", market)
        write_config_value("MODEL_DATA_PATH", model_data_path)
        write_config_value("Ashare_DATA_PATH", Ashare_data_path)
        print(f"✅ Runtime config initialized: SIGNATURE={signature}, MARKET={market}")

        # Select symbols based on agent type and market, Crypto agents don't use stock_symbols parameter
        stock_symbols = ashare_symbols #stock_symbols = all_nasdaq_100_symbols

        try: # Dynamically create Agent instance
            agent = AgentClass(
                    signature=signature,
                    basemodel=basemodel,
                    stock_symbols=stock_symbols,
                    mcp_config = mcp_service_configs,
                    log_path=model_data_path,
                    max_steps=max_steps,
                    max_retries=max_retries,
                    base_delay=base_delay,
                    initial_cash=initial_cash,
                    init_date=INIT_DATE,
                    openai_base_url=openai_base_url,
                    openai_api_key=openai_api_key)

            print(f"✅ {agent_type} instance created successfully: {agent}")
            await agent.initialize()   # Initialize MCP connection and AI model
            print("✅ Initialization successful")
            await agent.run_date_range(INIT_DATE, END_DATE) # Run all trading days in date range

            summary = agent.get_position_summary() # Display final position summary
            if agent.market == "cn": # Get currency symbol from agent's actual market (more accurate)
                currency_symbol = "¥" # currency_symbol = "$"
            print(f"📊 Final position summary:")
            print(f"   - Latest date: {summary.get('latest_date')}")
            print(f"   - Total records: {summary.get('total_records')}")
            print(f"   - Cash balance: {currency_symbol}{summary.get('positions', {}).get('CASH', 0):,.2f}")

        except Exception as e:
            print(f"❌ Error processing model {model_name} ({signature}): {str(e)}")
            print(f"📋 Error details: {e}")  # continue  # Continue processing next model
            exit()  # Or exit program 

        print("=" * 60)
        print(f"✅ Model {model_name} ({signature}) processing completed")
    print("🎉 All models processing completed!")

if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else None

    if config_path:
        print(f"📄 Using specified configuration file: {config_path}")
    else:
        print(f"📄 Using default configuration file: configs/astock_config.json")
    asyncio.run(main(config_path))
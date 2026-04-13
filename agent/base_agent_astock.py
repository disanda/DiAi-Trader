#A股专用交易Agent基类 including MCP tool management, AI agent creation, and trading execution
# main() -> run_date_range (子类无) -> run_with_retry (子类无) -> run_session
import os
import sys
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import langchain
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from agent.agent_prompt.agent_prompt_astock import (STOP_SIGNAL, get_agent_system_prompt_astock)
from agent.general_tools import (extract_conversation, extract_tool_messages, get_config_value, write_config_value)
from agent.price_tools import add_no_trade_record, is_trading_day
import utils.ashare_symbol as ashare_symbol
load_dotenv()# Load environment variables

class BaseAgentAStock:
    """
    A股专用交易Agent基类 Chinese A-shares specific trading agent base class
    Main functionalities:
    1. MCP tool management and connection
    2. AI agent creation and configuration
    3. Trading execution and decision loops (with A-shares specific rules)
    4. Logging and management
    5. Position and configuration management
    """

    DEFAULT_SSE50_SYMBOLS = ashare_symbol.sse_50_symbols #Default SSE 50 stock symbols (A-shares only)

    def __init__(
        self,
        signature: str,
        basemodel: str,
        stock_symbols: Optional[List[str]] = None,
        mcp_config: Optional[Dict[str, Dict[str, Any]]] = None,
        log_path: Optional[str] = None,
        max_steps: int = 10,
        max_retries: int = 3,
        base_delay: float = 0.5,
        openai_base_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        initial_cash: float = 1000000.0,  # 默认100万人民币
        init_date: str = "2026-09-01",
        market: str = "cn",  # 接受但忽略此参数，始终使用"cn"
    ):
        """
        Initialize BaseAgentAStock

        Args:
            signature: Agent signature/name
            basemodel: Base model name
            stock_symbols: List of stock symbols, defaults to SSE 50
            mcp_config: MCP tool configuration, including port and URL information
            log_path: Log path, defaults to ./data/agent_data_astock
            max_steps: Maximum reasoning steps
            max_retries: Maximum retry attempts
            base_delay: Base delay time for retries
            openai_base_url: OpenAI API base URL
            openai_api_key: OpenAI API key
            initial_cash: Initial cash amount (default: 100000.0 RMB)
            init_date: Initialization date
            market: Market type (accepted for compatibility, but always uses "cn")
        """
        self.signature = signature
        self.basemodel = basemodel
        self.market = "cn"  # 硬编码为A股市场

        # 默认使用上证50成分股
        if stock_symbols is None:
            self.stock_symbols = self.DEFAULT_SSE50_SYMBOLS
        else:
            self.stock_symbols = stock_symbols

        self.max_steps = max_steps
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.initial_cash = initial_cash
        self.init_date = init_date

        # Set log path - A股专用路径
        self.base_log_path = log_path

        # Set OpenAI configuration
        if openai_base_url == None:
            self.openai_base_url = os.getenv("OPENAI_API_BASE")
        else:
            self.openai_base_url = openai_base_url
        if openai_api_key == None:
            self.openai_api_key = os.getenv("OPENAI_API_KEY")
        else:
            self.openai_api_key = openai_api_key

        # Initialize components
        self.model: Optional[ChatOpenAI] = None
        self.agent: Optional[Any] = None
        self.client: Optional[MultiServerMCPClient] = None
        self.tools: Optional[List] = None
        self.mcp_config = mcp_config

        # Data paths
        self.model_data_path = Path(os.path.join(self.base_log_path, self.signature))
        self.position_file = self.model_data_path / "position" / "position.jsonl"

    async def initialize(self) -> None:
        """Initialize MCP client and AI model"""
        print(f"🚀 Initializing A-shares agent: {self.signature}")

        if not self.openai_api_key: #Validate OpenAI configuration
            raise ValueError("❌ OpenAI API key not set. Please configure OPENAI_API_KEY in environment or config file.")

        if not self.openai_base_url:
            print("⚠️  OpenAI base URL not set, using default")

        try:
            # Create MCP client
            self.client = MultiServerMCPClient(self.mcp_config)
            #print("okkkkkkk")

            # Get tools
            self.tools = await self.client.get_tools()
            #print("okkkkkkk2")
            if not self.tools:
                print("⚠️  Warning: No MCP tools loaded. MCP services may not be running.")
                print(f"   MCP configuration: {self.mcp_config}")
            else:
                print(f"✅ Loaded {len(self.tools)} MCP tools")
                #print(self.tools)
            # Create AI model - use custom DeepSeekChatOpenAI for DeepSeek models
            # to handle tool_calls.args format differences (JSON string vs dict)
            if "deepseek" in self.basemodel.lower():
                self.model = DeepSeekChatOpenAI(
                    model=self.basemodel,
                    base_url=self.openai_base_url,
                    api_key=self.openai_api_key,
                    max_retries=3,
                    timeout=30,
                )
            else:
                self.model = ChatOpenAI(
                    model=self.basemodel,
                    base_url=self.openai_base_url,
                    api_key=self.openai_api_key,
                    max_retries=3,
                    timeout=30,
                )
        except Exception as e:
            raise RuntimeError(f"❌ Failed to initialize AI model: {e}")

        # Note: agent will be created in run_trading_session() based on specific date
        # because system_prompt needs the current date and price information

        print(f"✅ A-shares agent {self.signature} initialization completed")

    def _setup_logging(self, today_date: str) -> str: 
        #Set up log file path
        log_path = os.path.join(self.base_log_path ,self.signature, "log", today_date)
        if not os.path.exists(log_path):
            os.makedirs(log_path)
        return os.path.join(log_path, "log.jsonl")

    def _log_message(self, log_file: str, new_messages: List[Dict[str, str]]) -> None:
        """Log messages to log file"""
        log_entry = {"timestamp": datetime.now().isoformat(), "signature": self.signature, "new_messages": new_messages}
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    def _log_step(self, log_file: str, step_entry: Dict[str, Any]) -> None:
        """
        Log one full agent step (atomic, replayable)
        """
        step_entry["timestamp"] = datetime.now().isoformat()
        step_entry["signature"] = self.signature

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(step_entry, ensure_ascii=False) + "\n")

    async def _ainvoke_with_retry(self, message: List[Dict[str, str]]) -> Any: #Agent invocation with retry
        for attempt in range(1, self.max_retries + 1):
            try:
                return await self.agent.ainvoke({"messages": message}, {"recursion_limit": 100}) # 限制 Agent 在一次“思考”中翻看资料的次数
            except Exception as e:
                if attempt == self.max_retries:
                    raise e
                print(f"⚠️ Attempt {attempt} failed, retrying after {self.base_delay * attempt} seconds...")
                print(f"Error details: {e}")
                await asyncio.sleep(self.base_delay * attempt)

    def _load_latest_journal(self, journal_dir: Path, today_date: str) -> str:
            """寻找日期在 today_date 之前且最接近的一份日志"""
            journals = sorted([f for f in journal_dir.glob("journal_*.md")], reverse=True)
            today_str = today_date.replace("-", "")
            
            for j in journals:
                # 提取文件名中的日期进行比较
                j_date = j.stem.split("_")[1]
                if j_date < today_str:
                    print(f"📖 已找到历史日志文件: {j.name}")
                    return j.read_text(encoding="utf-8")
            return ""

    async def _write_daily_journal(self, today_date: str, conversation_history: List[Dict], journal_dir: Path) -> None:
            """引导 Agent 撰写今日复盘日志并保存"""
            print(f"📝 正在撰写今日交易日志...")
            
            journal_request = {
                "role": "user", 
                "content": (
                    "今日交易已结束。请对今日操作与长线交易逻辑，撰写一份《交易复盘日志》。要求：\n"
                    "1. 今日交易操作概览，及当前交易策略的意义。\n"
                    "2. 总结目前持仓(含各股仓位、价值和当前现金量), 概述短-中-长线策略。\n"
                    "3. 当前持仓的风险预警点及应对策略 & 下一阶段调仓意向 "
                    "4. 如果过去交易策略存在不足，需指出并给出改进方法。\n"
                    "5. 你觉得有必要记录的其他信息。\n"
                    "若 今日《交易复盘日志》的部分内容与昨日内容接近，则简略撰写，总体字数控制在500字左右。"
                    "若 今日《交易复盘日志》相对昨日内容改变较大，则需在日志标题后注明“有重要更新“，字数限制放宽到800字以内。"
                    "这份日志将作为你长期交易的核心记录，日志格式统一采用Markdown \n"
                )
            }
            
            temp_messages = conversation_history + [journal_request]
            
            try:
                response = await self._ainvoke_with_retry(temp_messages)
                journal_content = extract_conversation(response, "final")
                
                # 以日期为文件名保存
                file_name = f"journal_{today_date.replace('-', '')}.md"
                journal_path = journal_dir / file_name
                journal_path.write_text(journal_content, encoding="utf-8")
                print(f"✅ 今日日志已保存: {file_name}")
            except Exception as e:
                print(f"⚠️ 撰写日志失败: {e}")

    async def _handle_trading_result(self, today_date: str) -> None:
        """Handle trading results"""
        if_trade = get_config_value("IF_TRADE")
        if if_trade:
            write_config_value("IF_TRADE", False)
            print("✅ Trading completed")
        else:
            print("📊 No trading, maintaining positions")
            try:
                add_no_trade_record(today_date, self.signature)
            except NameError as e:
                print(f"❌ NameError: {e}")
                raise
            write_config_value("IF_TRADE", False)

    async def run_trading_session(self, today_date: str) -> None:
        """
        Run single day trading session (A-shares specific)

        Args:
            today_date: Trading date
        """
        print(f"📈 Starting A-shares trading session: {today_date}")
        log_file = self._setup_logging(today_date) # Set up logging

        # 1. 路径定义：日志存放目录
        journal_dir = self.model_data_path / "daily_journals"
        journal_dir.mkdir(parents=True, exist_ok=True)

        # 2. 读取“昨日”或“最近一次”的日志
        last_journal_content = self._load_latest_journal(journal_dir, today_date)

        # 3. 初始化 Agent, Update system prompt - 使用A股专用提示词
        self.agent = create_agent( 
            self.model,
            tools=self.tools,
            system_prompt=get_agent_system_prompt_astock(today_date, self.signature, self.stock_symbols),
        )

        # 4. 构造初始 Query：将长线日志注入上下文
        prompt_content = f"请分析并更新当前（{today_date}）的持仓。"
        if last_journal_content:
            prompt_content = (
                f"### 历史交易日志与长线逻辑回顾：\n{last_journal_content}\n\n"
                f"### 今日任务：\n请结合上述长线逻辑，分析并更新今日（{today_date}）的持仓。保持策略连贯性。"
            )

        user_query = [{"role": "user", "content": prompt_content}] # Initial user query
        message = user_query.copy()
        self._log_message(log_file, user_query) # Log initial message

        # 5. 执行原有的交易循环 (trading loop) ...
        current_step = 0 # Trading loop
        while current_step < self.max_steps: # 限制 Agent 在今天跟我交流的次数
            current_step += 1
            print(f"🔄 Step {current_step}/{self.max_steps}")

            try: # Call agent
                response = await self._ainvoke_with_retry(message)
                agent_response = extract_conversation(response, "final") # Extract agent response
                tool_msgs = extract_tool_messages(response) # Extract tool messages

                # ====== ⭐ 核心：构造 step 级日志 ======
                tool_records = [
                    {
                        "tool_name": msg.name,
                        "tool_output": msg.content,
                    }
                    for msg in tool_msgs
                ]
                step_log = {
                    "step": current_step,
                    "input_messages": message.copy(),
                    "agent_final": agent_response,
                    "tools": tool_records,
                    "stop": STOP_SIGNAL in agent_response,
                }

                self._log_step(log_file, step_log)

                if STOP_SIGNAL in agent_response: # Check stop signal
                    print("✅ Received stop signal, trading session ended")
                    print(agent_response)
                    self._log_message(log_file, [{"role": "assistant", "content": agent_response}])
                    break

                # ====== 继续对话 ======
                clean_tool_responses = []
                for msg in tool_msgs:
                    content = msg.content
                    if "error" in content:
                        # 如果工具报错，包装成 AI 容易处理但不会导致格式混乱的形式
                        clean_tool_responses.append(f"System Alert: Tool {msg.name} failed with error.")
                    else:
                        clean_tool_responses.append(content)
                tool_response = "\n".join(clean_tool_responses)

                # Prepare new messages
                new_messages = [ 
                    {"role": "assistant", "content": agent_response}, 
                    {"role": "user", "content": f"Tool results: {tool_response}"}, 
                ]
                message.extend(new_messages) # Add new messages

                self._log_message(log_file, new_messages[0]) # Log messages
                self._log_message(log_file, new_messages[1])

            except Exception as e:
                print(f"❌ Trading session error: {str(e)}")
                print(f"Error details: {e}")
                raise

        # 6. 交易trading loop结束后, 如果 Agent 发出了 STOP_SIGNAL, 我们增加一个“撰写交易日志”的任务
        await self._write_daily_journal(today_date, message, journal_dir)
        await self._handle_trading_result(today_date) # Handle trading results

    async def run_with_retry(self, today_date: str) -> None:
        """Run method with retry"""
        for attempt in range(1, self.max_retries + 1):
            try:
                print(f"🔄 Attempting to run {self.signature} - {today_date} (Attempt {attempt})")
                await self.run_trading_session(today_date) # 重新建立连接
                print(f"✅ {self.signature} - {today_date} run successful")
                return
            except Exception as e:
                print(f"❌ Attempt {attempt} failed: {str(e)}")
                if attempt == self.max_retries:
                    print(f"💥 {self.signature} - {today_date} all retries failed")
                    raise
                else:
                    wait_time = self.base_delay * attempt
                    print(f"⏳ Waiting {wait_time} seconds before retry...")
                    await asyncio.sleep(wait_time)

    def register_agent(self) -> None:
        """Register new agent, create initial positions"""

        # Check if position.jsonl file already exists
        if os.path.exists(self.position_file):
            print(f"⚠️ Position file {self.position_file} already exists, skipping registration")
            return

        # Ensure directory structure exists
        position_dir = os.path.join(self.model_data_path, "position")
        if not os.path.exists(position_dir):
            os.makedirs(position_dir)
            print(f"📁 Created position directory: {position_dir}")

        # Create initial positions
        init_position = {symbol: 0 for symbol in self.stock_symbols}
        init_position["CASH"] = self.initial_cash

        # Normalize init_date to zero-padded HH if time exists
        init_date_str = self.init_date
        if " " in init_date_str:
            try:
                # If already proper format, keep it
                datetime.strptime(init_date_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    date_part, time_part = init_date_str.split(" ", 1)
                    hh, mm, ss = time_part.split(":")
                    init_date_str = f"{date_part} {hh.zfill(2)}:{mm}:{ss}"
                except Exception:
                    # Fallback: keep original if unexpected
                    pass

        with open(self.position_file, "w") as f:  # Use "w" mode to ensure creating new file
            f.write(json.dumps({"date": init_date_str, "id": 0, "positions": init_position}) + "\n")

        print(f"✅ A-shares agent {self.signature} registration completed")
        print(f"📁 Position file: {self.position_file}")
        print(f"💰 Initial cash: ¥{self.initial_cash:,.2f}")
        print(f"📊 Number of stocks: {len(self.stock_symbols)}")

    def get_trading_dates(self, init_date: str, end_date: str, force_from_init: bool =True) -> List[str]:
        #Get trading date list, filtered by actual trading days in A-shares market
        #Args - init_date: Start date, end_date: End date; Returns: List of trading dates (excluding weekends and holidays)

        if force_from_init:
            max_date = init_date

        dates = []
        max_date = None
        if not os.path.exists(self.position_file):
            self.register_agent()
            max_date = init_date
        else: # Read existing position file, find latest date
            with open(self.position_file, "r") as f:
                for line in f:
                    doc = json.loads(line)
                    current_date = doc["date"]
                    if max_date is None:
                        max_date = current_date
                    else:
                        current_date_obj = datetime.strptime(current_date, "%Y-%m-%d")
                        max_date_obj = datetime.strptime(max_date, "%Y-%m-%d")
                        if current_date_obj > max_date_obj:
                            max_date = current_date

        max_date_obj = datetime.strptime(max_date, "%Y-%m-%d") # Check if new dates need to be processed
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

        if end_date_obj <= max_date_obj:
            return []

        trading_dates = [] # Generate trading date list, filtered by actual trading days (A-shares market)
        current_date = max_date_obj + timedelta(days=1)

        while current_date <= end_date_obj:
            date_str = current_date.strftime("%Y-%m-%d") # Check if this is an actual trading day in A-shares market
            if is_trading_day(date_str, market="cn"):
                trading_dates.append(date_str)
            current_date += timedelta(days=1)
        return trading_dates

    async def run_date_range(self, init_date: str, end_date: str) -> None:
        # Run all trading days in date range, Args: init_date: Start date end_date: End date.
        print(f"📅 Running A-shares date range: {init_date} to {end_date}")
        trading_dates = self.get_trading_dates(init_date, end_date) #Get trading date list
        if not trading_dates:
            print(f"ℹ️ No trading days to process")
            return
        
        print(f"📊 Trading days to process: {trading_dates}")
        for date in trading_dates:
            print(f"🔄 Processing {self.signature} - Date: {date}") # Process each trading day
            write_config_value("TODAY_DATE", date) # Set configuration
            write_config_value("SIGNATURE", self.signature)

            try:
                await self.run_with_retry(date)
            except Exception as e:
                print(f"❌ Error processing {self.signature} - Date: {date}")
                print(e)
                raise

        print(f"✅ {self.signature} processing completed")

    def get_position_summary(self) -> Dict[str, Any]:
        """Get position summary"""
        
        if not os.path.exists(self.position_file):
            return {"error": "Position file does not exist"}
        
        print(self.position_file)
        positions = []
        with open(self.position_file, "r") as f:
            for line in f:
                positions.append(json.loads(line))

        if not positions:
            return {"error": "No position records"}

        latest_position = positions[-1]
        return {
            "signature": self.signature,
            "latest_date": latest_position.get("date"),
            "positions": latest_position.get("positions", {}),
            "total_records": len(positions),
        }

    def __str__(self) -> str:
        return (
            f"BaseAgentAStock(signature='{self.signature}', basemodel='{self.basemodel}', "
            f"market='cn', stocks={len(self.stock_symbols)})"
        )

    def __repr__(self) -> str:
        return self.__str__()

if __name__ == "__main__":
    # new_result = buy("AAPL", 1)
    # print(new_result)
    # new_result = sell("AAPL", 1)
    # print(new_result)
    port = int(os.getenv("TRADE_HTTP_PORT", "8002"))
    mcp.run(transport="streamable-http", port=port)

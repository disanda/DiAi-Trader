import json
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
load_dotenv()

def _resolve_runtime_env_path() -> str: 
#确定“运行期配置文件”存放路径
#Resolve runtime env path from RUNTIME_ENV_PATH in .env file.
#Simple strategy:
#1. Read RUNTIME_ENV_PATH from environment (.env file)
#2. If relative path, resolve from project root
#3. Return the path (will be created by write_config_value if needed)
    path = os.environ.get("RUNTIME_ENV_PATH")
    if not path: # Fallback to default if not set
        path = "./data/.runtime_env.json"
    if not os.path.isabs(path): # If relative path, resolve from project root
        base_dir = Path(__file__).resolve().parents[1]
        path = str(base_dir / path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
    return path

def _load_runtime_env() -> dict: 
# 加载运行期配置文件（JSON）
    path = _resolve_runtime_env_path()
    if path is None:
        return {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def get_config_value(key: str, default=None, json_config_path: str = None):
    """
    统一配置文件读取入口（支持 JSON + 原有环境变量）
    
    参数:
        key: 要读取的配置键（如 "sse_50", "Ashare_symbols" 等）
        default: 默认值
        json_config_path: JSON配置文件路径（如果提供则优先读取）
    """
    # 1. 优先从 JSON 文件读取（如果你传了路径）
    if json_config_path:
        config_file = Path(json_config_path)
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                # 如果 key 直接存在于 JSON 中（例如 "sse_50"）
                if key in config:
                    return config[key]
                
                # 可选：也支持读取像 "Ashare_symbols" 这样的控制键（以后扩展用）
                if key == "Ashare_symbols" and "Ashare_symbols" in config:
                    return config["Ashare_symbols"]
                    
            except Exception as e:
                print(f"⚠️ 读取 JSON 配置文件失败 ({config_file}): {e}")
        else:
            print(f"⚠️ JSON 配置文件不存在: {config_file}")

    # 2. 保留原来的逻辑（运行时环境 + 环境变量）
    _RUNTIME_ENV = _load_runtime_env()
    if key in _RUNTIME_ENV:
        return _RUNTIME_ENV[key]

    return os.getenv(key, default)
def write_config_value(key: str, value: Any): 
# 把程序运行过程中产生的状态，写入 runtime env JSON 文件，“覆盖式写入”
    path = _resolve_runtime_env_path()
    if path is None:
        print(f"⚠️  WARNING: RUNTIME_ENV_PATH not set, config value '{key}' not persisted")
        return
    _RUNTIME_ENV = _load_runtime_env()
    _RUNTIME_ENV[key] = value
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_RUNTIME_ENV, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ Error writing config to {path}: {e}")

def extract_conversation(conversation: dict, output_type: str):
    """
    Extract information from a conversation payload.
    Args:
        conversation: A mapping that includes 'messages' (list of dicts or objects with attributes).
        output_type: 'final' to return the model's final answer content; 'all' to return the full messages list.
    Returns:
        For 'final': the final assistant content string if found, otherwise None.
        For 'all': the original messages list (or empty list if missing).
    """
    def get_field(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    def get_nested(obj, path, default=None):
        current = obj
        for key in path:
            current = get_field(current, key, None)
            if current is None:
                return default
        return current
    messages = get_field(conversation, "messages", []) or []

    if output_type == "all":
        return messages

    if output_type == "final": # Prefer the last message with finish_reason == 'stop' and non-empty content.
        for msg in reversed(messages):
            finish_reason = get_nested(msg, ["response_metadata", "finish_reason"])
            content = get_field(msg, "content")
            if finish_reason == "stop" and isinstance(content, str) and content.strip():
                return content

        for msg in reversed(messages): # Fallback: last AI-like message with non-empty content and not a tool call.
            content = get_field(msg, "content")
            additional_kwargs = get_field(msg, "additional_kwargs", {}) or {}
            tool_calls = None
            if isinstance(additional_kwargs, dict):
                tool_calls = additional_kwargs.get("tool_calls")
            else:
                tool_calls = getattr(additional_kwargs, "tool_calls", None)

            is_tool_invoke = isinstance(tool_calls, list) # Tool messages often have 'tool_call_id' or 'name' (tool name)
            has_tool_call_id = get_field(msg, "tool_call_id") is not None
            tool_name = get_field(msg, "name")
            is_tool_message = has_tool_call_id or isinstance(tool_name, str)

            if not is_tool_invoke and not is_tool_message and isinstance(content, str) and content.strip():
                return content

        return None

    raise ValueError("output_type must be 'final' or 'all'")

def extract_tool_messages(conversation: dict):
    """
    Return all ToolMessage-like entries from the conversation.
    A ToolMessage is identified heuristically by having either:
      - a non-empty 'tool_call_id', or
      - a string 'name' (tool name) and no 'finish_reason' like normal AI messages
    Supports both dict-based and object-based messages. 
    """

    def get_field(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def get_nested(obj, path, default=None):
        current = obj
        for key in path:
            current = get_field(current, key, None)
            if current is None:
                return default
        return current

    messages = get_field(conversation, "messages", []) or []
    tool_messages = []
    for msg in messages:
        tool_call_id = get_field(msg, "tool_call_id")
        name = get_field(msg, "name")
        finish_reason = get_nested(msg, ["response_metadata", "finish_reason"])  # present for AIMessage
        # Treat as ToolMessage if it carries a tool_call_id, or looks like a tool response
        if tool_call_id or (isinstance(name, str) and not finish_reason): # tool_call_id 存在（强判定）｜ name 存在，但没有 finish_reason（弱判定）
            tool_messages.append(msg)  
    return tool_messages

def extract_first_tool_message_content(conversation: dict):
    """
    Return the content of the first ToolMessage if available, else None.
    """
    msgs = extract_tool_messages(conversation)
    if not msgs:
        return None

    first = msgs[0]
    if isinstance(first, dict):
        return first.get("content")
    return getattr(first, "content", None)

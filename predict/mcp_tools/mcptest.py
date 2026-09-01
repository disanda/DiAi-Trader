#!/usr/bin/env python3
"""Smoke tests for the prediction news-search MCP server.

Examples:
    python mcptest.py --api-pool api.json
    python mcptest.py --api-pool api.json --query "宁德时代 最新消息"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "news_search_server.py"


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def result_text(result) -> str:
    data = plain(result)
    content = data.get("content", []) if isinstance(data, dict) else []
    if isinstance(content, list):
        return "\n".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
    return json.dumps(data, ensure_ascii=False)


async def run(args: argparse.Namespace) -> int:
    server_args = [str(SERVER), "--api-pool", str(Path(args.api_pool).resolve())]
    params = StdioServerParameters(command=sys.executable, args=server_args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            response = await session.list_tools()
            names = {tool.name for tool in response.tools}
            expected = {"news_search", "news_deep_search", "api_pool_status"}
            missing = expected - names
            if missing:
                print(f"FAIL: missing MCP tools: {', '.join(sorted(missing))}")
                return 1
            print(f"PASS: discovered tools: {', '.join(sorted(names))}")

            status = await session.call_tool("api_pool_status", arguments={})
            print("API pool:")
            print(result_text(status))

            if args.query:
                result = await session.call_tool(
                    "news_search",
                    arguments={"query": args.query, "max_results": args.max_results, "time_range": args.time_range},
                )
                payload = result_text(result)
                if not payload:
                    print("FAIL: news_search returned an empty response")
                    return 1
                print("Search result:")
                print(payload)
            else:
                print("PASS: connectivity check complete (use --query for a live search)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the prediction Tavily news-search MCP server")
    parser.add_argument("--api-pool", default=str(ROOT / "api.json"), help="Path to Tavily API pool JSON")
    parser.add_argument("--query", help="Optional live news query")
    parser.add_argument("--max-results", type=int, default=3)
    parser.add_argument("--time-range", default="week", choices=["day", "week", "month", "year", "d", "w", "m", "y"])
    try:
        return asyncio.run(run(parser.parse_args()))
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"FAIL: MCP test error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

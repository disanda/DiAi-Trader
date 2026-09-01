#!/usr/bin/env python3
"""Tavily news-search MCP server for the prediction workflow."""

import argparse
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_POOL = "api.json"
Topic = Literal["general", "news", "finance"]
Depth = Literal["ultra-fast", "fast", "basic", "advanced"]
Range = Literal["day", "week", "month", "year", "d", "w", "m", "y"]


def _clean_json(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _mode(value: str) -> bool | str:
    return True if value == "true" else False if value == "false" else value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _masked(value: str) -> str:
    return "*" * len(value) if len(value) <= 8 else f"{value[:4]}...{value[-4:]}"


@dataclass(frozen=True)
class Credential:
    id: str
    key: str


class ApiPool:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.credentials = self._load()

    def _load(self) -> list[Credential]:
        if not self.path.exists():
            env_key = os.getenv("TAVILY_API_KEY", "").strip()
            if env_key:
                return [Credential("env", env_key)]
            raise FileNotFoundError(f"API pool file not found: {self.path}")
        payload = json.loads(_clean_json(self.path.read_text(encoding="utf-8-sig")))
        entries = payload.get("apis") or payload.get("keys") or [] if isinstance(payload, dict) else payload
        credentials = []
        for index, item in enumerate(entries or []):
            if isinstance(item, str) and item.strip():
                credentials.append(Credential(f"api_{index + 1}", item.strip()))
            elif isinstance(item, dict) and str(item.get("key", "")).strip():
                credentials.append(Credential(str(item.get("id") or f"api_{index + 1}"), str(item["key"]).strip()))
        if not credentials:
            raise ValueError(f"No usable API keys found in: {self.path}")
        return credentials

    def choose(self) -> Credential:
        return random.choice(self.credentials)

    def status(self) -> dict[str, Any]:
        return {"path": str(self.path), "count": len(self.credentials), "apis": [{"id": c.id, "key_masked": _masked(c.key)} for c in self.credentials]}


pool: ApiPool | None = None


def _request(query: str, max_results: int, topic: str, depth: str, answer: str, raw: str, time_range: str | None, country: str | None, raw_chars: int, timeout: int) -> dict[str, Any]:
    credential = pool.choose() if pool else (_ for _ in ()).throw(RuntimeError("API pool is not initialized"))
    body = {"query": query, "max_results": max(1, min(max_results, 20)), "topic": topic, "search_depth": depth, "include_answer": _mode(answer), "include_raw_content": _mode(raw), "include_images": False, "include_favicon": True, "include_usage": True}
    if time_range:
        body["time_range"] = time_range
    if country:
        body["country"] = country
    request = urllib.request.Request(TAVILY_URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {credential.key}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tavily HTTP {exc.code} ({credential.id}): {detail}") from exc
    results = []
    for item in data.get("results", []):
        raw_content = item.get("raw_content")
        if isinstance(raw_content, str) and raw_chars >= 0:
            raw_content = raw_content[:raw_chars]
        results.append({"title": item.get("title", ""), "url": item.get("url", ""), "content": item.get("content", ""), "score": item.get("score"), "published_date": item.get("published_date", ""), "favicon": item.get("favicon", ""), "raw_content": raw_content})
    return {"action": "tavily_news_search", "fetched_at": _now(), "api_id": credential.id, "query": data.get("query", query), "answer": data.get("answer"), "response_time": data.get("response_time"), "request_id": data.get("request_id"), "results": results}


mcp = FastMCP("predict-news-search")


@mcp.tool()
def news_search(query: str, max_results: int = 5, time_range: Range | None = "week", search_depth: Depth = "basic", raw_chars: int = 2000, country: str | None = None) -> dict[str, Any]:
    """Search recent financial and general news through Tavily."""
    return _request(query, max_results, "news", search_depth, "basic", "markdown", time_range, country, raw_chars, 60)


@mcp.tool()
def news_deep_search(query: str, max_results: int = 10, time_range: Range | None = "month", raw_chars: int = 8000) -> dict[str, Any]:
    """Run an advanced news search with synthesized answer and page content."""
    return _request(query, max_results, "news", "advanced", "advanced", "markdown", time_range, None, raw_chars, 90)


@mcp.tool()
def api_pool_status() -> dict[str, Any]:
    """Return API pool metadata without exposing full credentials."""
    return pool.status() if pool else {"error": "API pool is not initialized"}


def main(argv: list[str]) -> None:
    global pool
    parser = argparse.ArgumentParser(description="MCP server for Tavily news search")
    parser.add_argument("--api-pool", default=os.getenv("TAVILY_API_POOL_FILE", DEFAULT_POOL))
    parser.add_argument("--check-pool", action="store_true")
    args = parser.parse_args(argv)
    pool = ApiPool(args.api_pool)
    if args.check_pool:
        print(json.dumps(pool.status(), ensure_ascii=False, indent=2))
        return
    mcp.run()


if __name__ == "__main__":
    main(sys.argv[1:])

"""Prediction competition runner.

The runner deliberately builds each prompt from observations strictly before the
prediction date.  This makes the saved result suitable for a walk-forward test.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # Keep the module usable when python-dotenv is absent.
    def load_dotenv(path, override=False):
        """Small fallback parser for the project's simple KEY=value .env file."""
        env_path = Path(path)
        if not env_path.exists():
            return False
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if value[:1] in ("'", '"') and value[-1:] == value[:1]:
                value = value[1:-1]
            if override or key not in os.environ:
                os.environ[key] = value
        return True


PROJECT_DIR = Path(__file__).resolve().parent.parent
INDICES_DIR = PROJECT_DIR / "data" / "Astocks" / "indices"
OUTPUT_DIR = PROJECT_DIR / "data" / "predict"
CLASS_LABELS = ("strong_down", "down", "up", "strong_up")

load_dotenv(PROJECT_DIR / ".env", override=False)


def safe_directory_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return name.strip("._") or "unnamed_agent"


def load_indices() -> list[dict[str, Any]]:
    indices = []
    for path in sorted(INDICES_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        records = data.get("records", [])
        if records:
            indices.append({
                "ts_code": data.get("ts_code", path.stem),
                "name": data.get("name", path.stem),
                "records": records,
            })
    return indices


def observations_before(records: list[dict[str, Any]], target_date: str, days: int) -> list[dict[str, Any]]:
    """Return only completed observations before target_date, never target day."""
    history = [row for row in records if str(row.get("trade_date", "")) < target_date]
    return history[-days:]


def compact_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("trade_date", "open", "high", "low", "close", "pct_chg", "vol", "amount")
    return [{field: row.get(field) for field in fields} for row in rows]


def candle_class(pct_change: float) -> str:
    if pct_change <= -1:
        return "strong_down"
    if pct_change < 0:
        return "down"
    if pct_change < 1:
        return "up"
    return "strong_up"


def actual_outcome(index: dict[str, Any], target_date: str) -> dict[str, Any] | None:
    for row in index.get("records", []):
        if str(row.get("trade_date", "")) != target_date:
            continue
        try:
            pct = float(row.get("pct_chg"))
        except (TypeError, ValueError):
            return None
        return {
            "trade_date": target_date,
            "pct_chg": pct,
            "direction": "up" if pct >= 0 else "down",
            "candle_class": candle_class(pct),
            "open": row.get("open"), "high": row.get("high"),
            "low": row.get("low"), "close": row.get("close"),
        }
    return None


def make_prompt(index: dict[str, Any], history: list[dict[str, Any]], target_date: str, rules: str, news_context: str = "") -> str:
    prompt = f"""You are participating in an offline A-share index forecasting evaluation.
Prediction target: {index['name']} ({index['ts_code']}) on {target_date}.
You may only use the ten completed trading sessions supplied below. Do not assume
you know the target day's price or any later information.

{rules}

Return one JSON object only, with this exact schema:
{{
  "direction": "up" | "down",
  "candle_class": "strong_down" | "down" | "up" | "strong_up",
  "confidence": 0-100,
  "expected_pct_change": number,
  "rationale": "concise evidence based on the supplied data",
  "market_analysis": "broad-market and sector implications under this view"
}}

Completed sessions (oldest first):
{json.dumps(compact_history(history), ensure_ascii=False)}"""
    if news_context:
        prompt += f"\n\nRecent news context (use as supplementary evidence; cite links in rationale when relevant):\n{news_context}"
    return prompt


def load_news_search(config: dict[str, Any]):
    """Load the local Tavily client only when news search is enabled."""
    if not config.get("use_news_search", False):
        return None
    try:
        from .mcp_tools import news_search_server
    except ImportError:
        from mcp_tools import news_search_server
    pool_path = config.get("news_api_pool") or os.getenv("TAVILY_API_POOL_FILE") or str(PROJECT_DIR / "predict" / "mcp_tools" / "api.json")
    pool_path = Path(pool_path)
    if not pool_path.is_absolute():
        pool_path = PROJECT_DIR / pool_path
    news_search_server.pool = news_search_server.ApiPool(pool_path)
    return news_search_server


def fetch_news_context(search_module, index: dict[str, Any], config: dict[str, Any]) -> str:
    if search_module is None:
        return ""
    query_template = str(config.get("news_query", "{name} {ts_code} 最新新闻 A股"))
    query = query_template.format(name=index.get("name", ""), ts_code=index.get("ts_code", ""))
    try:
        result = search_module._request(
            query=query,
            max_results=int(config.get("news_max_results", 3)),
            topic="news",
            depth="basic",
            answer="basic",
            raw="markdown",
            time_range=config.get("news_time_range", "week"),
            country=None,
            raw_chars=int(config.get("news_raw_chars", 800)),
            timeout=int(config.get("news_timeout_seconds", 60)),
        )
    except Exception as exc:
        return f"News search unavailable: {exc}"
    items = []
    for item in result.get("results", []):
        title = item.get("title", "").strip()
        content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
        url = item.get("url", "")
        if title or content:
            items.append(f"- {title}: {content[:500]} ({url})")
    return "\n".join(items) if items else "No relevant news results found."


def call_openai_compatible(model: dict[str, Any], prompt: str, timeout: int) -> dict[str, Any]:
    base_url = str(model.get("openai_base_url") or "").rstrip("/")
    api_key = str(model.get("openai_api_key") or "")
    if not api_key and model.get("api_key_env"):
        api_key = os.getenv(str(model["api_key_env"]), "")
    if not base_url or not api_key:
        raise ValueError("Enabled model requires openai_base_url and openai_api_key")
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    payload = {
        "model": model.get("basemodel") or model.get("name"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(model.get("temperature", 0.2)),
    }
    # Some OpenAI-compatible providers reject response_format even though they
    # support chat completions. Enable it explicitly per model when supported.
    if model.get("json_mode", False):
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
        except Exception:
            detail = str(exc.reason)
        raise RuntimeError(f"Model request failed: HTTP {exc.code}: {detail}") from exc
    content = response_data["choices"][0]["message"]["content"]
    return json.loads(content)


def normalise_prediction(raw: dict[str, Any]) -> dict[str, Any]:
    candle_class = str(raw.get("candle_class", "")).lower()
    if candle_class not in CLASS_LABELS:
        raise ValueError("candle_class must be one of " + ", ".join(CLASS_LABELS))
    direction = str(raw.get("direction", "")).lower()
    if direction not in ("up", "down"):
        direction = "up" if candle_class in ("up", "strong_up") else "down"
    confidence = max(0, min(100, float(raw.get("confidence", 0))))
    return {
        "direction": direction,
        "candle_class": candle_class,
        "confidence": confidence,
        "expected_pct_change": raw.get("expected_pct_change"),
        "rationale": str(raw.get("rationale", "")),
        "market_analysis": str(raw.get("market_analysis", "")),
    }


def run_competition(config: dict[str, Any]) -> list[Path]:
    target_date = str(config["prediction_date"]).replace("-", "")
    lookback_days = int(config.get("lookback_days", 10))
    timeout = int(config.get("request_timeout_seconds", 90))
    rules = str(config.get("rules", "Use price, range and volume evidence only."))
    news_search = load_news_search(config)
    enabled_models = [item for item in config.get("models", []) if item.get("enabled")]
    if not enabled_models:
        raise ValueError("No enabled models in test configuration")

    indices = load_indices()
    if not indices:
        raise FileNotFoundError(f"No index data found in {INDICES_DIR}")
    written = []
    for model in enabled_models:
        agent_name = str(model.get("name") or model.get("signature") or model.get("basemodel"))
        results = []
        for index in indices:
            history = observations_before(index["records"], target_date, lookback_days)
            if len(history) < lookback_days:
                results.append({"ts_code": index["ts_code"], "name": index["name"], "error": "Insufficient history"})
                continue
            news_context = ""
            try:
                news_context = fetch_news_context(news_search, index, config)
                raw = call_openai_compatible(model, make_prompt(index, history, target_date, rules, news_context), timeout)
            except Exception as exc:
                results.append({
                    "ts_code": index["ts_code"], "name": index["name"],
                    "as_of_date": history[-1]["trade_date"],
                    "error": str(exc),
                })
                continue
            try:
                prediction = normalise_prediction(raw)
            except Exception as exc:
                results.append({
                    "ts_code": index["ts_code"], "name": index["name"],
                    "as_of_date": history[-1]["trade_date"],
                    "error": f"Invalid model JSON: {exc}",
                })
                continue
            actual = actual_outcome(index, target_date)
            results.append({
                "ts_code": index["ts_code"], "name": index["name"],
                "as_of_date": history[-1]["trade_date"], "lookback": compact_history(history),
                "news_context": news_context or None,
                "prediction": prediction,
                "actual": actual,
                "verification": (None if actual is None else {
                    "direction_correct": prediction["direction"] == actual["direction"],
                    "candle_correct": prediction["candle_class"] == actual["candle_class"],
                }),
            })
        payload = {
            "agent_name": agent_name,
            "prediction_date": target_date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "data_policy": "Each prediction only contains completed index sessions before prediction_date.",
            "predictions": results,
        }
        directory = OUTPUT_DIR / safe_directory_name(agent_name)
        directory.mkdir(parents=True, exist_ok=True)
        output_path = directory / f"{target_date}.json"
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        written.append(output_path)
    return written

"""OpenAI-compatible client that only accepts a forced tool call."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from predict_v2.tool_layer.result_tool import TOOL_NAME, prediction_tool_schema, validate_submission


class ModelCallError(RuntimeError):
    def __init__(self, category: str, attempts: list[dict[str, Any]]):
        super().__init__(category)
        self.category = category
        self.attempts = attempts


def call_prediction_tool(model: dict[str, Any], system_prompt: str, user_prompt: str,
                         reference_close: float | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    api_key = os.environ.get(model["api_key_env"], "")
    if not api_key:
        raise ModelCallError("missing_api_key", [])
    endpoint = model["openai_base_url"].rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    body = {
        "model": model["basemodel"],
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        "temperature": float(model.get("temperature", 0.1)),
        "tools": [prediction_tool_schema()],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
    }
    attempts = []
    maximum = int(model.get("max_retries", 2)) + 1
    for attempt in range(maximum):
        started = time.monotonic()
        audit = {"attempt": attempt + 1, "started_at": datetime.now(timezone.utc).isoformat(),
                 "request_id": None, "http_status": None, "latency_ms": None,
                 "tool_call_received": False, "error_type": None}
        retry = True
        try:
            request = urllib.request.Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, method="POST")
            with urllib.request.urlopen(request, timeout=int(model.get("timeout_seconds", 90))) as response:
                audit["http_status"] = response.status
                audit["request_id"] = response.headers.get("x-request-id")
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("response_too_large")
            payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
            message = payload["choices"][0]["message"]
            calls = message.get("tool_calls")
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("exactly_one_tool_call_required")
            function = calls[0].get("function")
            if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
                raise ValueError("submit_prediction_tool_required")
            arguments = json.loads(function.get("arguments", ""), parse_constant=_reject_constant)
            prediction = validate_submission(arguments, reference_close=reference_close)
            audit["tool_call_received"] = True
            usage = payload.get("usage")
            if isinstance(usage, dict):
                audit["token_usage"] = {key: value for key, value in usage.items()
                                        if key in ("prompt_tokens", "completion_tokens", "total_tokens") and type(value) is int}
            audit["latency_ms"] = round((time.monotonic() - started) * 1000)
            attempts.append(audit)
            return prediction, attempts
        except urllib.error.HTTPError as exc:
            audit.update(http_status=exc.code, error_type="api_error")
            retry = exc.code in (429, 500, 502, 503, 504)
            exc.close()
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
            audit["error_type"] = "network_error"
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError, json.JSONDecodeError):
            audit["error_type"] = "invalid_tool_output"
        audit["latency_ms"] = round((time.monotonic() - started) * 1000)
        attempts.append(audit)
        if not retry or attempt == maximum - 1:
            raise ModelCallError(audit["error_type"], attempts)
        time.sleep(min(2 ** attempt, 8))
    raise ModelCallError("api_error", attempts)


def _reject_constant(value: str):
    raise ValueError(f"nonfinite_json:{value}")

"""Live news search with fail-closed publication-time isolation."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from predict_v2.feature_layer.validation import parse_timestamp
from predict_v2.tool_layer.news_api_pool import NewsApiPool


class NewsTool:
    name = "search_point_in_time_news"

    def __init__(self, project_root: Path, config: dict[str, Any]):
        self.project_root = project_root
        self.config = config
        self.api_pool = NewsApiPool(project_root / config.get("env_file", ".env"),
                                    config.get("tavily_api_key_env", "TAVILY_API_KEY"))

    def run(self, symbol: str, name: str, cutoff_text: str) -> dict[str, Any]:
        cutoff = parse_timestamp(cutoff_text)
        mode = self.config.get("mode", "tavily_live")
        if mode == "disabled":
            return self._result("disabled", [], [], "news_disabled")
        if mode != "tavily_live":
            raise ValueError("invalid_news_mode")
        now = datetime.now(timezone.utc)
        cutoff = min(cutoff, now)
        items = self._tavily(symbol, name, cutoff, now)
        accepted, audit = self._filter(items, symbol, cutoff)
        return self._result("ok" if accepted else "empty", accepted, audit, None)

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        failures = []
        for key in self.api_pool.candidates():
            request = urllib.request.Request("https://api.tavily.com/search",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=int(self.config.get("timeout_seconds", 45))) as response:
                    result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict) or not isinstance(result.get("results"), list):
                    raise ValueError("invalid_news_api_response")
                return result
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                if code not in (401, 403, 429, 432, 433) and not 500 <= code <= 599:
                    raise RuntimeError(f"news_api_http_{code}") from None
                failures.append(f"http_{code}")
            except (OSError, ValueError):
                failures.append("transport_or_response_error")
        raise RuntimeError("news_api_pool_exhausted:" + ",".join(failures)) from None

    def _tavily(self, symbol: str, name: str, cutoff: datetime,
                fetched_at: datetime) -> list[Any]:
        body = {"query": f"{name} {symbol} 股票 新闻", "topic": "news", "search_depth": "basic",
                "max_results": max(1, min(int(self.config.get("max_results", 8)), 20)),
                "include_answer": False, "include_raw_content": False, "include_images": False,
                "end_date": cutoff.date().isoformat()}
        result = self._request(body)
        items = []
        for item in result["results"]:
            if not isinstance(item, dict):
                items.append(item)
                continue
            items.append({"title": item.get("title"), "url": item.get("url"),
                          "content": item.get("content"), "source": "tavily",
                          "published_at": item.get("published_date"),
                          **{field: item.get(field) for field in ("updated_at", "updated_date", "last_updated")},
                          "fetched_at": fetched_at.isoformat(), "symbols": [symbol]})
        return items

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        try:
            return parse_timestamp(value)
        except (TypeError, ValueError):
            if not isinstance(value, str) or not re.fullmatch(
                r"(?:[A-Za-z]{3},\s+)?\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+"
                r"\d{2}:\d{2}:\d{2}\s+(?:[+-]\d{4}|GMT|UTC)", value.strip()
            ):
                raise ValueError("unreliable_news_timestamp") from None
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timestamp_timezone_required")
            return parsed.astimezone(timezone.utc)

    def _filter(self, items: list[Any], symbol: str, cutoff: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted, audit, seen = [], [], set()
        limit = max(1, min(int(self.config.get("max_results", 8)), 20))
        chars = max(0, int(self.config.get("max_content_chars", 600)))
        for position, item in enumerate(items):
            record = {"position": position, "accepted": False}
            audit.append(record)
            if not isinstance(item, dict):
                record["reason"] = "invalid_record"
                continue
            record.update({key: item.get(key) for key in ("title", "url", "source", "published_at", "updated_at", "updated_date", "last_updated", "fetched_at")})
            try:
                published = self._timestamp(item.get("published_at"))
                fetched = parse_timestamp(item.get("fetched_at"))
                updates = [self._timestamp(item[field]) for field in ("updated_at", "updated_date", "last_updated")
                           if item.get(field) is not None]
                updated = max(updates, default=None)
            except (TypeError, ValueError, OverflowError):
                record["reason"] = "missing_or_unreliable_timestamp"
                continue
            if published > cutoff:
                record["reason"] = "published_after_cutoff"
                continue
            if updated is not None and updated > cutoff:
                record["reason"] = "updated_after_cutoff"
                continue
            if any(value < published for value in updates):
                record["reason"] = "updated_before_publication"
                continue
            if fetched < published or (updated is not None and fetched < updated):
                record["reason"] = "fetched_before_publication_or_update"
                continue
            symbols = item.get("symbols") or item.get("index_codes")
            if not isinstance(symbols, list) or symbol not in symbols:
                record["reason"] = "unverified_symbol_relevance"
                continue
            raw_title, raw_url = item.get("title"), item.get("url")
            if not isinstance(raw_title, str) or not isinstance(raw_url, str):
                record["reason"] = "invalid_title_or_url"
                continue
            url = raw_url.split("#", 1)[0].rstrip("/")
            title = re.sub(r"\W+", "", raw_title.casefold())
            identity = (url, title)
            if not url.startswith(("https://", "http://")) or not title:
                record["reason"] = "invalid_title_or_url"
                continue
            if identity in seen:
                record["reason"] = "duplicate"
                continue
            seen.add(identity)
            if len(accepted) >= limit:
                record["reason"] = "result_limit"
                continue
            record.update(accepted=True, reason="within_cutoff", published_at=published.isoformat(), fetched_at=fetched.isoformat())
            accepted.append({"title": raw_title[:200], "url": url,
                             "source": str(item.get("source", "unknown"))[:100],
                             "published_at": published.isoformat(), "fetched_at": fetched.isoformat(),
                             "content": str(item.get("content") or "")[:chars]})
        return accepted, audit

    @staticmethod
    def _result(status: str, events: list[dict[str, Any]], audit: list[dict[str, Any]], reason: str | None):
        return {"schema_version": "news-context-2.0", "status": status, "reason": reason,
                "events": events, "audit": audit, "accepted_count": len(events),
                "policy": "live_search_only; timezone-aware published_at <= min(prediction_cutoff, request_time); "
                          "reject unreliable timestamps and known updates after cutoff; "
                          "live page historical content versions cannot be verified"}

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from predict_v2.feature_layer.pipeline import analyze
from predict_v2.feature_layer.validation import default_cutoff, validate_history
from predict_v2.predict_layer.llm_client import ModelCallError, call_prediction_tool
from predict_v2.predict_layer.orchestrator import Orchestrator
from predict_v2.main import resolve_prediction_dates
from predict_v2.tool_layer.news_tool import NewsTool
from predict_v2.tool_layer.result_tool import validate_submission


def rows(count=80):
    result = []
    for index in range(count):
        close = 10 + index / 100
        result.append({"ts_code": "TEST.SZ", "trade_date": (datetime(2026, 1, 1) + timedelta(days=index)).strftime("%Y%m%d"),
                       "open": close * .998, "high": close * 1.01, "low": close * .99,
                       "close": close, "vol": 1000 + index, "amount": 10000 + index,
                       "name": "娴嬭瘯鑲＄エ", "pct_chg": .1})
    return result


def submission():
    return {"expected_return_pct": .3, "return_interval": {"lower_pct": -1.2, "upper_pct": 1.8},
            "probability_positive": .56, "confidence_level": "low", "analysis": "瓒嬪娍鍜岄噺浠锋俯鍜屼竴鑷淬€?,
            "signal_relationships": ["鐭腑鍛ㄦ湡鏀剁泭鍚屽悜锛屼絾浼樺娍鏈夐檺銆?], "positive_evidence": ["鏀剁泭鍔ㄩ噺涓烘銆?],
            "negative_evidence": ["娉㈠姩浠嶇劧瀛樺湪銆?], "uncertainties": ["鏂伴椈涓虹┖銆?],
            "counter_view": "鐭湡鍙兘鍙戠敓鍧囧€煎洖褰掋€?, "risk_scenarios": ["甯傚満鏁翠綋蹇€熶笅璺屻€?]}


class FeatureTests(unittest.TestCase):
    def test_future_excluded_and_returns_only(self):
        source = rows()
        selected, quality = validate_history(source, "20260320", default_cutoff("20260320"), 60, "TEST.SZ")
        self.assertEqual(quality["status"], "ok")
        self.assertTrue(all(row["trade_date"] < "20260320" for row in selected))
        report = analyze(selected, 15)
        self.assertEqual(report["basis"], "returns_and_relative_values_only")
        compact = json.dumps(report["compact_return_bars"])
        for field in ('"open"', '"high"', '"low"', '"close"'):
            self.assertNotIn(field, compact)
        json.dumps(report, allow_nan=False)

    def test_invalid_data_rejected(self):
        source = rows()
        source[30]["high"] = source[30]["low"] - 1
        selected, quality = validate_history(source, "20260320", default_cutoff("20260320"), 60, "TEST.SZ")
        self.assertEqual(quality["status"], "error")
        self.assertEqual(len(selected), 60)


class NewsTests(unittest.TestCase):
    def test_historical_live_search_uses_cutoff_and_filters_results(self):
        items = [
            {"title": "before", "url": "https://example.com/a", "source": "test", "symbols": ["TEST.SZ"],
             "published_at": "2026-03-19T15:00:00Z", "fetched_at": "2026-09-16T00:00:00Z", "content": "ok"},
            {"title": "future", "url": "https://example.com/b", "source": "test", "symbols": ["TEST.SZ"],
             "published_at": "2026-03-19T17:00:00Z", "fetched_at": "2026-09-16T00:00:00Z", "content": "future"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            tool = NewsTool(Path(temporary), {"mode": "tavily_live", "max_results": 3})
            with patch.object(tool, "_tavily", return_value=items) as search:
                report = tool.run("TEST.SZ", "test", "2026-03-19T16:00:00Z")
        search.assert_called_once()
        self.assertEqual(search.call_args.args[2].isoformat(), "2026-03-19T16:00:00+00:00")
        self.assertEqual([item["title"] for item in report["events"]], ["before"])
        self.assertIn("published_after_cutoff", [item["reason"] for item in report["audit"]])


class ResultToolTests(unittest.TestCase):
    def test_structured_conversion(self):
        value = validate_submission(submission())
        self.assertEqual(value["direction"], "up")
        self.assertEqual(value["candle_class"], "up")
        self.assertEqual(value["expected_pct_change"], .3)

    def test_conflicts_and_nonfinite_rejected(self):
        for field, value in (("probability_positive", .4), ("expected_return_pct", float("nan"))):
            item = submission()
            item[field] = value
            with self.assertRaises(ValueError):
                validate_submission(item)


class FakeResponse:
    status = 200
    headers = {"x-request-id": "request-test"}

    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return json.dumps({"choices": [{"message": self.message}], "usage": {"total_tokens": 12}}).encode()


class LLMClientTests(unittest.TestCase):
    def setUp(self):
        self.model = {"basemodel": "test", "openai_base_url": "https://example.com/v1",
                      "api_key_env": "TEST_V2_KEY", "max_retries": 0, "timeout_seconds": 2}

    @patch.dict(os.environ, {"TEST_V2_KEY": "secret"})
    def test_forced_tool_call(self):
        message = {"content": "杩欐鏅€氭枃鏈笉鑳芥垚涓洪娴?, "tool_calls": [{"function": {
            "name": "submit_prediction", "arguments": json.dumps(submission(), ensure_ascii=False)}}]}
        with patch("urllib.request.urlopen", return_value=FakeResponse(message)):
            result, attempts = call_prediction_tool(self.model, "绯荤粺", "杈撳叆")
        self.assertEqual(result["expected_return_pct"], .3)
        self.assertTrue(attempts[0]["tool_call_received"])

    @patch.dict(os.environ, {"TEST_V2_KEY": "secret"})
    def test_plain_text_rejected(self):
        with patch("urllib.request.urlopen", return_value=FakeResponse({"content": json.dumps(submission())})):
            with self.assertRaises(ModelCallError) as caught:
                call_prediction_tool(self.model, "绯荤粺", "杈撳叆")
        self.assertEqual(caught.exception.category, "invalid_tool_output")


class OrchestratorTests(unittest.TestCase):
    def test_dry_run_and_saved_payload_omit_daily_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data" / "stocks"
            data.mkdir(parents=True)
            payload = {"ts_code": "TEST.SZ", "records": rows()}
            (data / "TEST.SZ.json").write_text(json.dumps(payload), encoding="utf-8")
            config = {"prediction_date": "20260320", "prediction_cutoff_datetime": None,
                      "asset_type": "stock", "symbols": ["TEST.SZ"], "history_days": 60, "compact_days": 15,
                      "data_paths": {"stock": "data/stocks"}, "output_dir": "results", "prompt_profile": "balanced",
                      "news": {"mode": "disabled", "max_results": 3},
                      "model": {"name": "test-v2", "basemodel": "test", "api_key_env": "TEST_V2_KEY",
                                "openai_base_url": "https://example.com/v1", "max_retries": 0},
                      "logging": {"level": "ERROR", "directory": "logs"}}
            profile = {"name": "test", "instruction": "娴嬭瘯"}
            report = Orchestrator(root, config, profile).run("dry_run")
            item = report["payload"]["predictions"][0]
            self.assertNotIn("lookback", item)
            self.assertNotIn('"open"', item["prompt"])
            with patch("predict_v2.predict_layer.orchestrator.call_prediction_tool",
                       return_value=(validate_submission(submission()), [])):
                saved = Orchestrator(root, config, profile).run("predict")
            data = json.loads(Path(saved["output"]).read_text(encoding="utf-8"))
            saved_item = data["predictions"][0]
            self.assertNotIn("lookback", saved_item)
            self.assertNotIn("prompt", saved_item)
            self.assertIn("feature_summary", saved_item)
            self.assertEqual(saved_item["prediction"]["expected_return_pct"], .3)

    def test_date_range_uses_common_trading_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "stocks"
            data.mkdir()
            first = {"records": rows(80)}
            second_rows = rows(80)
            second_rows.pop(75)
            (data / "A.json").write_text(json.dumps(first), encoding="utf-8")
            (data / "B.json").write_text(json.dumps({"records": second_rows}), encoding="utf-8")
            config = {"prediction_date": "", "prediction_start_date": "20260315",
                      "prediction_end_date": "20260320", "asset_type": "stock",
                      "symbols": ["A", "B"], "data_paths": {"stock": str(data)}}
            dates = resolve_prediction_dates(config)
        self.assertNotIn(rows(80)[75]["trade_date"], dates)
        self.assertEqual(dates, sorted(dates))


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from predict_v2.tool_layer.news_api_pool import NewsApiPool, read_env
from predict_v2.tool_layer.news_tool import NewsTool


class NewsApiPoolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = self.root / ".env"
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_dotenv_rotation_deduplication_and_environment_priority(self):
        self.env.write_text("TAVILY_API_KEY_10=ten\nTAVILY_API_KEY_2=two\n"
                            "TAVILY_API_KEY_1=one\nTAVILY_API_KEY_3=one\n"
                            "TAVILY_API_KEY_4= # empty\nTAVILY_API_KEY_OTHER=ignored\n", encoding="utf-8")
        with patch.dict(os.environ, {"TAVILY_API_KEY_2": "override"}):
            pool = NewsApiPool(self.env)
            self.assertEqual(pool.candidates(), ["one", "override", "ten"])
            self.assertEqual(pool.candidates(), ["override", "ten", "one"])
            self.assertEqual(pool.candidates(), ["ten", "one", "override"])
            self.assertEqual(pool.candidates(), ["one", "override", "ten"])

    def test_dotenv_quotes_comments_export_and_no_expansion(self):
        self.env.write_text("\ufeff# ignored\nexport TAVILY_API_KEY_1='first#key' # note\n"
                            'TAVILY_API_KEY_2="${OTHER}"\n'
                            "TAVILY_API_KEY_3=third # note\n", encoding="utf-8")
        self.assertEqual(NewsApiPool(self.env).candidates(), ["first#key", "${OTHER}", "third"])
        self.assertNotIn("TAVILY_API_KEY_1", os.environ)

    def test_single_key_and_custom_prefix(self):
        with patch.dict(os.environ, {"CUSTOM_NEWS": "single", "CUSTOM_NEWS_1": "numbered"}):
            self.assertEqual(NewsApiPool(self.env, "CUSTOM_NEWS").candidates(), ["single", "numbered"])

    def test_missing_or_empty_keys_fail_closed(self):
        for text in (None, "TAVILY_API_KEY_1=\n"):
            with self.subTest(text=text):
                if text is not None:
                    self.env.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "missing_news_api_keys"):
                    NewsApiPool(self.env).candidates()

    def test_invalid_env_does_not_expose_values(self):
        for text in ("INVALID secret-value", "TAVILY_API_KEY_1='secret-value"):
            with self.subTest(text=text):
                self.env.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError) as caught:
                    read_env(self.env)
                self.assertNotIn("secret-value", str(caught.exception))

    def test_thread_safe_rotation(self):
        self.env.write_text("TAVILY_API_KEY_1=one\nTAVILY_API_KEY_2=two\n", encoding="utf-8")
        pool = NewsApiPool(self.env)
        with ThreadPoolExecutor(max_workers=8) as executor:
            starts = list(executor.map(lambda _: pool.candidates()[0], range(40)))
        self.assertEqual(starts.count("one"), 20)
        self.assertEqual(starts.count("two"), 20)


class LiveNewsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".env").write_text("TAVILY_API_KEY_1=first-secret\nTAVILY_API_KEY_2=second-secret\n", encoding="utf-8")
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.tool = NewsTool(self.root, {"max_results": 8})
        self.cutoff = "2026-03-20T00:00:00+08:00"

    @staticmethod
    def response(items=None):
        return io.BytesIO(json.dumps({"results": [] if items is None else items}).encode("utf-8"))

    @staticmethod
    def item(title="before", published="2026-03-19T15:00:00Z", **extra):
        return {"title": title, "url": f"https://example.com/{title}", "source": "test",
                "symbols": ["TEST.SZ"], "published_at": published,
                "fetched_at": "2026-09-16T00:00:00Z", "content": title, **extra}

    def run_items(self, items):
        with patch.object(self.tool, "_tavily", return_value=items):
            return self.tool.run("TEST.SZ", "test", self.cutoff)

    def test_default_live_search_reads_configured_env_and_rotates(self):
        for expected in ("first-secret", "second-secret"):
            with patch("urllib.request.urlopen", return_value=self.response()) as request:
                self.assertEqual(self.tool.run("TEST.SZ", "test", self.cutoff)["status"], "empty")
            sent = request.call_args.args[0]
            self.assertEqual(sent.get_header("Authorization"), f"Bearer {expected}")
            body = json.loads(sent.data)
            self.assertEqual(body["end_date"], "2026-03-19")
            self.assertEqual(body["topic"], "news")
            self.assertFalse(body["include_answer"])
            self.assertFalse(body["include_raw_content"])
            self.assertFalse(body["include_images"])
            self.assertNotIn("time_range", body)
            self.assertEqual(request.call_args.kwargs["timeout"], 45)

    def test_relative_env_path_is_resolved_from_project_root(self):
        (self.root / "custom.env").write_text("TAVILY_API_KEY_1=custom-secret", encoding="utf-8")
        tool = NewsTool(self.root, {"env_file": "custom.env"})
        self.assertEqual(tool.api_pool.candidates(), ["custom-secret"])

    def test_each_retryable_http_error_switches_key(self):
        for code in (401, 403, 429, 432, 433, 500, 503):
            with self.subTest(code=code):
                tool = NewsTool(self.root, {})
                error = urllib.error.HTTPError("https://api.tavily.com/search", code,
                                               "first-secret", {}, io.BytesIO(b"first-secret"))
                with patch("urllib.request.urlopen", side_effect=[error, self.response()]) as request:
                    report = tool.run("TEST.SZ", "test", self.cutoff)
                self.assertEqual(report["status"], "empty")
                self.assertEqual([call.args[0].get_header("Authorization") for call in request.call_args_list],
                                 ["Bearer first-secret", "Bearer second-secret"])
                self.assertTrue(error.closed)

    def test_transport_timeout_and_invalid_response_switch_key(self):
        for failed in (urllib.error.URLError("first-secret"), TimeoutError("first-secret"),
                       io.BytesIO(b"not-json"), io.BytesIO(b'{"error":"first-secret"}')):
            with self.subTest(failed_type=type(failed).__name__):
                tool = NewsTool(self.root, {})
                with patch("urllib.request.urlopen", side_effect=[failed, self.response()]) as request:
                    self.assertEqual(tool.run("TEST.SZ", "test", self.cutoff)["status"], "empty")
                self.assertEqual(request.call_count, 2)

    def test_pool_exhaustion_is_bounded_and_sanitized(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("first-secret")) as request:
            with self.assertRaisesRegex(RuntimeError, "news_api_pool_exhausted") as caught:
                self.tool.run("TEST.SZ", "test", self.cutoff)
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("first-secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_non_retryable_http_error_is_sanitized(self):
        error = urllib.error.HTTPError("https://api.tavily.com/search", 400, "first-secret", {}, io.BytesIO(b"first-secret"))
        with patch("urllib.request.urlopen", side_effect=error) as request:
            with self.assertRaisesRegex(RuntimeError, "^news_api_http_400$"):
                self.tool.run("TEST.SZ", "test", self.cutoff)
        self.assertEqual(request.call_count, 1)
        self.assertTrue(error.closed)

    def test_exact_cutoff_timezones_and_future_rejection(self):
        report = self.run_items([
            self.item(), self.item("boundary", "2026-03-20T00:00:00+08:00"),
            self.item("future", "2026-03-20T00:00:00.000001+08:00"),
            self.item("rfc", "Thu, 19 Mar 2026 16:00:00 GMT"),
            self.item("rfc_future", "Fri, 20 Mar 2026 00:00:01 +0800"),
        ])
        self.assertEqual([item["title"] for item in report["events"]], ["before", "boundary", "rfc"])
        self.assertEqual(sum(item.get("reason") == "published_after_cutoff" for item in report["audit"]), 2)
        self.assertNotIn('"future"', json.dumps(report["events"]))

    def test_unreliable_publication_times_are_rejected(self):
        for published in (None, "", "2026-03-18", "2026-03-18T00:00:00", "yesterday",
                          "Thu, 19 Mar 2026 15:00:00", "Thu, 19 Mar 2026 15:00:00 -0000", 123):
            with self.subTest(published=published):
                report = self.run_items([self.item(published=published)])
                self.assertEqual(report["accepted_count"], 0)
                self.assertEqual(report["audit"][0]["reason"], "missing_or_unreliable_timestamp")

    def test_known_updates_are_time_filtered(self):
        for updated, reason in (("2026-03-19T17:00:00Z", "updated_after_cutoff"),
                                ("2026-03-19T14:00:00Z", "updated_before_publication"),
                                ("2026-03-19", "missing_or_unreliable_timestamp"),
                                ("", "missing_or_unreliable_timestamp")):
            with self.subTest(updated=updated):
                report = self.run_items([self.item(updated_at=updated)])
                self.assertEqual(report["accepted_count"], 0)
                self.assertEqual(report["audit"][0]["reason"], reason)
        self.assertEqual(self.run_items([self.item(updated_at="2026-03-19T16:00:00Z")])["accepted_count"], 1)

    def test_provider_results_are_normalized_before_filtering(self):
        results = [{"title": "accepted", "url": "https://example.com/ok", "content": "ok",
                    "published_date": "Thu, 19 Mar 2026 15:00:00 GMT"},
                   {"title": "updated", "url": "https://example.com/updated", "content": "future",
                    "published_date": "2026-03-19T15:00:00Z", "updated_date": "2026-03-19T17:00:00Z"}, None]
        with patch("urllib.request.urlopen", return_value=self.response(results)):
            report = self.tool.run("TEST.SZ", "test", self.cutoff)
        self.assertEqual([item["title"] for item in report["events"]], ["accepted"])
        self.assertEqual([item["reason"] for item in report["audit"]],
                         ["within_cutoff", "updated_after_cutoff", "invalid_record"])

    def test_all_provided_update_fields_must_be_safe(self):
        report = self.run_items([self.item(updated_at="2026-03-19T15:30:00Z",
                                          last_updated="2026-03-19T17:00:00Z")])
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["audit"][0]["reason"], "updated_after_cutoff")

    def test_each_backtest_date_has_its_own_request_cutoff(self):
        with patch("urllib.request.urlopen", side_effect=[self.response(), self.response()]) as request:
            self.tool.run("TEST.SZ", "test", "2026-03-19T00:00:00+08:00")
            self.tool.run("TEST.SZ", "test", "2026-03-20T00:00:00+08:00")
        self.assertEqual([json.loads(call.args[0].data)["end_date"] for call in request.call_args_list],
                         ["2026-03-18", "2026-03-19"])

    def test_repeated_backtest_searches_never_read_or_write_news(self):
        before = {path.name for path in self.root.iterdir()}
        with patch("urllib.request.urlopen", side_effect=[self.response(), self.response()]) as request:
            self.tool.run("TEST.SZ", "test", self.cutoff)
            self.tool.run("TEST.SZ", "test", self.cutoff)
        self.assertEqual(request.call_count, 2)
        self.assertEqual({path.name for path in self.root.iterdir()}, before)
        self.assertFalse(hasattr(self.tool, "_load_cache"))

    def test_invalid_mode_rejected_and_disabled_never_reads_keys(self):
        with patch.object(self.tool.api_pool, "candidates") as keys:
            self.tool.config["mode"] = "disabled"
            self.assertEqual(self.tool.run("TEST.SZ", "test", self.cutoff)["status"], "disabled")
            self.tool.config["mode"] = "local_cache"
            with self.assertRaisesRegex(ValueError, "invalid_news_mode"):
                self.tool.run("TEST.SZ", "test", self.cutoff)
        keys.assert_not_called()

    def test_request_time_caps_future_prediction_cutoff(self):
        now = datetime(2026, 3, 19, 16, tzinfo=timezone.utc)
        with patch("predict_v2.tool_layer.news_tool.datetime") as clock:
            clock.now.return_value = now
            with patch.object(self.tool, "_tavily", return_value=[self.item("future", "2026-03-19T17:00:00Z")]) as search:
                report = self.tool.run("TEST.SZ", "test", "2099-01-01T00:00:00Z")
        self.assertEqual(search.call_args.args[2], now)
        self.assertEqual(report["accepted_count"], 0)

    def test_invalid_records_duplicates_limits_and_content_truncation(self):
        self.tool.config.update(max_results=1, max_content_chars=3)
        report = self.run_items([None, self.item(title=None), self.item(), self.item(), self.item("extra")])
        self.assertEqual(report["accepted_count"], 1)
        self.assertEqual(report["events"][0]["content"], "bef")
        self.assertEqual([item["reason"] for item in report["audit"]],
                         ["invalid_record", "invalid_title_or_url", "within_cutoff", "duplicate", "result_limit"])


if __name__ == "__main__":
    unittest.main()

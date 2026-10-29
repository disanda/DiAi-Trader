"""Trusted orchestration of tools, model tool-call and compatible storage."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from predict_v2.logs_layer.logger import RunLogger
from predict_v2.predict_layer.llm_client import ModelCallError, call_prediction_tool
from predict_v2.predict_layer.prompts import SYSTEM_PROMPT, build_prompt
from predict_v2.tool_layer.feature_tool import FeatureTool
from predict_v2.tool_layer.market_data_tool import MarketDataTool
from predict_v2.tool_layer.news_tool import NewsTool
from predict_v2.tool_layer.result_tool import save_result


class Orchestrator:
    def __init__(self, project_root: Path, config: dict[str, Any], profile: dict[str, str]):
        self.root = project_root
        self.config = config
        self.profile = profile
        self.run_id = uuid.uuid4().hex
        log_dir = (project_root / config["logging"]["directory"]).resolve()
        self.logger = RunLogger(log_dir, self.run_id, config["logging"].get("level", "INFO"))
        self.market_tool = MarketDataTool(project_root, config["data_paths"])
        self.feature_tool = FeatureTool()
        self.news_tool = NewsTool(project_root, config["news"])

    def run(self, mode: str) -> dict[str, Any]:
        model = self.config["model"]
        date = str(self.config["prediction_date"]).replace("-", "")
        output = self._output_path(model["name"], date)
        if mode == "predict" and output.exists():
            raise FileExistsError(f"refusing_to_overwrite:{output}")
        self.logger.log("INFO", "run_started", mode=mode, prediction_date=date,
                        model_name=model["basemodel"], symbols=self.config["symbols"])
        predictions = []
        for symbol in self.config["symbols"]:
            predictions.append(self._predict_symbol(symbol, mode))
        payload = {"agent_name": model["name"], "prediction_date": date,
                   "generated_at": datetime.now(timezone.utc).isoformat(),
                   "lookback_days": self.config["history_days"],
                   "data_policy": "Point-in-time validated relative features; model output is a predicted OHLC candle accepted only through submit_prediction tool",
                   "predictions": predictions, "schema_version": "predict-v2.0", "run_id": self.run_id,
                   "model_name": model["basemodel"], "prompt_profile": self.config["prompt_profile"]}
        if mode == "predict":
            save_result(output, payload)
            self.logger.log("INFO", "result_saved", path=str(output),
                            successes=sum("prediction" in item for item in predictions),
                            failures=sum("error" in item for item in predictions))
        self.logger.log("INFO", "run_finished", mode=mode)
        return {"mode": mode, "run_id": self.run_id,
                "output": str(output) if mode == "predict" else None, "payload": payload}

    def _predict_symbol(self, symbol: str, mode: str) -> dict[str, Any]:
        date = self.config["prediction_date"]
        try:
            market = self.market_tool.run(self.config["asset_type"], symbol, date,
                                          self.config.get("prediction_cutoff_datetime"),
                                          self.config["history_days"])
            self.logger.log("INFO", "tool_return", tool=self.market_tool.name, symbol=symbol,
                            status=market["data_quality"]["status"], rows=len(market["rows"]))
            if market["data_quality"]["status"] == "error":
                raise ValueError("market_data_quality_failed")
            feature_report = self.feature_tool.run(market["rows"], self.config["compact_days"])
            self.logger.log("INFO", "tool_return", tool=self.feature_tool.name, symbol=symbol,
                            status="ok", feature_count=len(feature_report["features"]),
                            signal_count=len(feature_report["signals"]))
            news = self.news_tool.run(symbol, market["name"], market["cutoff"])
            self.logger.log("INFO", "tool_return", tool=self.news_tool.name, symbol=symbol,
                            status=news["status"], accepted=news["accepted_count"],
                            rejected=len(news["audit"]) - news["accepted_count"])
            reference_close = float(market["rows"][-1]["close"])
            context = {"target": {"symbol": symbol, "name": market["name"],
                                   "asset_type": market["asset_type"], "prediction_date": market["prediction_date"],
                                   "prediction_cutoff": market["cutoff"],
                                   "target_definition": "next-session OHLC candle; use reference_close as the latest known close",
                                   "reference_close": reference_close},
                       "data_quality": market["data_quality"], "feature_report": feature_report,
                       "news_context": {key: news[key] for key in ("schema_version", "status", "reason", "events", "accepted_count", "policy")}}
            prompt = build_prompt(context, self.profile)
            base = {"ts_code": symbol, "name": market["name"], "as_of_date": market["data_quality"]["coverage_end"],
                    "data_quality": market["data_quality"],
                    "feature_summary": {"schema_version": feature_report["schema_version"],
                                        "coverage": feature_report["coverage"], "features": feature_report["features"],
                                        "signals": feature_report["signals"], "input_sha256": feature_report["input_sha256"]},
                    "news_status": news["status"], "news_audit": news["audit"],
                    "news_context": news["events"] or None,
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
            if mode in ("dry_run", "validate"):
                return {**base, "status": mode, **({"prompt": prompt} if mode == "dry_run" else {})}
            self.logger.log("INFO", "model_request_started", symbol=symbol, model_name=self.config["model"]["basemodel"],
                            required_tool="submit_prediction")
            prediction, attempts = call_prediction_tool(self.config["model"], SYSTEM_PROMPT, prompt,
                                                        reference_close=reference_close)
            self.logger.log("INFO", "model_tool_return", symbol=symbol, tool="submit_prediction",
                            predicted_open=prediction["predicted_open"],
                            predicted_high=prediction["predicted_high"],
                            predicted_low=prediction["predicted_low"],
                            predicted_close=prediction["predicted_close"], attempts=len(attempts))
            actual = self._actual(market["source_path"], date)
            return {**base, "prediction": prediction, "model_attempts": attempts, "actual": actual,
                    "verification": None if actual is None else {
                        "direction_correct": prediction["direction"] == actual["direction"],
                        "candle_correct": prediction["candle_class"] == actual["candle_class"]}}
        except ModelCallError as exc:
            self.logger.log("ERROR", "model_failed", symbol=symbol, error_type=exc.category, attempts=len(exc.attempts))
            return {"ts_code": symbol, "name": symbol, "error": exc.category,
                    "error_type": exc.category, "model_attempts": exc.attempts}
        except Exception as exc:
            category = "data_or_tool_error"
            self.logger.log("ERROR", "symbol_failed", symbol=symbol, error_type=type(exc).__name__)
            return {"ts_code": symbol, "name": symbol, "error": str(exc), "error_type": category}

    def _actual(self, relative_path: str, date: str) -> dict[str, Any] | None:
        payload = json.loads((self.root / relative_path).read_text(encoding="utf-8-sig"))
        matches = [row for row in payload["records"] if str(row.get("trade_date")) == str(date).replace("-", "")]
        if len(matches) != 1:
            return None
        change = float(matches[0]["pct_chg"])
        candle = "strong_down" if change <= -1 else "down" if change < 0 else "up" if change < 1 else "strong_up"
        return {"trade_date": str(date).replace("-", ""), "pct_chg": change,
                "direction": "up" if change >= 0 else "down", "candle_class": candle,
                "open": matches[0].get("open"), "high": matches[0].get("high"),
                "low": matches[0].get("low"), "close": matches[0].get("close")}

    def _output_path(self, name: str, date: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "predict_v2"
        return (self.root / self.config["output_dir"] / safe / f"{date}.json").resolve()

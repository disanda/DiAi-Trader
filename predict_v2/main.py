"""CLI entry point for predict_v2."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from predict_v2.predict_layer.orchestrator import Orchestrator
from predict_v2.feature_layer.validation import date_key
from predict_v2.tool_layer.news_api_pool import read_env

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    for key, value in read_env(ROOT / ".env").items():
        os.environ.setdefault(key, value)


def validate_config(config: dict, prompts: dict, mode: str) -> None:
    errors = []
    if mode not in ("dry_run", "validate", "predict"):
        errors.append("mode must be dry_run, validate or predict")
    if config.get("asset_type") not in ("stock", "index", "etf"):
        errors.append("invalid asset_type")
    if not isinstance(config.get("symbols"), list) or not config["symbols"]:
        errors.append("symbols must be a non-empty array")
    elif len(config["symbols"]) != len(set(config["symbols"])):
        errors.append("symbols must not contain duplicates")
    if type(config.get("history_days")) is not int or not 60 <= config["history_days"] <= 250:
        errors.append("history_days must be 60..250")
    if type(config.get("compact_days")) is not int or not 10 <= config["compact_days"] <= 20:
        errors.append("compact_days must be 10..20")
    if config.get("prompt_profile") not in prompts:
        errors.append("unknown prompt_profile")
    try:
        if config.get("prediction_date"):
            date_key(config["prediction_date"])
        else:
            start = date_key(config.get("prediction_start_date"))
            end = date_key(config.get("prediction_end_date"))
            if start > end:
                errors.append("prediction_start_date must not exceed prediction_end_date")
            if config.get("prediction_cutoff_datetime"):
                errors.append("prediction_cutoff_datetime is only supported for a single prediction_date")
    except (TypeError, ValueError):
        errors.append("invalid prediction date configuration")
    model = config.get("model", {})
    for field in ("name", "basemodel", "openai_base_url", "api_key_env"):
        if not isinstance(model.get(field), str) or not model[field].strip():
            errors.append(f"model.{field} is required")
    if mode == "predict" and not os.environ.get(model.get("api_key_env", "")):
        errors.append(f"missing environment variable: {model.get('api_key_env')}")
    try:
        endpoint = urlsplit(model.get("openai_base_url", ""))
        if endpoint.scheme != "https" or not endpoint.netloc or endpoint.username or endpoint.password:
            errors.append("model.openai_base_url must be HTTPS without credentials")
    except ValueError:
        errors.append("invalid model.openai_base_url")
    if errors:
        raise ValueError("; ".join(errors))


def resolve_prediction_dates(config: dict) -> list[str]:
    if config.get("prediction_date"):
        return [date_key(config["prediction_date"])]
    root = Path(__file__).resolve().parent.parent
    data_dir = (root / config["data_paths"][config["asset_type"]]).resolve()
    common_dates: set[str] | None = None
    for symbol in config["symbols"]:
        path = data_dir / f"{symbol}.json"
        if path.parent != data_dir or not path.is_file():
            raise FileNotFoundError(f"market_data_not_found:{symbol}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        dates = set()
        for row in payload.get("records", []):
            try:
                dates.add(date_key(row["trade_date"]))
            except (KeyError, TypeError, ValueError):
                continue
        common_dates = dates if common_dates is None else common_dates & dates
    start = date_key(config["prediction_start_date"])
    end = date_key(config["prediction_end_date"])
    result = sorted(day for day in (common_dates or set()) if start <= day <= end)
    if not result:
        raise ValueError("date range contains no common trading sessions")
    return result


def preflight_outputs(config: dict, dates: list[str], mode: str) -> None:
    if mode != "predict":
        return
    root = Path(__file__).resolve().parent.parent
    name = "".join(character if character.isalnum() or character in "._-" else "_"
                   for character in config["model"]["name"]).strip("._") or "predict_v2"
    output_dir = (root / config["output_dir"] / name).resolve()
    collisions = [str(output_dir / f"{day}.json") for day in dates if (output_dir / f"{day}.json").exists()]
    if collisions:
        raise FileExistsError("refusing_to_overwrite_range:" + ",".join(collisions))


def main() -> None:
    parser = argparse.ArgumentParser(description="OHLC 特征 + 时间隔离新闻 + 强制工具提交的 LLM 预测")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--date", help="覆盖 config，预测单个交易日")
    date_group.add_argument("--start", help="覆盖 config，预测日期范围起点；必须同时提供 --end")
    parser.add_argument("--end", help="覆盖 config，预测日期范围终点；必须同时提供 --start")
    parser.add_argument("--mode", choices=("dry_run", "validate", "predict"), help="覆盖 config 中的 mode")
    args = parser.parse_args()
    load_env()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    prompts = json.loads(Path(__file__).with_name("prompt.json").read_text(encoding="utf-8-sig"))
    if args.date:
        config["prediction_date"] = args.date
    if bool(args.start) != bool(args.end):
        parser.error("--start 和 --end 必须同时提供")
    if args.start:
        config["prediction_date"] = ""
        config["prediction_start_date"] = args.start
        config["prediction_end_date"] = args.end
    mode = args.mode or config.get("mode", "dry_run")
    validate_config(config, prompts, mode)
    dates = resolve_prediction_dates(config)
    preflight_outputs(config, dates, mode)
    print("predict_v2 初始化")
    print(f"模式: {mode}")
    print(f"标的类型: {config['asset_type']}; 标的数量: {len(config['symbols'])}")
    print(f"历史窗口: {config['history_days']} 日; 紧凑收益序列: {config['compact_days']} 日")
    print(f"模型: {config['model']['basemodel']}; 输出名: {config['model']['name']}")
    print(f"新闻模式: {config['news']['mode']}; 提示词: {config['prompt_profile']}")
    print(f"预测日期: {dates[0]} 至 {dates[-1]}; 共 {len(dates)} 个共同交易日")
    summaries = []
    for position, date in enumerate(dates, 1):
        run_config = copy.deepcopy(config)
        run_config["prediction_date"] = date
        print(f"[{position}/{len(dates)}] 处理 {date}")
        report = Orchestrator(ROOT, run_config, prompts[config["prompt_profile"]]).run(mode)
        if mode == "dry_run":
            summaries.extend({"prediction_date": date, "ts_code": item["ts_code"],
                              "status": item.get("status", "error"),
                              "feature_count": len(item.get("feature_summary", {}).get("features", {})),
                              "signal_count": len(item.get("feature_summary", {}).get("signals", [])),
                              "news_status": item.get("news_status"),
                              "prompt_chars": len(item.get("prompt", ""))}
                             for item in report["payload"]["predictions"])
        elif report["output"]:
            print(f"结果已保存: {report['output']}")
    if mode == "dry_run":
        print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""JSON-lines logging with run context and no secret fields."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunLogger:
    def __init__(self, directory: Path, run_id: str, level: str = "INFO"):
        directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.path = directory / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        self.minimum = getattr(logging, level.upper(), logging.INFO)

    def log(self, level: str, event: str, **fields: Any) -> None:
        numeric = getattr(logging, level.upper(), logging.INFO)
        if numeric < self.minimum:
            return
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level.upper(),
                  "event": event, "run_id": self.run_id, **fields}
        line = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line)

"""Independent dotenv-backed Tavily credential rotation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", text)
        if not match:
            raise ValueError("invalid_env_assignment")
        name, value = match.groups()
        if value.startswith(("'", '"')):
            quoted = re.fullmatch(r"(['\"])(.*?)\1\s*(?:#.*)?", value)
            if not quoted:
                raise ValueError("invalid_env_quoted_value")
            value = quoted.group(2)
        elif value.startswith("#"):
            value = ""
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        values[name] = value
    return values


class NewsApiPool:
    def __init__(self, env_path: Path, key_env: str = "TAVILY_API_KEY"):
        self.env_path = env_path
        self.key_env = key_env
        self._keys: list[str] = []
        self._next = 0
        self._lock = Lock()

    def _load(self) -> list[str]:
        values = read_env(self.env_path)
        values.update(os.environ)
        names = [self.key_env] + sorted(
            (name for name in values if name.startswith(self.key_env + "_")
             and name[len(self.key_env) + 1:].isdigit()),
            key=lambda name: (int(name[len(self.key_env) + 1:]), name))
        keys = []
        for name in names:
            value = values.get(name, "").strip()
            if "\r" in value or "\n" in value:
                raise ValueError("invalid_news_api_key")
            if value and value not in keys:
                keys.append(value)
        if not keys:
            raise ValueError("missing_news_api_keys")
        return keys

    def candidates(self) -> list[str]:
        with self._lock:
            if not self._keys:
                self._keys = self._load()
            start = self._next
            self._next = (start + 1) % len(self._keys)
            return self._keys[start:] + self._keys[:start]

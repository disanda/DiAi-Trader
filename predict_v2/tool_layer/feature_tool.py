"""Feature analysis tool wrapper."""

from __future__ import annotations

from typing import Any

from predict_v2.feature_layer.pipeline import analyze


class FeatureTool:
    name = "analyze_return_features"

    def run(self, rows: list[dict[str, Any]], compact_days: int) -> dict[str, Any]:
        if len(rows) < 60:
            raise ValueError("feature_tool_requires_60_sessions")
        return analyze(rows, compact_days)

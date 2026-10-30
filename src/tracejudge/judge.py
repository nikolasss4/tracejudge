"""LLM-as-judge (placeholder until the judge lands)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tracejudge.runner import JudgeFn
from tracejudge.suite import Suite


def make_judge(
    suite: Suite, model: str | None = None, record: bool = False, base_dir: Path | None = None
) -> tuple[JudgeFn | None, dict[str, Any]]:
    return None, {}

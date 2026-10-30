from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from tracejudge.models import ScoreResult, Trace


@dataclass
class ScoreContext:
    output: Any
    trace: Trace
    error: str | None = None
    input: Any = None
    case_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Scorer(Protocol):
    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]: ...


def run_scorers(scorers: list[Scorer], ctx: ScoreContext) -> list[ScoreResult]:
    results: list[ScoreResult] = []
    for scorer in scorers:
        try:
            results.extend(scorer(ctx))
        except Exception as exc:  # a broken scorer must not take down the whole run
            name = getattr(scorer, "name", type(scorer).__name__)
            results.append(
                ScoreResult(
                    scorer="scorer_error",
                    name=str(name),
                    passed=False,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
    return results

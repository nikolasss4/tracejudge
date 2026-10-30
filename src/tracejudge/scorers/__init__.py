"""Scorers turn (case expectations, agent output, trace) into pass/fail verdicts."""

from tracejudge.scorers.base import ScoreContext, Scorer, run_scorers
from tracejudge.scorers.deterministic import build_scorers

__all__ = ["ScoreContext", "Scorer", "build_scorers", "run_scorers"]

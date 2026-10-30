"""Judge calibration: how often does the LLM judge agree with human labels?

Humans label a sample of trials pass/fail per criterion (in the viewer's labeling screen or with
``tracejudge label``). For every criterion we then report raw agreement, Cohen's kappa (agreement
corrected for chance, which matters when most trials pass) and the confusion matrix, plus the
disagreements themselves so the rubric can be fixed where the judge goes wrong.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from tracejudge.models import CaseResult
from tracejudge.store import Store


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa for two binary raters. None when it is undefined (one class only)."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    p_a = sum(a for a, _ in pairs) / n
    p_b = sum(b for _, b in pairs) / n
    pe = p_a * p_b + (1 - p_a) * (1 - p_b)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def interpret_kappa(k: float | None) -> str:
    """Landis & Koch (1977) bands."""
    if k is None:
        return "undefined"
    if k < 0:
        return "poor"
    for limit, word in ((0.2, "slight"), (0.4, "fair"), (0.6, "moderate"), (0.8, "substantial")):
        if k <= limit:
            return word
    return "almost perfect"


@dataclass
class Disagreement:
    case_result_id: str
    case_id: str
    trial: int
    judge_pass: bool
    human_pass: bool
    judge_reason: str
    human_note: str


@dataclass
class CriterionCalibration:
    criterion: str
    n: int = 0
    agree: int = 0
    # judge verdict vs human label
    judge_pass_human_pass: int = 0
    judge_pass_human_fail: int = 0
    judge_fail_human_pass: int = 0
    judge_fail_human_fail: int = 0
    pairs: list[tuple[bool, bool]] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)

    @property
    def agreement(self) -> float | None:
        return self.agree / self.n if self.n else None

    @property
    def kappa(self) -> float | None:
        return cohen_kappa(self.pairs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "n": self.n,
            "agreement": self.agreement,
            "kappa": self.kappa,
            "kappa_band": interpret_kappa(self.kappa),
            "confusion": {
                "judge_pass_human_pass": self.judge_pass_human_pass,
                "judge_pass_human_fail": self.judge_pass_human_fail,
                "judge_fail_human_pass": self.judge_fail_human_pass,
                "judge_fail_human_fail": self.judge_fail_human_fail,
            },
            "disagreements": [d.__dict__ for d in self.disagreements],
        }


def judge_verdicts(cr: CaseResult) -> dict[str, tuple[bool, str]]:
    return {
        s.name: (s.passed, s.reason)
        for s in cr.scores
        if s.scorer == "judge" and s.passed is not None
    }


def calibrate(store: Store, run_ids: list[str] | None = None) -> list[CriterionCalibration]:
    """Compare judge verdicts with human labels, per criterion."""
    runs = run_ids or [r.run_id for r in store.list_runs()]
    results: dict[str, CriterionCalibration] = {}
    for run_id in runs:
        labels = {(lb.case_result_id, lb.criterion): lb for lb in store.labels(run_id)}
        if not labels:
            continue
        for cr in store.case_results(run_id):
            for criterion, (judge_pass, reason) in judge_verdicts(cr).items():
                lb = labels.get((cr.id, criterion))
                if lb is None:
                    continue
                cal = results.setdefault(criterion, CriterionCalibration(criterion))
                human = lb.human_pass
                cal.n += 1
                cal.pairs.append((judge_pass, human))
                if judge_pass == human:
                    cal.agree += 1
                else:
                    cal.disagreements.append(
                        Disagreement(
                            cr.id, cr.case_id, cr.trial, judge_pass, human, reason, lb.note
                        )
                    )
                attr = (
                    f"judge_{'pass' if judge_pass else 'fail'}_human_{'pass' if human else 'fail'}"
                )
                setattr(cal, attr, getattr(cal, attr) + 1)
    return sorted(results.values(), key=lambda c: c.criterion)


def label_queue(
    store: Store, run_id: str, criterion: str | None = None, limit: int = 100, seed: int = 0
) -> list[tuple[CaseResult, str]]:
    """(trial, criterion) pairs that still need a human label.

    Sampled so judge-pass and judge-fail verdicts are both well represented: if the judge passes
    95% of trials, a uniform sample would almost never test whether its failures are right.
    """
    labelled = {(lb.case_result_id, lb.criterion) for lb in store.labels(run_id)}
    by_verdict: dict[bool, list[tuple[CaseResult, str]]] = {True: [], False: []}
    for cr in store.case_results(run_id):
        for name, (passed, _) in judge_verdicts(cr).items():
            if criterion and name != criterion:
                continue
            if (cr.id, name) not in labelled:
                by_verdict[passed].append((cr, name))
    rng = random.Random(seed)
    for items in by_verdict.values():
        rng.shuffle(items)
    fails, passes = by_verdict[False], by_verdict[True]
    take_fail = min(len(fails), max(limit // 2, limit - len(passes)))
    queue = fails[:take_fail] + passes[: limit - take_fail]
    rng.shuffle(queue)
    return queue

"""Compare two eval runs: which cases flipped, what got slower or pricier, and is it noise?"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from tracejudge.models import CaseResult, Run
from tracejudge.stats import fisher_exact
from tracejudge.store import Store

Status = Literal["regressed", "fixed", "degraded", "improved", "unchanged", "added", "removed"]


@dataclass
class CaseDiff:
    case_id: str
    status: Status
    a_passed: int = 0
    a_trials: int = 0
    b_passed: int = 0
    b_trials: int = 0
    a_cost: float = 0.0
    b_cost: float = 0.0
    a_latency_ms: float = 0.0
    b_latency_ms: float = 0.0
    new_failures: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    trajectory_a: list[str] = field(default_factory=list)
    trajectory_b: list[str] = field(default_factory=list)
    diverged_at: int | None = None
    trial_a: str | None = None
    trial_b: str | None = None
    p_value: float | None = None

    @property
    def a_rate(self) -> float:
        return self.a_passed / self.a_trials if self.a_trials else 0.0

    @property
    def b_rate(self) -> float:
        return self.b_passed / self.b_trials if self.b_trials else 0.0


@dataclass
class RunDiff:
    a: Run
    b: Run
    cases: list[CaseDiff]
    pass_rate_a: float
    pass_rate_b: float
    p_value: float
    cost_a: float
    cost_b: float
    latency_p50_a: float
    latency_p50_b: float
    latency_p95_a: float
    latency_p95_b: float
    notes: list[str] = field(default_factory=list)

    def by_status(self, status: Status) -> list[CaseDiff]:
        return [c for c in self.cases if c.status == status]

    @property
    def pass_rate_delta(self) -> float:
        return self.pass_rate_b - self.pass_rate_a

    @property
    def cost_change(self) -> float | None:
        return (self.cost_b - self.cost_a) / self.cost_a if self.cost_a else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a.model_dump(mode="json", exclude={"summary"}),
            "b": self.b.model_dump(mode="json", exclude={"summary"}),
            "pass_rate_a": self.pass_rate_a,
            "pass_rate_b": self.pass_rate_b,
            "pass_rate_delta": self.pass_rate_delta,
            "p_value": self.p_value,
            "cost_per_trial_a": self.cost_a,
            "cost_per_trial_b": self.cost_b,
            "cost_change": self.cost_change,
            "latency_p50_a": self.latency_p50_a,
            "latency_p50_b": self.latency_p50_b,
            "latency_p95_a": self.latency_p95_a,
            "latency_p95_b": self.latency_p95_b,
            "notes": self.notes,
            "cases": [{**asdict(c), "a_rate": c.a_rate, "b_rate": c.b_rate} for c in self.cases],
        }


def _failing(cr: CaseResult) -> set[str]:
    return {f"{s.scorer}:{s.name}" for s in cr.scores if s.passed is False}


def _tools(store: Store, cr: CaseResult) -> list[str]:
    t = store.get_trace(cr.trace_id) if cr.trace_id else None
    return [c.name for c in t.tool_calls()] if t else []


def _first_divergence(a: list[str], b: list[str]) -> int | None:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def _status(a: list[CaseResult], b: list[CaseResult]) -> Status:
    if not a:
        return "added"
    if not b:
        return "removed"
    ra = sum(r.passed for r in a) / len(a)
    rb = sum(r.passed for r in b) / len(b)
    if ra > 0.5 >= rb:
        return "regressed"
    if rb > 0.5 >= ra:
        return "fixed"
    if rb < ra:
        return "degraded"
    if rb > ra:
        return "improved"
    return "unchanged"


def diff_runs(store: Store, a: Run, b: Run) -> RunDiff:
    """Per-case comparison. A case passes when most of its trials pass; a pass->fail change of
    that majority is a *regression*, a smaller drop in its pass rate is *degraded*."""
    ra: dict[str, list[CaseResult]] = defaultdict(list)
    rb: dict[str, list[CaseResult]] = defaultdict(list)
    for r in store.case_results(a.run_id):
        ra[r.case_id].append(r)
    for r in store.case_results(b.run_id):
        rb[r.case_id].append(r)

    cases: list[CaseDiff] = []
    for case_id in sorted(set(ra) | set(rb)):
        xa, xb = ra.get(case_id, []), rb.get(case_id, [])
        cd = CaseDiff(case_id=case_id, status=_status(xa, xb))
        cd.a_trials, cd.b_trials = len(xa), len(xb)
        cd.a_passed, cd.b_passed = sum(r.passed for r in xa), sum(r.passed for r in xb)
        if xa:
            cd.a_cost = sum(r.cost_usd for r in xa) / len(xa)
            cd.a_latency_ms = sum(r.latency_ms for r in xa) / len(xa)
        if xb:
            cd.b_cost = sum(r.cost_usd for r in xb) / len(xb)
            cd.b_latency_ms = sum(r.latency_ms for r in xb) / len(xb)
        if xa and xb:
            cd.p_value = fisher_exact(
                cd.a_passed, cd.a_trials - cd.a_passed, cd.b_passed, cd.b_trials - cd.b_passed
            )
            fail_a = set().union(*(_failing(r) for r in xa))
            failing_b = [r for r in xb if not r.passed]
            cd.new_failures = sorted(set().union(*(_failing(r) for r in xb)) - fail_a)
            if cd.status in ("regressed", "degraded", "fixed", "improved"):
                # Show a representative pair: a passing A trial against a failing B trial
                # (or the reverse for fixes), to locate where the trajectories split.
                want_a, want_b = (
                    (True, False) if cd.status in ("regressed", "degraded") else (False, True)
                )
                ta = next((r for r in xa if r.passed == want_a), xa[0])
                tb = next((r for r in xb if r.passed == want_b), xb[0])
                cd.trial_a, cd.trial_b = ta.id, tb.id
                cd.trajectory_a, cd.trajectory_b = _tools(store, ta), _tools(store, tb)
                cd.diverged_at = _first_divergence(cd.trajectory_a, cd.trajectory_b)
            for r in failing_b[:1]:
                cd.reasons = [
                    f"{s.scorer}:{s.name}: {s.reason}" for s in r.scores if s.passed is False
                ][:4]
        cases.append(cd)

    na = sum(len(v) for v in ra.values())
    nb = sum(len(v) for v in rb.values())
    pa = sum(r.passed for v in ra.values() for r in v)
    pb = sum(r.passed for v in rb.values() for r in v)
    p_value = fisher_exact(pa, na - pa, pb, nb - pb) if na and nb else 1.0
    sa, sb = a.summary, b.summary
    d = RunDiff(
        a=a,
        b=b,
        cases=cases,
        pass_rate_a=pa / na if na else 0.0,
        pass_rate_b=pb / nb if nb else 0.0,
        p_value=p_value,
        cost_a=sa.get("cost_per_trial_usd", 0.0),
        cost_b=sb.get("cost_per_trial_usd", 0.0),
        latency_p50_a=sa.get("latency_p50_ms", 0.0),
        latency_p50_b=sb.get("latency_p50_ms", 0.0),
        latency_p95_a=sa.get("latency_p95_ms", 0.0),
        latency_p95_b=sb.get("latency_p95_ms", 0.0),
    )
    d.notes = significance_notes(d, na, nb)
    return d


def significance_notes(d: RunDiff, na: int, nb: int) -> list[str]:
    notes = []
    if d.pass_rate_delta != 0:
        verdict = (
            "unlikely to be noise" if d.p_value < 0.05 else "could be noise at this sample size"
        )
        notes.append(
            f"Pass-rate change {d.pass_rate_delta * 100:+.1f} pts over {na} vs {nb} trials: "
            f"Fisher's exact p = {d.p_value:.3g}, {verdict}."
        )
    if min(na, nb) < 30:
        notes.append(
            f"Small sample ({min(na, nb)} trials): only large changes are detectable. "
            "Add cases or repeats for more power."
        )
    trials = max((c.a_trials for c in d.cases), default=0)
    if d.by_status("regressed") and trials and trials <= 5:
        floor = fisher_exact(trials, 0, 0, trials)
        notes.append(
            f"With {trials} trials per case, a single case can't reach p < {floor:.2g} on its own. "
            "Treat an all-pass → all-fail flip as a strong signal; a one-trial change as a hint."
        )
    if d.by_status("degraded"):
        notes.append(
            f"{len(d.by_status('degraded'))} case(s) still pass by majority but fail more trials: "
            "watch for flakiness."
        )
    return notes


@dataclass
class Thresholds:
    max_regressions: int | None = 0
    max_pass_rate_drop: float | None = None
    max_cost_increase: float | None = None
    min_pass_rate: float | None = None


def check_thresholds(d: RunDiff, t: Thresholds) -> list[str]:
    """Return the list of violated gates (empty means the candidate run passes)."""
    problems = []
    n_reg = len(d.by_status("regressed"))
    if t.max_regressions is not None and n_reg > t.max_regressions:
        problems.append(f"{n_reg} case(s) regressed (max {t.max_regressions})")
    if t.max_pass_rate_drop is not None and -d.pass_rate_delta > t.max_pass_rate_drop:
        problems.append(
            f"pass rate dropped {-d.pass_rate_delta * 100:.1f} pts "
            f"(max {t.max_pass_rate_drop * 100:.1f})"
        )
    if (
        t.max_cost_increase is not None
        and d.cost_change is not None
        and d.cost_change > t.max_cost_increase
    ):
        problems.append(
            f"cost per trial up {d.cost_change * 100:.0f}% (max {t.max_cost_increase * 100:.0f}%)"
        )
    if t.min_pass_rate is not None and d.pass_rate_b < t.min_pass_rate:
        problems.append(f"pass rate {d.pass_rate_b:.1%} below {t.min_pass_rate:.1%}")
    return problems

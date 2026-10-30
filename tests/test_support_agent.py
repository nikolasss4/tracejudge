"""The demo agent: v1 follows the refund policy, v2's prompt rewrite breaks it."""

from pathlib import Path

import pytest

from tracejudge.diff import diff_runs
from tracejudge.runner import RunOptions, run_suite
from tracejudge.store import Store
from tracejudge.suite import load_suite

SUITE = Path(__file__).parents[1] / "examples" / "support_agent" / "suite.yaml"


@pytest.fixture(autouse=True)
def no_sim_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_LATENCY", "0")
    monkeypatch.setenv("SUPPORT_AGENT_MODEL", "simulated")


def test_suite_shape() -> None:
    suite = load_suite(SUITE)
    assert len(suite.cases) == 41
    assert {c.name for c in suite.judge.criteria} == {
        "policy_compliance",
        "grounded",
        "helpful_tone",
    }


def test_v2_regression_is_caught(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    suite = load_suite(SUITE)
    v1 = run_suite(suite, store, RunOptions(agent="examples.support_agent.agent:run_v1", repeats=1))
    v2 = run_suite(suite, store, RunOptions(agent="examples.support_agent.agent:run_v2", repeats=1))
    assert v1.summary["pass_rate"] > 0.9
    d = diff_runs(store, v1, v2)
    regressed = {c.case_id for c in d.by_status("regressed")}
    assert "refund-late-boots" in regressed and "refund-high-value-bike" in regressed
    # Correct outcome, wrong process: the refund goes through but skipped the policy check.
    shoes = next(c for c in d.cases if c.case_id == "refund-eligible-shoes")
    assert shoes.status == "regressed"
    assert shoes.new_failures == [
        "precondition:issue_refund<-check_refund_policy",
        "trajectory:trajectory",
    ]
    refund_cases = {c.id for c in suite.cases if "refund" in c.tags}
    ownership = {c.id for c in suite.cases if "ownership" in c.tags}
    assert regressed >= refund_cases - ownership
    # Address and status flows are unchanged in v2; only the simulated model's rare seeded
    # slips can flip one of them in a single-trial run.
    assert len(regressed - refund_cases) <= 2

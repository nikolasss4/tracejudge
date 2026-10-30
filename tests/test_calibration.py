from pathlib import Path

import pytest

from tracejudge.calibration import calibrate, cohen_kappa, interpret_kappa, label_queue
from tracejudge.models import CaseResult, Label, Run, ScoreResult
from tracejudge.store import Store


def test_cohen_kappa_known_values() -> None:
    # Classic textbook example: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> kappa 0.4
    pairs = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 10 + [(False, False)] * 15
    assert cohen_kappa(pairs) == pytest.approx(0.4)
    assert cohen_kappa([(True, True), (False, False)]) == 1.0
    assert cohen_kappa([(True, False), (False, True)]) == -1.0
    assert cohen_kappa([(True, True)] * 5) is None
    assert cohen_kappa([]) is None


def test_high_agreement_can_still_mean_low_kappa() -> None:
    # The judge passes everything; humans fail 2 of 20. 90% agreement, kappa 0.
    pairs = [(True, True)] * 18 + [(True, False)] * 2
    assert sum(a == b for a, b in pairs) / len(pairs) == 0.9
    assert cohen_kappa(pairs) == pytest.approx(0.0)


def test_interpret() -> None:
    assert interpret_kappa(0.85) == "almost perfect"
    assert interpret_kappa(0.5) == "moderate"
    assert interpret_kappa(-0.1) == "poor"
    assert interpret_kappa(None) == "undefined"


def seed(store: Store) -> tuple[Run, list[CaseResult]]:
    run = Run(suite="s", agent="a")
    store.save_run(run)
    results = []
    for i in range(10):
        cr = CaseResult(
            run_id=run.run_id,
            case_id=f"c{i}",
            scores=[
                ScoreResult(scorer="judge", name="policy", passed=i < 6, reason=f"r{i}"),
                ScoreResult(scorer="judge", name="tone", passed=True, reason="ok"),
                ScoreResult(scorer="judge", name="skipped", passed=None, reason="no key"),
            ],
        )
        store.save_case_result(cr)
        results.append(cr)
    return run, results


def test_calibrate(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    run, results = seed(store)
    # Humans agree with the judge on policy except for c0 (judge pass, human fail).
    for i, cr in enumerate(results):
        human = i < 6 and i != 0
        store.set_label(
            Label(case_result_id=cr.id, criterion="policy", human_pass=human, note=f"n{i}")
        )
    store.set_label(Label(case_result_id=results[0].id, criterion="tone", human_pass=True))

    cals = {c.criterion: c for c in calibrate(store)}
    policy = cals["policy"]
    assert (policy.n, policy.agree) == (10, 9)
    assert policy.judge_pass_human_fail == 1 and policy.judge_fail_human_fail == 4
    assert policy.kappa == pytest.approx(
        cohen_kappa([(True, False)] + [(True, True)] * 5 + [(False, False)] * 4)
    )
    assert policy.disagreements[0].case_id == "c0" and policy.disagreements[0].human_note == "n0"
    assert cals["tone"].kappa is None
    assert "skipped" not in cals
    assert calibrate(store, [run.run_id])[0].criterion == "policy"


def test_label_queue_is_stratified(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    run, results = seed(store)
    queue = label_queue(store, run.run_id, criterion="policy", limit=4)
    verdicts = [next(s.passed for s in cr.scores if s.name == "policy") for cr, _ in queue]
    assert sorted(verdicts) == [False, False, True, True]
    store.set_label(Label(case_result_id=results[9].id, criterion="policy", human_pass=False))
    remaining = label_queue(store, run.run_id, criterion="policy", limit=100)
    assert len(remaining) == 9
    assert len(label_queue(store, run.run_id, limit=100)) == 19  # policy + tone

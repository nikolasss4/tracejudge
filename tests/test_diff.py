import json
from pathlib import Path

from typer.testing import CliRunner

from tracejudge.bundle import export_runs, import_bundle, read_bundle, write_bundle
from tracejudge.cli import app
from tracejudge.diff import Thresholds, check_thresholds, diff_runs
from tracejudge.models import CaseResult, Run, ScoreResult, Span, Trace
from tracejudge.report import MARKER, render_markdown
from tracejudge.store import Store


def add_trial(
    store: Store,
    run: Run,
    case_id: str,
    trial: int,
    passed: bool,
    tools: list[str],
    cost: float = 0.01,
) -> None:
    t = Trace(run_id=run.run_id, start_ns=0)
    t.spans = [
        Span(trace_id=t.trace_id, name=n, kind="tool", start_ns=i + 1, end_ns=i + 2)
        for i, n in enumerate(tools)
    ]
    store.save_trace(t)
    scores = [
        ScoreResult(
            scorer="precondition",
            name="refund<-policy",
            passed=passed,
            reason="ok" if passed else "issue_refund called before check_policy",
        )
    ]
    store.save_case_result(
        CaseResult(
            run_id=run.run_id,
            case_id=case_id,
            trial=trial,
            passed=passed,
            trace_id=t.trace_id,
            scores=scores,
            cost_usd=cost,
            latency_ms=100,
        )
    )


GOOD = ["lookup_order", "check_policy", "refund"]
BAD = ["lookup_order", "refund"]


def build(store: Store) -> tuple[Run, Run]:
    a = Run(suite="support", agent="v1", label="v1", git_sha="aaaaaaa1")
    b = Run(suite="support", agent="v2", label="v2", git_sha="bbbbbbb2")
    for i in range(3):
        add_trial(store, a, "refund-ineligible", i, True, GOOD)
        add_trial(store, b, "refund-ineligible", i, False, BAD, cost=0.012)
        add_trial(store, a, "address-change", i, True, ["lookup_order"])
        add_trial(store, b, "address-change", i, i != 0, ["lookup_order"], cost=0.012)
        add_trial(store, a, "escalate", i, i == 0, ["escalate"])
        add_trial(store, b, "escalate", i, True, ["escalate"], cost=0.012)
    a.summary = {"cost_per_trial_usd": 0.01, "latency_p50_ms": 100, "latency_p95_ms": 120}
    b.summary = {"cost_per_trial_usd": 0.012, "latency_p50_ms": 100, "latency_p95_ms": 130}
    store.save_run(a)
    store.save_run(b)
    return a, b


def test_diff_classifies_cases(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    a, b = build(store)
    d = diff_runs(store, a, b)
    status = {c.case_id: c.status for c in d.cases}
    assert status == {
        "refund-ineligible": "regressed",
        "address-change": "degraded",
        "escalate": "fixed",
    }
    reg = d.by_status("regressed")[0]
    assert reg.trajectory_a == GOOD and reg.trajectory_b == BAD
    assert reg.diverged_at == 1
    assert reg.new_failures == ["precondition:refund<-policy"]
    assert reg.p_value is not None and reg.p_value > 0.05  # 3 vs 3 trials can't be significant
    assert d.pass_rate_a == 7 / 9 and d.pass_rate_b == 5 / 9
    assert any("Small sample" in n for n in d.notes)
    assert d.cost_change is not None and abs(d.cost_change - 0.2) < 1e-9

    assert check_thresholds(d, Thresholds()) == ["1 case(s) regressed (max 0)"]
    assert check_thresholds(d, Thresholds(max_regressions=1)) == []
    gates = Thresholds(max_regressions=None, max_pass_rate_drop=0.1, max_cost_increase=0.1)
    assert len(check_thresholds(d, gates)) == 2

    md = render_markdown(d, ["1 case(s) regressed (max 0)"])
    assert md.startswith(MARKER)
    assert "Regression gate failed" in md
    assert (
        "| `refund-ineligible` | 3/3 | 0/3 | step 2: `check_policy` → `refund` | "
        "`precondition:refund<-policy` |" in md
    )
    assert "**Fixed (1):** `escalate` (1/3→3/3)" in md


def test_bundle_roundtrip_and_cli_diff(tmp_path: Path) -> None:
    src = Store(tmp_path / "src.db")
    a, b = build(src)
    for run in (a, b):
        write_bundle(export_runs(src, [run.run_id]), tmp_path / f"{run.label}.json.gz")
    assert read_bundle(tmp_path / "v1.json.gz")["runs"][0]["label"] == "v1"

    db = tmp_path / "dst.db"
    md = tmp_path / "report.md"
    out = tmp_path / "diff.json"
    result = CliRunner().invoke(
        app,
        [
            "diff",
            str(tmp_path / "v1.json.gz"),
            str(tmp_path / "v2.json.gz"),
            "--db",
            str(db),
            "--markdown",
            str(md),
            "--json",
            str(out),
            "--max-regressions",
            "0",
        ],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 1, result.output
    assert "regressed" in result.output and "refund-ineligible" in result.output
    assert "Newly failing (1)" in md.read_text()
    assert json.loads(out.read_text())["gate_failures"] == ["1 case(s) regressed (max 0)"]
    ok = CliRunner().invoke(app, ["diff", "v1", "v2", "--db", str(db)])
    assert ok.exit_code == 0, ok.output

    again = Store(tmp_path / "again.db")
    assert import_bundle(again, read_bundle(tmp_path / "v2.json.gz")) == [b.run_id]
    assert len(again.case_results(b.run_id)) == 9

import json
from pathlib import Path

from typer.testing import CliRunner

from tracejudge.cli import app
from tracejudge.runner import RunOptions, load_agent, run_suite
from tracejudge.store import Store
from tracejudge.suite import load_suite

SUITE = Path(__file__).parent / "data" / "toy_suite.yaml"


def test_run_suite_scores_and_summarizes(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    suite = load_suite(SUITE)
    run = run_suite(
        suite, store, RunOptions(agent="tests.agents.toy:agent", repeats=2, concurrency=1)
    )
    s = run.summary
    assert (s["cases"], s["trials"]) == (4, 8)
    assert s["per_case"]["add-small"] == {"passed": 2, "trials": 2}
    assert s["per_case"]["add-wrong-expectation"]["passed"] == 0
    assert s["per_case"]["crash"]["passed"] == 0
    # The flaky case shares its input dict across trials, so it alternates fail/pass.
    assert s["per_case"]["flaky"] == {"passed": 1, "trials": 2}
    assert s["flaky_cases"] == ["flaky"]
    assert s["pass_rate"] == 3 / 8
    assert s["pass_at_k"] == (1 + 0 + 0 + 1) / 4
    assert s["pass_hat_k"] == 1 / 4
    assert run.model == "claude-haiku-5-5"
    assert run.status == "finished"

    results = store.case_results(run.run_id)
    crash = next(r for r in results if r.case_id == "crash")
    assert crash.error == "RuntimeError: crashed"
    trace = store.get_trace(results[0].trace_id or "")
    assert trace is not None and trace.run_id == run.run_id
    root = [sp for sp in trace.spans if sp.parent_id is None]
    assert len(root) == 1 and root[0].kind == "agent"


def test_case_filter_and_async_agent(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    suite = load_suite(SUITE)
    opts = RunOptions(agent="tests.agents.toy:async_agent", repeats=1, patterns=["math"])
    run = run_suite(suite, store, opts)
    assert run.summary["cases"] == 1 and run.summary["pass_rate"] == 1


def test_load_agent_from_file() -> None:
    fn = load_agent(str(Path(__file__).parent / "agents" / "toy.py") + ":agent")
    assert callable(fn)


def test_cli_eval(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    out = tmp_path / "out.json"
    args = ["eval", str(SUITE), "--db", str(db), "-n", "1", "--json", str(out), "--label", "base"]
    result = CliRunner().invoke(app, [*args, "--fail-under", "0.9"])
    assert result.exit_code == 1, result.output
    assert "pass rate" in result.output
    data = json.loads(out.read_text())
    assert data["run"]["label"] == "base" and len(data["results"]) == 4
    listing = CliRunner().invoke(app, ["runs", "--db", str(db)])
    assert "base" in listing.output
    shown = CliRunner().invoke(app, ["show", "base", "--db", str(db)])
    assert "add-wrong-expectation" in shown.output

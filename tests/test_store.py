from pathlib import Path

from tracejudge.models import CaseResult, Label, Run, ScoreResult, Span, Trace
from tracejudge.store import Store


def make_trace(run_id: str | None = None) -> Trace:
    t = Trace(name="case", start_ns=1_000, end_ns=9_000, run_id=run_id)
    root = Span(trace_id=t.trace_id, name="agent", kind="agent", start_ns=1_000, end_ns=9_000)
    llm = Span(
        trace_id=t.trace_id,
        parent_id=root.span_id,
        name="claude",
        kind="llm",
        start_ns=2_000,
        end_ns=4_000,
        model="claude-sonnet-5-5",
        input_tokens=100,
        output_tokens=20,
        cost_usd=0.0004,
        input={"messages": [{"role": "user", "content": "hi"}]},
    )
    tool = Span(
        trace_id=t.trace_id,
        parent_id=root.span_id,
        name="lookup_order",
        kind="tool",
        start_ns=5_000,
        end_ns=6_000,
        input={"order_id": "A1"},
        output={"status": "shipped"},
    )
    t.spans = [tool, root, llm]
    return t


def test_trace_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    t = make_trace()
    store.save_trace(t)
    got = store.get_trace(t.trace_id)
    assert got is not None
    assert [s.name for s in got.ordered_spans()] == ["agent", "claude", "lookup_order"]
    assert got.total_tokens == 120
    assert got.cost_usd == 0.0004
    assert got.tool_calls()[0].args == {"order_id": "A1"}
    assert got.spans_of("llm")[0].input == {"messages": [{"role": "user", "content": "hi"}]}
    summary = store.list_traces()[0]
    assert summary["spans"] == 3 and summary["tokens"] == 120


def test_add_spans_creates_trace(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    spans = [
        Span(trace_id="abc", span_id="1", name="root", start_ns=10, end_ns=50),
        Span(trace_id="abc", span_id="2", parent_id="1", name="child", start_ns=5, end_ns=80),
    ]
    store.add_spans(spans[1:])
    store.add_spans(spans[:1])
    t = store.get_trace("abc")
    assert t is not None
    assert t.name == "root"
    assert (t.start_ns, t.end_ns) == (5, 80)
    assert len(t.spans) == 2


def test_runs_cases_and_labels(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    run = Run(suite="support", agent="agent:v1", model="sim", git_sha="abc1234", label="base")
    store.save_run(run)
    cr = CaseResult(
        run_id=run.run_id,
        case_id="refund-1",
        trial=1,
        passed=True,
        scores=[ScoreResult(scorer="judge", name="polite", passed=True, reason="ok")],
    )
    store.save_case_result(cr)
    store.set_label(Label(case_result_id=cr.id, criterion="polite", human_pass=False))
    store.set_label(Label(case_result_id=cr.id, criterion="polite", human_pass=True))

    assert store.get_run(run.run_id[:12]) is not None
    assert store.get_run("base") is not None
    assert [r.run_id for r in store.list_runs(git_sha="abc")] == [run.run_id]
    assert store.list_runs(suite="other") == []
    results = store.case_results(run.run_id)
    assert results[0].scores[0].name == "polite"
    labels = store.labels(run.run_id)
    assert len(labels) == 1 and labels[0].human_pass is True

    store.delete_run(run.run_id)
    assert store.get_run(run.run_id) is None
    assert store.labels() == []

import asyncio
from pathlib import Path

import pytest

from tracejudge import capture, configure, span, trace
from tracejudge.models import Trace
from tracejudge.store import Store


@trace(kind="tool")
def lookup_order(order_id: str, verbose: bool = False) -> dict:
    return {"order_id": order_id, "status": "shipped"}


@trace(name="fail", kind="tool")
def broken() -> None:
    raise ValueError("boom")


@trace(kind="retrieval")
async def search(query: str) -> list[str]:
    await asyncio.sleep(0)
    return [query.upper()]


def test_capture_nests_spans() -> None:
    with capture("case-1") as t, span("agent", kind="agent", input={"q": "x"}) as root:
        lookup_order("A1")
        with span("claude", kind="llm") as llm:
            llm.set_usage(model="claude-sonnet-5-5", input_tokens=1000, output_tokens=100)
        root.set_output("done")
    names = [s.name for s in t.ordered_spans()]
    assert names == ["agent", "lookup_order", "claude"]
    root_span = t.ordered_spans()[0]
    assert all(s.parent_id == root_span.span_id for s in t.spans if s is not root_span)
    assert t.tool_calls()[0].args == {"order_id": "A1", "verbose": False}
    assert t.tool_calls()[0].result == {"order_id": "A1", "status": "shipped"}
    assert t.spans_of("llm")[0].cost_usd == pytest.approx((1000 * 2 + 100 * 10) / 1e6)
    assert root_span.output == "done"


def test_errors_are_recorded_and_reraised() -> None:
    with capture() as t, pytest.raises(ValueError):
        broken()
    assert t.spans[0].status == "error"
    assert "boom" in (t.spans[0].error or "")


def test_async_spans() -> None:
    async def main() -> Trace:
        with capture() as t:
            await asyncio.gather(search("a"), search("b"))
        return t

    t = asyncio.run(main())
    assert sorted(s.output[0] for s in t.spans) == ["A", "B"]
    assert all(s.kind == "retrieval" and s.parent_id is None for s in t.spans)


def test_root_span_flushes_to_store(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    configure(db=db)
    try:
        with span("standalone", kind="agent"):
            lookup_order("B2")
    finally:
        configure()
    traces = Store(db).list_traces()
    assert len(traces) == 1 and traces[0]["spans"] == 2 and traces[0]["name"] == "standalone"

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tracejudge.judge import Judge, build_prompt, make_judge, render_transcript
from tracejudge.models import Span, Trace
from tracejudge.scorers.base import ScoreContext
from tracejudge.suite import Case, Criterion, JudgeConfig, Suite

CRITERIA = [
    Criterion(name="policy", description="Refunds only after checking policy."),
    Criterion(name="tone", description="Polite and concise."),
]


class FakeMessages:
    def __init__(self, verdicts: list[dict[str, Any]], stop_reason: str = "end_turn") -> None:
        self.verdicts = verdicts
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            model="claude-sonnet-5-5",
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps({"verdicts": self.verdicts}))],
            usage=SimpleNamespace(input_tokens=2000, output_tokens=200),
        )


def fake_client(verdicts: list[dict[str, Any]], **kw: Any) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(verdicts, **kw)))


def ctx() -> ScoreContext:
    t = Trace()
    t.spans = [
        Span(
            trace_id=t.trace_id,
            name="llm",
            kind="llm",
            start_ns=1,
            output={"content": [{"type": "text", "text": "Let me check."}]},
        ),
        Span(
            trace_id=t.trace_id,
            name="issue_refund",
            kind="tool",
            start_ns=2,
            input={"order_id": "A1"},
            output={"ok": True},
        ),
    ]
    return ScoreContext(output="Done, refunded.", trace=t)


CASE = Case(id="c1", input={"message": "refund A1"}, reference="Deny: outside window")


def test_transcript_and_prompt() -> None:
    text = render_transcript(ctx().trace)
    assert text.splitlines() == [
        "[assistant] Let me check.",
        '[tool call] issue_refund({"order_id": "A1"}) -> {"ok": true}',
    ]
    prompt = build_prompt(JudgeConfig(), CASE, ctx(), CRITERIA)
    assert "<reference_answer>" in prompt and 'name="tone"' in prompt


def test_judge_records_then_replays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    verdicts = [
        {"criterion": "policy", "reasoning": "Refunded without check.", "passed": False},
        {"criterion": "tone", "reasoning": "Polite.", "passed": True},
    ]
    client = fake_client(verdicts)
    rec = Judge(JudgeConfig(), fixtures_dir=tmp_path, record=True, client=client)
    results = rec.evaluate(CASE, ctx(), CRITERIA)
    assert [(r.name, r.passed) for r in results] == [("policy", False), ("tone", True)]
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert len(list(tmp_path.glob("*.json"))) == 1

    replay = Judge(JudgeConfig(), fixtures_dir=tmp_path, client=fake_client([]))
    again = replay.evaluate(CASE, ctx(), CRITERIA)
    assert [(r.name, r.passed) for r in again] == [("policy", False), ("tone", True)]
    assert again[0].details["source"] == "fixture"
    assert replay.stats == {"replayed": 1, "called": 0, "skipped": 0}

    # A different transcript is a different request, so it is not replayed: skipped, not passed.
    changed = ctx()
    changed.output = "something else"
    skipped = replay.evaluate(CASE, changed, CRITERIA)
    assert all(r.passed is None for r in skipped)


def test_refusal_and_missing_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    refused = Judge(JudgeConfig(), client=fake_client([], stop_reason="refusal"))
    assert all(r.passed is None for r in refused.evaluate(CASE, ctx(), CRITERIA))
    partial = Judge(
        JudgeConfig(),
        client=fake_client([{"criterion": "tone", "reasoning": "ok", "passed": True}]),
    )
    results = {r.name: r.passed for r in partial.evaluate(CASE, ctx(), CRITERIA)}
    assert results == {"policy": None, "tone": True}


def test_make_judge_respects_case_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    suite = Suite(
        name="s",
        judge=JudgeConfig(criteria=CRITERIA),
        cases=[Case(id="a", input=1, judge=["tone"]), Case(id="b", input=2, judge=False)],
    )
    client = fake_client([{"criterion": "tone", "reasoning": "ok", "passed": True}])
    fn, info = make_judge(suite, model="claude-opus-5-5", client=client)
    assert fn is not None and info["model"] == "claude-opus-5-5"
    assert [r.name for r in fn(suite.cases[0], ctx())] == ["tone"]
    assert fn(suite.cases[1], ctx()) == []

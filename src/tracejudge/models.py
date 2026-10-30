"""Core data model: traces made of spans, eval runs made of case results."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SpanKind = Literal["agent", "llm", "tool", "retrieval", "custom"]
SpanStatus = Literal["ok", "error"]
TraceSource = Literal["sdk", "otlp", "import"]


def new_id(nbytes: int = 8) -> str:
    return secrets.token_hex(nbytes)


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class Span(BaseModel):
    """One unit of work inside a trace: an LLM call, a tool call, a retrieval, or anything else."""

    span_id: str = Field(default_factory=new_id)
    trace_id: str
    parent_id: str | None = None
    name: str
    kind: SpanKind = "custom"
    start_ns: int
    end_ns: int | None = None
    status: SpanStatus = "ok"
    error: str | None = None
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    # LLM-specific; None for other kinds.
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    @property
    def duration_ms(self) -> float:
        if self.end_ns is None:
            return 0.0
        return (self.end_ns - self.start_ns) / 1e6


class ToolCall(BaseModel):
    """A tool invocation pulled out of a trace, in the order it started."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    error: str | None = None
    span_id: str | None = None


class Trace(BaseModel):
    trace_id: str = Field(default_factory=lambda: new_id(16))
    name: str = "trace"
    source: TraceSource = "sdk"
    start_ns: int = 0
    end_ns: int | None = None
    run_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    spans: list[Span] = Field(default_factory=list)

    def ordered_spans(self) -> list[Span]:
        return sorted(self.spans, key=lambda s: (s.start_ns, s.end_ns or 0))

    def spans_of(self, kind: SpanKind) -> list[Span]:
        return [s for s in self.ordered_spans() if s.kind == kind]

    def tool_calls(self) -> list[ToolCall]:
        calls = []
        for s in self.spans_of("tool"):
            args = s.input if isinstance(s.input, dict) else {"input": s.input}
            calls.append(
                ToolCall(name=s.name, args=args, result=s.output, error=s.error, span_id=s.span_id)
            )
        return calls

    @property
    def input_tokens(self) -> int:
        return sum(s.input_tokens or 0 for s in self.spans)

    @property
    def output_tokens(self) -> int:
        return sum(s.output_tokens or 0 for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        return sum(s.cost_usd or 0.0 for s in self.spans)

    @property
    def duration_ms(self) -> float:
        starts = [s.start_ns for s in self.spans] + ([self.start_ns] if self.start_ns else [])
        ends = [s.end_ns for s in self.spans if s.end_ns] + ([self.end_ns] if self.end_ns else [])
        if not starts or not ends:
            return 0.0
        return (max(ends) - min(starts)) / 1e6

    @property
    def llm_calls(self) -> int:
        return len(self.spans_of("llm"))


class ScoreResult(BaseModel):
    """The verdict of one scorer (or one judge criterion) on one case trial.

    ``passed`` is None when the scorer was skipped, e.g. an LLM judge with no API key and no
    recorded fixture. Skipped scores never count towards pass or fail.
    """

    scorer: str
    name: str
    passed: bool | None
    score: float | None = None
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class CaseResult(BaseModel):
    id: str = Field(default_factory=new_id)
    run_id: str
    case_id: str
    trial: int = 0
    trace_id: str | None = None
    input: Any = None
    output: Any = None
    error: str | None = None
    passed: bool = False
    scores: list[ScoreResult] = Field(default_factory=list)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    steps: int = 0
    tags: list[str] = Field(default_factory=list)


class Run(BaseModel):
    run_id: str = Field(default_factory=new_run_id)
    suite: str
    agent: str
    model: str | None = None
    label: str | None = None
    git_sha: str | None = None
    git_branch: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    status: Literal["running", "finished", "failed"] = "running"
    config: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class Label(BaseModel):
    """A human pass/fail judgement on one criterion of one case result."""

    case_result_id: str
    criterion: str
    human_pass: bool
    note: str = ""
    labeler: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

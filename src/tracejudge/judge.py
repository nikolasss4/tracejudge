"""LLM-as-judge: rubric-based, per-criterion verdicts with structured output.

The judge sees the task input, a compact transcript of the agent's trajectory (assistant text,
tool calls with arguments and results) and the final answer, then returns one
``{criterion, reasoning, passed}`` verdict per criterion via JSON-schema structured output.

Every judge call is keyed by a hash of its full request. With ``record=True`` the responses are
written to a fixtures directory; later runs replay them, so CI can run LLM-judged suites with no
API key. A call with neither a fixture nor credentials is reported as *skipped*, never as a pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from tracejudge.models import ScoreResult, Trace
from tracejudge.pricing import cost_usd
from tracejudge.runner import JudgeFn
from tracejudge.scorers.base import ScoreContext
from tracejudge.scorers.deterministic import output_text
from tracejudge.suite import Case, Criterion, JudgeConfig, Suite

JUDGE_SYSTEM = """You are an evaluator for an AI agent. You grade one agent run against a \
rubric of independent criteria.

For each criterion, decide pass or fail using only the evidence in the transcript: what the \
agent said, which tools it called with which arguments, and what the tools returned. Judge each \
criterion on its own; a failure on one criterion does not affect the others. If a criterion \
does not apply to this run, mark it passed and say why it does not apply.

Write one or two sentences of reasoning per criterion that cite the specific evidence, then the \
verdict."""

MAX_FIELD_CHARS = 4000


def _clip(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= MAX_FIELD_CHARS else text[:MAX_FIELD_CHARS] + " …[truncated]"


def render_transcript(trace: Trace) -> str:
    """Render the agent's trajectory as plain text for the judge."""
    lines: list[str] = []
    for s in trace.ordered_spans():
        if s.kind == "llm":
            out = s.output if isinstance(s.output, dict) else {}
            for block in out.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    lines.append(f"[assistant] {_clip(block['text'])}")
            if isinstance(out.get("message"), dict) and out["message"].get("content"):
                lines.append(f"[assistant] {_clip(out['message']['content'])}")
        elif s.kind == "tool":
            result = f"ERROR {s.error}" if s.status == "error" else _clip(s.output)
            lines.append(f"[tool call] {s.name}({_clip(s.input)}) -> {result}")
        elif s.kind == "retrieval":
            lines.append(f"[retrieval] {s.name}({_clip(s.input)}) -> {_clip(s.output)}")
    return "\n".join(lines) or "(no LLM or tool activity recorded)"


def verdict_schema(criteria: list[Criterion]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion": {"type": "string", "enum": [c.name for c in criteria]},
                        "reasoning": {"type": "string"},
                        "passed": {"type": "boolean"},
                    },
                    "required": ["criterion", "reasoning", "passed"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["verdicts"],
        "additionalProperties": False,
    }


def build_prompt(
    config: JudgeConfig, case: Case, ctx: ScoreContext, criteria: list[Criterion]
) -> str:
    parts = [
        "<task_input>",
        _clip(case.input),
        "</task_input>",
        "<agent_transcript>",
        render_transcript(ctx.trace),
        "</agent_transcript>",
        "<final_answer>",
        _clip(output_text(ctx.output)),
        "</final_answer>",
    ]
    if case.reference:
        parts += ["<reference_answer>", case.reference, "</reference_answer>"]
    if config.instructions:
        parts += ["<grading_notes>", config.instructions.strip(), "</grading_notes>"]
    parts.append("<criteria>")
    for c in criteria:
        parts.append(f'<criterion name="{c.name}">\n{c.description.strip()}')
        for ex in c.examples:
            verdict = "PASS" if ex.get("passed") else "FAIL"
            parts.append(f"  example ({verdict}): {ex.get('text', '')}")
        parts.append("</criterion>")
    parts.append("</criteria>")
    parts.append("Return one verdict for every criterion listed above.")
    return "\n".join(parts)


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


class Judge:
    def __init__(
        self,
        config: JudgeConfig,
        fixtures_dir: Path | None = None,
        record: bool = False,
        client: Any = None,
        effort: str = "medium",
    ) -> None:
        self.config = config
        self.fixtures_dir = fixtures_dir
        self.record = record
        self.effort = effort
        self._client = client
        self._lock = threading.Lock()
        self.stats = {"replayed": 0, "called": 0, "skipped": 0}

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                import anthropic

                self._client = anthropic.Anthropic()
            return self._client

    def request(self, prompt: str, criteria: list[Criterion]) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "max_tokens": 16000,
            "system": JUDGE_SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": verdict_schema(criteria)},
            },
        }

    @staticmethod
    def digest(request: dict[str, Any]) -> str:
        canonical = json.dumps(request, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    def _fixture(self, key: str) -> Path | None:
        return self.fixtures_dir / f"{key}.json" if self.fixtures_dir else None

    def _call_api(self, request: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        # Server-side fallback reroutes a safety decline to another model inside the same call.
        response = client.beta.messages.create(
            **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
        )
        if response.stop_reason == "refusal":
            return {"refused": True, "model": response.model}
        text = next(b.text for b in response.content if b.type == "text")
        usage = response.usage
        return {
            "model": response.model,
            "verdicts": json.loads(text)["verdicts"],
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }

    def evaluate(
        self, case: Case, ctx: ScoreContext, criteria: list[Criterion]
    ) -> list[ScoreResult]:
        if not criteria:
            return []
        request = self.request(build_prompt(self.config, case, ctx, criteria), criteria)
        key = self.digest(request)
        fixture = self._fixture(key)
        source = "api"
        if fixture and fixture.exists() and not self.record:
            data = json.loads(fixture.read_text())
            source = "fixture"
            self.stats["replayed"] += 1
        elif self.record or has_credentials():
            data = self._call_api(request)
            self.stats["called"] += 1
            if fixture and self.record:
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.write_text(json.dumps({"key": key, "case": case.id, **data}, indent=2))
        else:
            self.stats["skipped"] += 1
            return [
                ScoreResult(
                    scorer="judge",
                    name=c.name,
                    passed=None,
                    reason="skipped: no recorded fixture and no Anthropic credentials",
                    details={"key": key},
                )
                for c in criteria
            ]
        if data.get("refused"):
            return [
                ScoreResult(
                    scorer="judge", name=c.name, passed=None, reason="skipped: judge refused"
                )
                for c in criteria
            ]
        cost = cost_usd(
            data.get("model"), data.get("input_tokens", 0), data.get("output_tokens", 0)
        )
        by_name = {v["criterion"]: v for v in data["verdicts"]}
        results = []
        for c in criteria:
            v = by_name.get(c.name)
            details = {"model": data.get("model"), "source": source, "key": key}
            if v is None:
                results.append(
                    ScoreResult(
                        scorer="judge",
                        name=c.name,
                        passed=None,
                        reason="judge returned no verdict",
                        details=details,
                    )
                )
                continue
            results.append(
                ScoreResult(
                    scorer="judge",
                    name=c.name,
                    passed=bool(v["passed"]),
                    score=1.0 if v["passed"] else 0.0,
                    reason=v["reasoning"],
                    details={**details, "cost_usd": cost / len(criteria) if cost else None},
                )
            )
        return results


def make_judge(
    suite: Suite,
    model: str | None = None,
    record: bool = False,
    base_dir: Path | None = None,
    client: Any = None,
) -> tuple[JudgeFn | None, dict[str, Any]]:
    """Build the runner's judge callback for a suite."""
    if suite.judge is None or not suite.judge.criteria:
        return None, {}
    config = suite.judge.model_copy(update={"model": model} if model else {})
    fixtures = None
    if config.fixtures:
        fixtures = Path(config.fixtures)
        if not fixtures.is_absolute() and base_dir is not None:
            fixtures = base_dir / fixtures
    judge = Judge(config, fixtures_dir=fixtures, record=record, client=client)

    def judge_fn(case: Case, ctx: ScoreContext) -> list[ScoreResult]:
        return judge.evaluate(case, ctx, suite.judge_criteria(case))

    info = {
        "model": config.model,
        "criteria": [c.name for c in config.criteria],
        "fixtures": str(fixtures) if fixtures else None,
    }
    return judge_fn, info

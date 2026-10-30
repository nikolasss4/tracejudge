"""Deterministic scorers, built from a test case's ``expect`` block.

    expect:
      final_answer: {contains: ["refund"], regex: "\\$\\d+"}
      tool_calls:
        - {name: issue_refund, args: {order_id: A100, amount: {$lte: 50}}}
      trajectory: {mode: ordered, steps: [lookup_order, check_refund_policy, issue_refund]}
      forbidden: [escalate_to_human]
      preconditions: {issue_refund: check_refund_policy}
      budget: {max_steps: 8, max_tokens: 20000, max_cost_usd: 0.05}

Every scorer is a pure function of the output and the trace, so all of this is unit-tested
and needs no API key.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tracejudge.models import ScoreResult, ToolCall
from tracejudge.scorers.base import ScoreContext, Scorer

# ---- value matching ---------------------------------------------------------------------

_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


def _num(v: Any) -> bool:
    return _TYPES["number"](v)


def match_value(expected: Any, actual: Any) -> bool:
    """Match an actual value against an expected value or operator dict.

    Plain values must be equal (floats within 1e-6). Dicts match as subsets (extra keys in the
    actual value are allowed) unless they are operator dicts such as ``{"$regex": "..."}``.
    """
    if isinstance(expected, dict) and expected and all(k.startswith("$") for k in expected):
        return all(_match_op(op, arg, actual) for op, arg in expected.items())
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and match_value(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(match_value(e, a) for e, a in zip(expected, actual, strict=True))
    if _num(expected) and _num(actual):
        return math.isclose(expected, actual, rel_tol=1e-6, abs_tol=1e-6)
    return bool(expected == actual)


def _match_op(op: str, arg: Any, actual: Any) -> bool:
    match op:
        case "$any":
            return True
        case "$eq":
            return match_value(arg, actual)
        case "$ne":
            return not match_value(arg, actual)
        case "$regex":
            return isinstance(actual, str) and re.search(arg, actual) is not None
        case "$in":
            return any(match_value(a, actual) for a in arg)
        case "$contains":
            return isinstance(actual, str | list) and arg in actual
        case "$icontains":
            return isinstance(actual, str) and str(arg).lower() in actual.lower()
        case "$gt":
            return _num(actual) and actual > arg
        case "$gte":
            return _num(actual) and actual >= arg
        case "$lt":
            return _num(actual) and actual < arg
        case "$lte":
            return _num(actual) and actual <= arg
        case "$type":
            return _TYPES[arg](actual)
        case "$exists":
            return (actual is not None) is bool(arg)
    raise ValueError(f"unknown match operator {op!r}")


def validate_schema(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    """Validate against a practical JSON Schema subset: type, enum, const, required,
    properties, additionalProperties, items, pattern, minimum/maximum, min/maxLength."""
    errors: list[str] = []
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](value) for x in types):
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']!r}")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if _num(value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required {key!r}")
        for key, sub in value.items():
            if key in props:
                errors.extend(validate_schema(props[key], sub, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate_schema(schema["items"], item, f"{path}[{i}]"))
    return errors


# ---- helpers ----------------------------------------------------------------------------


def output_text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("answer", "final_answer", "text", "output", "response"):
            if isinstance(output.get(key), str):
                return str(output[key])
    return json.dumps(output, default=str)


@dataclass
class CallSpec:
    name: str
    args: dict[str, Any] | None = None

    @classmethod
    def parse(cls, raw: str | dict[str, Any]) -> CallSpec:
        if isinstance(raw, str):
            return cls(name=raw)
        return cls(name=raw["name"], args=raw.get("args"))

    def matches(self, call: ToolCall) -> bool:
        return call.name == self.name and (self.args is None or match_value(self.args, call.args))

    def label(self) -> str:
        return self.name if self.args is None else f"{self.name}({json.dumps(self.args)})"


def _result(scorer: str, name: str, passed: bool, reason: str, **details: Any) -> ScoreResult:
    return ScoreResult(scorer=scorer, name=name, passed=passed, reason=reason, details=details)


# ---- scorers ----------------------------------------------------------------------------


@dataclass
class NoError:
    name: str = "no_error"

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        if ctx.error:
            return [_result("no_error", "no_error", False, ctx.error)]
        return []


@dataclass
class FinalAnswer:
    spec: dict[str, Any]
    name: str = "final_answer"

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        text = output_text(ctx.output)
        ignore_case = self.spec.get("ignore_case", True)
        norm = text.lower() if ignore_case else text
        flags = re.IGNORECASE if ignore_case else 0
        problems = []

        def n(s: str) -> str:
            return s.lower() if ignore_case else s

        if "equals" in self.spec and norm.strip() != n(str(self.spec["equals"])).strip():
            problems.append(f"expected exactly {self.spec['equals']!r}")
        missing = [s for s in self.spec.get("contains", []) if n(s) not in norm]
        if missing:
            problems.append(f"missing {missing}")
        any_of = self.spec.get("contains_any", [])
        if any_of and not any(n(s) in norm for s in any_of):
            problems.append(f"contains none of {any_of}")
        present = [s for s in self.spec.get("not_contains", []) if n(s) in norm]
        if present:
            problems.append(f"must not contain {present}")
        for pattern in _as_list(self.spec.get("regex")):
            if not re.search(pattern, text, flags):
                problems.append(f"does not match /{pattern}/")
        reason = "; ".join(problems) or "answer matches"
        return [_result("final_answer", "final_answer", not problems, reason, answer=text[:2000])]


@dataclass
class ToolCalled:
    spec: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.spec["name"])

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        calls = [c for c in ctx.trace.tool_calls() if c.name == self.name]
        min_times = self.spec.get("min_times", 1 if self.spec.get("max_times") != 0 else 0)
        max_times = self.spec.get("max_times")
        args = self.spec.get("args")
        schema = self.spec.get("args_schema")
        exact = self.spec.get("exact_args", False)

        def problems_for(c: ToolCall) -> list[str]:
            out = []
            if args is not None:
                for key, want in args.items():
                    if key not in c.args:
                        out.append(f"missing arg {key!r}")
                    elif not match_value(want, c.args[key]):
                        out.append(f"{key}={c.args[key]!r}, expected {want!r}")
                if exact and set(c.args) - set(args):
                    out.append(f"unexpected args {sorted(set(c.args) - set(args))}")
            if schema is not None:
                out.extend(validate_schema(schema, c.args))
            return out

        matching = [c for c in calls if not problems_for(c)]
        n = len(matching)
        if n < min_times:
            if calls:
                reason = f"{self.name} called {len(calls)}x but args did not match: " + "; ".join(
                    problems_for(calls[0])
                )
            else:
                reason = f"{self.name} was never called"
            passed = False
        elif max_times is not None and len(calls) > max_times:
            reason = f"{self.name} called {len(calls)}x, at most {max_times} allowed"
            passed = False
        else:
            reason = f"{self.name} called {len(calls)}x as expected"
            passed = True
        return [
            _result(
                "tool_call",
                self.name,
                passed,
                reason,
                calls=[c.args for c in calls],
            )
        ]


@dataclass
class Trajectory:
    spec: dict[str, Any]
    name: str = "trajectory"

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        mode = self.spec.get("mode", "ordered")
        steps = [CallSpec.parse(s) for s in self.spec["steps"]]
        calls = ctx.trace.tool_calls()
        actual = [c.name for c in calls]
        expected = [s.label() for s in steps]
        diverged: int | None = None

        if mode == "exact":
            passed = len(calls) == len(steps) and all(
                s.matches(c) for s, c in zip(steps, calls, strict=False)
            )
            if not passed:
                diverged = next(
                    (
                        i
                        for i, (s, c) in enumerate(zip(steps, calls, strict=False))
                        if not s.matches(c)
                    ),
                    min(len(steps), len(calls)),
                )
        elif mode == "ordered":
            i = 0
            for j, c in enumerate(calls):
                if i < len(steps) and steps[i].matches(c):
                    i += 1
                elif diverged is None and i < len(steps):
                    diverged = j
            passed = i == len(steps)
            if passed:
                diverged = None
            elif diverged is None:
                diverged = len(calls)
            missing = [s.label() for s in steps[i:]]
        elif mode == "unordered":
            remaining = list(calls)
            missing = []
            for s in steps:
                hit = next((c for c in remaining if s.matches(c)), None)
                if hit is None:
                    missing.append(s.label())
                else:
                    remaining.remove(hit)
            passed = not missing
        else:
            raise ValueError(f"unknown trajectory mode {mode!r}")

        if passed:
            reason = f"{mode} trajectory matches"
        elif mode == "exact":
            reason = f"diverged at step {diverged}: expected {expected}, got {actual}"
        else:
            reason = f"missing {missing} ({mode}); got {actual}"
        return [
            _result(
                "trajectory",
                "trajectory",
                passed,
                reason,
                mode=mode,
                expected=expected,
                actual=actual,
                diverged_at=diverged,
            )
        ]


@dataclass
class Forbidden:
    spec: CallSpec

    @property
    def name(self) -> str:
        return self.spec.name

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        hits = [c for c in ctx.trace.tool_calls() if self.spec.matches(c)]
        reason = (
            f"forbidden call {self.spec.label()} made {len(hits)}x: {hits[0].args}"
            if hits
            else f"{self.spec.label()} not called"
        )
        return [
            _result("forbidden", self.spec.name, not hits, reason, calls=[c.args for c in hits])
        ]


@dataclass
class Precondition:
    action: str
    required: str

    @property
    def name(self) -> str:
        return f"{self.action}<-{self.required}"

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        seen_required = False
        for c in ctx.trace.tool_calls():
            if c.name == self.required:
                seen_required = True
            elif c.name == self.action and not seen_required:
                return [
                    _result(
                        "precondition",
                        self.name,
                        False,
                        f"{self.action} called before {self.required}",
                    )
                ]
        return [_result("precondition", self.name, True, f"{self.required} precedes {self.action}")]


BUDGETS: dict[str, Callable[[ScoreContext], float]] = {
    "max_steps": lambda ctx: ctx.trace.llm_calls,
    "max_llm_calls": lambda ctx: ctx.trace.llm_calls,
    "max_tool_calls": lambda ctx: len(ctx.trace.tool_calls()),
    "max_tokens": lambda ctx: ctx.trace.total_tokens,
    "max_cost_usd": lambda ctx: ctx.trace.cost_usd,
    "max_latency_ms": lambda ctx: ctx.trace.duration_ms,
}


@dataclass
class Budget:
    spec: dict[str, float]
    name: str = "budget"

    def __call__(self, ctx: ScoreContext) -> list[ScoreResult]:
        out = []
        for key, limit in self.spec.items():
            if key not in BUDGETS:
                raise ValueError(f"unknown budget {key!r}; use one of {sorted(BUDGETS)}")
            used = BUDGETS[key](ctx)
            ok = used <= limit
            out.append(
                _result("budget", key, ok, f"{used:g} {'<=' if ok else '>'} {limit:g}", used=used)
            )
        return out


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


EXPECT_KEYS = {
    "final_answer",
    "tool_calls",
    "trajectory",
    "forbidden",
    "preconditions",
    "budget",
    "judge",
}


def build_scorers(expect: dict[str, Any]) -> list[Scorer]:
    """Build the deterministic scorers for one case. ``judge`` is handled by the runner."""
    unknown = set(expect) - EXPECT_KEYS
    if unknown:
        raise ValueError(f"unknown expectation {sorted(unknown)}; allowed: {sorted(EXPECT_KEYS)}")
    scorers: list[Scorer] = [NoError()]
    if fa := expect.get("final_answer"):
        scorers.append(FinalAnswer(fa if isinstance(fa, dict) else {"contains": _as_list(fa)}))
    for tc in _as_list(expect.get("tool_calls")):
        scorers.append(ToolCalled(tc if isinstance(tc, dict) else {"name": tc}))
    if tr := expect.get("trajectory"):
        scorers.append(Trajectory(tr if isinstance(tr, dict) else {"steps": tr}))
    for fb in _as_list(expect.get("forbidden")):
        scorers.append(Forbidden(CallSpec.parse(fb)))
    for action, required in (expect.get("preconditions") or {}).items():
        for req in _as_list(required):
            scorers.append(Precondition(action, req))
    if budget := expect.get("budget"):
        scorers.append(Budget(budget))
    return scorers

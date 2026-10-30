from typing import Any

import pytest

from tracejudge.models import Span, Trace
from tracejudge.scorers import ScoreContext, build_scorers, run_scorers
from tracejudge.scorers.deterministic import match_value, validate_schema


def make_trace(calls: list[tuple[str, dict[str, Any]]], llm_calls: int = 2) -> Trace:
    t = Trace(start_ns=0)
    ts = 1
    for _ in range(llm_calls):
        t.spans.append(
            Span(
                trace_id=t.trace_id,
                name="llm",
                kind="llm",
                start_ns=ts,
                end_ns=ts + 1_000_000,
                input_tokens=500,
                output_tokens=50,
                cost_usd=0.001,
            )
        )
        ts += 10
    for name, args in calls:
        t.spans.append(
            Span(
                trace_id=t.trace_id, name=name, kind="tool", start_ns=ts, end_ns=ts + 1, input=args
            )
        )
        ts += 10
    return t


REFUND_FLOW = [
    ("lookup_order", {"order_id": "A100"}),
    ("check_refund_policy", {"order_id": "A100", "reason": "damaged"}),
    ("issue_refund", {"order_id": "A100", "amount": 49.99}),
]


def score(expect: dict[str, Any], calls=REFUND_FLOW, output: Any = "Refund issued.", **kw: Any):
    ctx = ScoreContext(output=output, trace=make_trace(calls, **kw), error=None)
    return run_scorers(build_scorers(expect), ctx)


def verdicts(results) -> dict[str, bool | None]:
    return {f"{r.scorer}:{r.name}": r.passed for r in results}


# ---- value matching ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "actual", "ok"),
    [
        ("A100", "A100", True),
        ("A100", "a100", False),
        (49.99, 49.990000001, True),
        ({"$regex": "^A\\d+$"}, "A100", True),
        ({"$regex": "^B"}, "A100", False),
        ({"$in": ["x", "y"]}, "y", True),
        ({"$any": True}, None, True),
        ({"$gte": 10, "$lte": 50}, 49.99, True),
        ({"$gte": 10, "$lte": 50}, 50.01, False),
        ({"$contains": "Street"}, "12 Main Street", True),
        ({"$contains": "street"}, "12 Main Street", False),
        ({"$icontains": "street"}, "12 Main Street", True),
        ({"$type": "string"}, 3, False),
        ({"city": "Oslo"}, {"city": "Oslo", "zip": "0150"}, True),
        ({"city": "Oslo"}, {"city": "Bergen"}, False),
        ([1, 2], [1, 2], True),
        ([1, 2], [2, 1], False),
    ],
)
def test_match_value(expected: Any, actual: Any, ok: bool) -> None:
    assert match_value(expected, actual) is ok


def test_validate_schema() -> None:
    schema = {
        "type": "object",
        "required": ["order_id", "amount"],
        "properties": {
            "order_id": {"type": "string", "pattern": "^A\\d{3}$"},
            "amount": {"type": "number", "minimum": 0, "maximum": 500},
            "reason": {"enum": ["damaged", "late"]},
        },
        "additionalProperties": False,
    }
    assert validate_schema(schema, {"order_id": "A100", "amount": 5}) == []
    errors = validate_schema(schema, {"order_id": "B1", "amount": -1, "x": 1, "reason": "meh"})
    assert len(errors) == 4
    assert validate_schema(schema, {"amount": 1}) == ["$: missing required 'order_id'"]


# ---- scorers ----------------------------------------------------------------------------


def test_final_answer() -> None:
    res = verdicts(score({"final_answer": {"contains": ["refund"], "not_contains": ["sorry"]}}))
    assert res == {"final_answer:final_answer": True}
    res = verdicts(score({"final_answer": {"regex": "^Refund issued\\.$"}}))
    assert res["final_answer:final_answer"] is True
    res = verdicts(score({"final_answer": {"equals": "nope"}}))
    assert res["final_answer:final_answer"] is False
    dict_output = {"answer": "Refund issued.", "meta": 1}
    res = verdicts(score({"final_answer": {"contains": ["issued"]}}, output=dict_output))
    assert res["final_answer:final_answer"] is True


def test_tool_called_with_args_and_schema() -> None:
    expect = {
        "tool_calls": [
            {"name": "issue_refund", "args": {"order_id": "A100", "amount": {"$lte": 50}}},
            {
                "name": "check_refund_policy",
                "args_schema": {"type": "object", "required": ["reason"]},
            },
            {"name": "escalate", "max_times": 0},
        ]
    }
    res = verdicts(score(expect))
    assert res == {
        "tool_call:issue_refund": True,
        "tool_call:check_refund_policy": True,
        "tool_call:escalate": True,
    }
    bad = score({"tool_calls": [{"name": "issue_refund", "args": {"amount": 10}}]})
    assert bad[0].passed is False
    assert "amount" in bad[0].reason


def test_tool_called_exact_args_and_times() -> None:
    calls = [("lookup_order", {"order_id": "A100"}), ("lookup_order", {"order_id": "A100"})]
    res = score({"tool_calls": [{"name": "lookup_order", "max_times": 1}]}, calls=calls)
    assert res[0].passed is False
    res = score(
        {"tool_calls": [{"name": "lookup_order", "args": {}, "exact_args": True}]}, calls=calls
    )
    assert res[0].passed is False


@pytest.mark.parametrize(
    ("mode", "steps", "ok"),
    [
        ("ordered", ["lookup_order", "issue_refund"], True),
        ("ordered", ["issue_refund", "lookup_order"], False),
        ("exact", ["lookup_order", "check_refund_policy", "issue_refund"], True),
        ("exact", ["lookup_order", "issue_refund"], False),
        ("unordered", ["issue_refund", "lookup_order"], True),
        ("unordered", ["issue_refund", "escalate"], False),
    ],
)
def test_trajectory_modes(mode: str, steps: list[str], ok: bool) -> None:
    (r,) = score({"trajectory": {"mode": mode, "steps": steps}})
    assert r.passed is ok
    assert r.details["actual"] == ["lookup_order", "check_refund_policy", "issue_refund"]


def test_trajectory_divergence_index() -> None:
    calls = [("lookup_order", {"order_id": "A100"}), ("issue_refund", {"order_id": "A100"})]
    expect = {"trajectory": {"mode": "exact", "steps": [s[0] for s in REFUND_FLOW]}}
    (r,) = score(expect, calls=calls)
    assert r.passed is False
    assert r.details["diverged_at"] == 1


def test_trajectory_steps_with_args() -> None:
    steps = [{"name": "lookup_order", "args": {"order_id": "A100"}}, "issue_refund"]
    (r,) = score({"trajectory": {"steps": steps}})
    assert r.passed is True
    steps[0] = {"name": "lookup_order", "args": {"order_id": "Z9"}}
    (r,) = score({"trajectory": {"steps": steps}})
    assert r.passed is False


def test_forbidden_and_preconditions() -> None:
    res = verdicts(
        score(
            {
                "forbidden": [
                    {"name": "issue_refund", "args": {"amount": {"$gt": 100}}},
                    "escalate",
                ],
                "preconditions": {"issue_refund": "check_refund_policy"},
            }
        )
    )
    assert res == {
        "forbidden:issue_refund": True,
        "forbidden:escalate": True,
        "precondition:issue_refund<-check_refund_policy": True,
    }
    skipped_check = [REFUND_FLOW[0], REFUND_FLOW[2]]
    res = score({"preconditions": {"issue_refund": "check_refund_policy"}}, calls=skipped_check)
    assert res[0].passed is False
    res = score({"forbidden": ["issue_refund"]})
    assert res[0].passed is False


def test_budgets() -> None:
    res = verdicts(
        score({"budget": {"max_steps": 2, "max_tool_calls": 3, "max_tokens": 1100}}, llm_calls=2)
    )
    assert all(res.values())
    res = score({"budget": {"max_steps": 1, "max_cost_usd": 0.0001}}, llm_calls=2)
    assert {r.name: r.passed for r in res} == {"max_steps": False, "max_cost_usd": False}


def test_error_fails_and_unknown_key_raises() -> None:
    ctx = ScoreContext(output=None, trace=make_trace([]), error="RuntimeError: boom")
    (r,) = run_scorers(build_scorers({}), ctx)
    assert (r.scorer, r.passed) == ("no_error", False)
    with pytest.raises(ValueError, match="unknown expectation"):
        build_scorers({"tool_calss": []})

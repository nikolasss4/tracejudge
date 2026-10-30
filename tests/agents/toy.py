"""A tiny deterministic agent used by the runner tests."""

from typing import Any

from tracejudge import span, trace


@trace(kind="tool")
def add(a: int, b: int) -> int:
    return a + b


def agent(inp: dict[str, Any]) -> str:
    with span("plan", kind="llm") as s:
        s.set_usage(model="claude-haiku-5-5", input_tokens=100, output_tokens=10)
    if inp.get("crash"):
        raise RuntimeError("crashed")
    if inp.get("flaky") is not None:
        # passes on even trials only, driven by a counter in the input dict
        inp["flaky"] += 1
        if inp["flaky"] % 2:
            return "no idea"
    total = add(inp["a"], inp["b"])
    return f"The sum is {total}."


async def async_agent(inp: dict[str, Any]) -> str:
    return agent(inp)

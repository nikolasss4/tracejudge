"""The support agent loop, runnable on Claude or on the keyless simulated model.

    tracejudge eval examples/support_agent/suite.yaml --agent examples.support_agent.agent:run_v1

Pick the model with SUPPORT_AGENT_MODEL: "simulated" (default, no API key) or a Claude model id
such as "claude-sonnet-5-5".
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any

from examples.support_agent.data import fresh_db
from examples.support_agent.prompts import SYSTEM_V1, SYSTEM_V2, SYSTEM_V3
from examples.support_agent.simulated import SimulatedModel, _latency_scale
from examples.support_agent.tools import TOOL_DEFS, TOOLS, use_db

MAX_STEPS = 8


class ClaudeModel:
    def __init__(self, model: str) -> None:
        import anthropic

        from tracejudge.adapters import instrument_anthropic

        self.name = model
        self.client = instrument_anthropic(anthropic.Anthropic())

    def respond(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        response = self.client.messages.create(
            model=self.name,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason == "refusal":
            return response.content, [{"type": "text", "text": "(the model declined)"}]
        blocks = [b.model_dump() for b in response.content if b.type in ("text", "tool_use")]
        # Return the full content (thinking blocks included) for the history.
        return response.content, blocks


def make_model() -> Any:
    name = os.environ.get("SUPPORT_AGENT_MODEL", "simulated")
    if name == "simulated":
        return SimulatedModel()
    return ClaudeModel(name)


def run_agent(inp: dict[str, Any], system: str, model: Any | None = None) -> str:
    model = model or make_model()
    use_db(fresh_db())
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"customer_id: {inp['customer_id']}\n{inp['message']}"}
    ]
    for _ in range(MAX_STEPS):
        history_content, blocks = model.respond(system, messages, TOOL_DEFS)
        messages.append({"role": "assistant", "content": history_content})
        tool_uses = [b for b in blocks if b["type"] == "tool_use"]
        if not tool_uses:
            return "\n".join(b["text"] for b in blocks if b["type"] == "text").strip()
        results = []
        for tu in tool_uses:
            fn = TOOLS.get(tu["name"])
            if isinstance(model, SimulatedModel):
                time.sleep(_latency_scale() * random.uniform(0.005, 0.04))
            try:
                out = fn(**tu["input"]) if fn else {"error": f"unknown tool {tu['name']}"}
            except TypeError as exc:
                out = {"error": f"bad arguments: {exc}"}
            results.append(
                {"type": "tool_result", "tool_use_id": tu["id"], "content": json.dumps(out)}
            )
        messages.append({"role": "user", "content": results})
    return "(stopped: step budget exhausted)"


def run_v1(inp: dict[str, Any]) -> str:
    return run_agent(inp, SYSTEM_V1)


def run_v2(inp: dict[str, Any]) -> str:
    return run_agent(inp, SYSTEM_V2)


def run_v3(inp: dict[str, Any]) -> str:
    return run_agent(inp, SYSTEM_V3)

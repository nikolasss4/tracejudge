import asyncio
import json
from typing import Any

import anthropic
import httpx2
import pytest

from tracejudge import capture
from tracejudge.adapters import instrument_anthropic, instrument_openai

MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [
        {"type": "tool_use", "id": "tu_1", "name": "lookup_order", "input": {"order_id": "A1"}}
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 0},
}


def fake_transport(request: httpx2.Request) -> httpx2.Response:
    assert request.url.path == "/v1/messages"
    return httpx2.Response(200, json=MESSAGE)


def test_anthropic_adapter_records_llm_span() -> None:
    client = anthropic.Anthropic(
        api_key="test",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(fake_transport)),
    )
    instrument_anthropic(client)
    instrument_anthropic(client)  # idempotent
    with capture() as t:
        client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=1024,
            system="be helpful",
            tools=[{"name": "lookup_order", "input_schema": {"type": "object"}}],
            messages=[{"role": "user", "content": "where is A1?"}],
        )
    assert len(t.spans) == 1
    s = t.spans[0]
    assert s.kind == "llm" and s.model == "claude-sonnet-5-5"
    assert (s.input_tokens, s.output_tokens) == (1200, 80)
    assert s.cost_usd == pytest.approx((1200 * 2 + 80 * 10) / 1e6)
    assert s.input["tools"] == ["lookup_order"]
    assert s.output["content"][0]["name"] == "lookup_order"
    assert s.attributes["gen_ai.system"] == "anthropic"
    json.dumps(s.model_dump())


class FakeCompletions:
    def __init__(self, is_async: bool) -> None:
        self.is_async = is_async

    def _response(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "model": kwargs["model"],
            "choices": [
                {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }


class SyncCompletions(FakeCompletions):
    def create(self, **kwargs: Any) -> dict[str, Any]:
        return self._response(**kwargs)


class AsyncCompletions(FakeCompletions):
    async def create(self, **kwargs: Any) -> dict[str, Any]:
        return self._response(**kwargs)


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


def test_openai_adapter_sync_and_async() -> None:
    sync = instrument_openai(FakeClient(SyncCompletions(False)), system="vllm")
    async_client = instrument_openai(FakeClient(AsyncCompletions(True)))
    with capture() as t:
        sync.chat.completions.create(model="qwen3", messages=[{"role": "user", "content": "x"}])
        asyncio.run(async_client.chat.completions.create(model="qwen3", messages=[]))
    assert [s.output_tokens for s in t.spans] == [3, 3]
    assert t.spans[0].attributes["gen_ai.system"] == "vllm"
    assert t.spans[0].cost_usd is None  # no registered price, so no guessed cost

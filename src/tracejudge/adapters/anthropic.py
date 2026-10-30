"""Record Anthropic SDK ``messages.create`` calls as ``llm`` spans.

    client = instrument_anthropic(anthropic.Anthropic())

Works with both ``Anthropic`` and ``AsyncAnthropic``. Streaming calls (``messages.stream``) are
not wrapped yet; record them with ``span(kind="llm")`` and ``set_usage`` yourself.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

from tracejudge.pricing import cost_usd
from tracejudge.sdk import SpanHandle, span, to_jsonable

_PATCHED = "_tracejudge_instrumented"


def _request_input(kwargs: dict[str, Any]) -> dict[str, Any]:
    keep = ("model", "system", "messages", "max_tokens", "tool_choice", "output_config")
    inp = {k: to_jsonable(kwargs[k]) for k in keep if k in kwargs}
    if "tools" in kwargs:
        inp["tools"] = [t.get("name", t.get("type")) for t in to_jsonable(kwargs["tools"])]
    return inp


def _record_response(h: SpanHandle, response: Any, requested_model: str | None) -> None:
    data = to_jsonable(response)
    usage = data.get("usage") or {}
    model = data.get("model") or requested_model
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    h.set_output({"content": data.get("content"), "stop_reason": data.get("stop_reason")})
    h.set_usage(
        model=model,
        input_tokens=inp + cache_read + cache_write,
        output_tokens=out,
        cost_usd=cost_usd(model, inp, out, cache_read, cache_write),
    )
    h.set_attribute("gen_ai.response.finish_reasons", [data.get("stop_reason")])
    if cache_read:
        h.set_attribute("gen_ai.usage.cache_read_input_tokens", cache_read)


def instrument_anthropic(client: Any) -> Any:
    """Patch ``client.messages.create`` in place and return the client."""
    messages = client.messages
    if getattr(messages, _PATCHED, False):
        return client
    original = messages.create

    def start(kwargs: dict[str, Any]) -> Any:
        model = kwargs.get("model")
        return span(
            f"anthropic.messages {model}",
            kind="llm",
            input=_request_input(kwargs),
            **{"gen_ai.system": "anthropic", "gen_ai.request.model": model},
        )

    if inspect.iscoroutinefunction(original):

        @functools.wraps(original)
        async def acreate(*args: Any, **kwargs: Any) -> Any:
            with start(kwargs) as h:
                response = await original(*args, **kwargs)
                _record_response(h, response, kwargs.get("model"))
                return response

        messages.create = acreate
    else:

        @functools.wraps(original)
        def create(*args: Any, **kwargs: Any) -> Any:
            with start(kwargs) as h:
                response = original(*args, **kwargs)
                _record_response(h, response, kwargs.get("model"))
                return response

        messages.create = create
    setattr(messages, _PATCHED, True)
    return client

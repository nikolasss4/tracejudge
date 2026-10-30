"""Record ``chat.completions.create`` calls from any OpenAI-compatible client as ``llm`` spans.

This covers the OpenAI SDK pointed at vLLM, Ollama, LM Studio, MLX servers and other
OpenAI-compatible endpoints. The adapter is duck-typed and does not import ``openai``.
Register prices for your models with ``tracejudge.pricing.register_price`` to get costs.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

from tracejudge.sdk import SpanHandle, span, to_jsonable

_PATCHED = "_tracejudge_instrumented"


def _record(h: SpanHandle, response: Any, requested_model: str | None) -> None:
    data = to_jsonable(response)
    usage = data.get("usage") or {}
    choices = data.get("choices") or []
    first = choices[0] if choices else {}
    h.set_output({"message": first.get("message"), "finish_reason": first.get("finish_reason")})
    h.set_usage(
        model=data.get("model") or requested_model,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )
    h.set_attribute("gen_ai.response.finish_reasons", [c.get("finish_reason") for c in choices])


def instrument_openai(client: Any, system: str = "openai") -> Any:
    """Patch ``client.chat.completions.create`` in place and return the client."""
    completions = client.chat.completions
    if getattr(completions, _PATCHED, False):
        return client
    original = completions.create

    def start(kwargs: dict[str, Any]) -> Any:
        model = kwargs.get("model")
        inp = {k: to_jsonable(kwargs[k]) for k in ("model", "messages", "tools") if k in kwargs}
        return span(
            f"chat.completions {model}",
            kind="llm",
            input=inp,
            **{"gen_ai.system": system, "gen_ai.request.model": model},
        )

    if inspect.iscoroutinefunction(original):

        @functools.wraps(original)
        async def acreate(*args: Any, **kwargs: Any) -> Any:
            with start(kwargs) as h:
                response = await original(*args, **kwargs)
                _record(h, response, kwargs.get("model"))
                return response

        completions.create = acreate
    else:

        @functools.wraps(original)
        def create(*args: Any, **kwargs: Any) -> Any:
            with start(kwargs) as h:
                response = original(*args, **kwargs)
                _record(h, response, kwargs.get("model"))
                return response

        completions.create = create
    setattr(completions, _PATCHED, True)
    return client

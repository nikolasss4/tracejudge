"""Tracing SDK: record spans from any Python agent with a decorator or a context manager.

    from tracejudge import trace, span

    @trace(kind="tool")
    def lookup_order(order_id: str) -> dict: ...

    with span("plan", kind="custom") as s:
        s.set_output(plan)

Spans nest through ``contextvars``, so they work across ``async`` code too. The outermost span
starts a trace; when it ends the finished trace goes to the configured sink (a SQLite store, a
callback, or the eval runner's capture buffer).
"""

from __future__ import annotations

import functools
import inspect
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, overload

from tracejudge.models import Span, SpanKind, Trace

P = ParamSpec("P")
R = TypeVar("R")

_current_trace: ContextVar[Trace | None] = ContextVar("tracejudge_trace", default=None)
_current_span: ContextVar[Span | None] = ContextVar("tracejudge_span", default=None)
_sink: Callable[[Trace], None] | None = None


def configure(db: str | Path | None = None, sink: Callable[[Trace], None] | None = None) -> None:
    """Send finished traces to a SQLite database, a callback, or both."""
    global _sink
    sinks: list[Callable[[Trace], None]] = []
    if db is not None:
        from tracejudge.store import Store

        sinks.append(Store(db).save_trace)
    if sink is not None:
        sinks.append(sink)
    if not sinks:
        _sink = None
        return

    def fan_out(t: Trace) -> None:
        for fn in sinks:
            fn(t)

    _sink = fan_out


def _default_sink() -> Callable[[Trace], None] | None:
    if _sink is not None:
        return _sink
    if db := os.environ.get("TRACEJUDGE_DB"):
        configure(db=db)
    return _sink


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """Best-effort conversion of arbitrary values (pydantic models, SDK objects) to JSON."""
    if _depth > 20:
        return repr(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_jsonable(v, _depth + 1) for v in value]
    for attr in ("model_dump", "to_dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return to_jsonable(fn(), _depth + 1)
            except TypeError:
                pass
    if hasattr(value, "__dict__"):
        return {
            k: to_jsonable(v, _depth + 1) for k, v in vars(value).items() if not k.startswith("_")
        }
    return repr(value)


class SpanHandle:
    """What ``span()`` yields: lets the caller attach output, usage and attributes."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def set_input(self, value: Any) -> None:
        self.span.input = to_jsonable(value)

    def set_output(self, value: Any) -> None:
        self.span.output = to_jsonable(value)

    def set_attribute(self, key: str, value: Any) -> None:
        self.span.attributes[key] = to_jsonable(value)

    def set_usage(
        self,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        from tracejudge.pricing import cost_usd as price

        if model:
            self.span.model = model
        if input_tokens is not None:
            self.span.input_tokens = input_tokens
        if output_tokens is not None:
            self.span.output_tokens = output_tokens
        if cost_usd is None and self.span.model:
            cost_usd = price(self.span.model, input_tokens or 0, output_tokens or 0)
        self.span.cost_usd = cost_usd

    def set_error(self, message: str) -> None:
        self.span.status = "error"
        self.span.error = message


@contextmanager
def capture(name: str = "trace", **attributes: Any) -> Iterator[Trace]:
    """Collect every span opened inside the block into one trace, without sending it anywhere.

    The eval runner uses this to get the trace of each test case.
    """
    t = Trace(name=name, start_ns=time.time_ns(), attributes=to_jsonable(attributes))
    trace_token = _current_trace.set(t)
    span_token = _current_span.set(None)
    try:
        yield t
    finally:
        t.end_ns = time.time_ns()
        _current_span.reset(span_token)
        _current_trace.reset(trace_token)


@contextmanager
def span(
    name: str, kind: SpanKind = "custom", input: Any = None, **attributes: Any
) -> Iterator[SpanHandle]:
    """Record a span around the block. Exceptions mark the span as an error and re-raise."""
    t = _current_trace.get()
    owns_trace = t is None
    if t is None:
        t = Trace(name=name, start_ns=time.time_ns())
    parent = _current_span.get()
    s = Span(
        trace_id=t.trace_id,
        parent_id=parent.span_id if parent else None,
        name=name,
        kind=kind,
        start_ns=time.time_ns(),
        input=to_jsonable(input),
        attributes=to_jsonable(attributes),
    )
    t.spans.append(s)
    trace_token = _current_trace.set(t) if owns_trace else None
    span_token = _current_span.set(s)
    handle = SpanHandle(s)
    try:
        yield handle
    except BaseException as exc:
        handle.set_error(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        s.end_ns = time.time_ns()
        _current_span.reset(span_token)
        if trace_token is not None:
            _current_trace.reset(trace_token)
            t.end_ns = s.end_ns
            sink = _default_sink()
            if sink is not None:
                sink(t)


def current_span() -> SpanHandle | None:
    s = _current_span.get()
    return SpanHandle(s) if s else None


def _bound_input(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
    except TypeError:
        return {"args": args, "kwargs": kwargs}
    bound.apply_defaults()
    return {k: v for k, v in bound.arguments.items() if k not in ("self", "cls")}


@overload
def trace(fn: Callable[P, R], /) -> Callable[P, R]: ...
@overload
def trace(
    *, name: str | None = None, kind: SpanKind = "custom", capture_input: bool = True
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def trace(
    fn: Callable[P, R] | None = None,
    /,
    *,
    name: str | None = None,
    kind: SpanKind = "custom",
    capture_input: bool = True,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that records a span for each call: arguments in, return value out."""

    def decorate(func: Callable[P, R]) -> Callable[P, R]:
        span_name = name or func.__name__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                inp = _bound_input(func, args, kwargs) if capture_input else None
                with span(span_name, kind=kind, input=inp) as h:
                    result = await func(*args, **kwargs)
                    h.set_output(result)
                    return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            inp = _bound_input(func, args, kwargs) if capture_input else None
            with span(span_name, kind=kind, input=inp) as h:
                result = func(*args, **kwargs)
                h.set_output(result)
                return result

        return wrapper

    if fn is not None:
        return decorate(fn)
    return decorate

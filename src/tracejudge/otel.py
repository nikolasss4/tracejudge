"""OpenTelemetry ingestion: turn OTLP trace exports into tracejudge spans.

Supports OTLP/HTTP with JSON bodies out of the box and protobuf bodies when the optional
``opentelemetry-proto`` package is installed (``pip install tracejudge[otlp]``).

Span kinds and LLM fields are read from the OpenTelemetry GenAI semantic conventions
(``gen_ai.operation.name``, ``gen_ai.usage.*``, ``gen_ai.tool.*``, ``gen_ai.input.messages``
and friends), with fallbacks for the older ``gen_ai.prompt``/``gen_ai.completion`` attributes and
for OpenInference (``openinference.span.kind``), so traces from most agent frameworks map
cleanly. Anything that isn't recognised is kept as a plain ``custom`` span with its attributes.
"""

from __future__ import annotations

import base64
import json
import re
import zlib
from typing import Any

from tracejudge.models import Span, SpanKind
from tracejudge.pricing import cost_usd

MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_SPANS_PER_REQUEST = 20_000
MAX_ATTR_CHARS = 256 * 1024

_HEX = re.compile(r"^[0-9a-fA-F]+$")

LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "embeddings", "completion"}
AGENT_OPERATIONS = {"invoke_agent", "create_agent"}
OPENINFERENCE_KINDS: dict[str, SpanKind] = {
    "LLM": "llm",
    "EMBEDDING": "llm",
    "TOOL": "tool",
    "RETRIEVER": "retrieval",
    "RERANKER": "retrieval",
    "AGENT": "agent",
}


class OTLPError(ValueError):
    """The request body is not a valid OTLP trace export."""


def decode_body(body: bytes, content_encoding: str | None) -> bytes:
    """Undo gzip/deflate, refusing anything that inflates past MAX_BODY_BYTES."""
    enc = (content_encoding or "").lower().strip()
    if enc in ("", "identity"):
        data = body
    elif enc in ("gzip", "deflate"):
        wbits = 16 + zlib.MAX_WBITS if enc == "gzip" else zlib.MAX_WBITS
        d = zlib.decompressobj(wbits)
        try:
            data = d.decompress(body, MAX_BODY_BYTES + 1)
        except zlib.error as exc:
            raise OTLPError(f"bad {enc} body") from exc
        if d.unconsumed_tail:
            raise OTLPError("body too large after decompression")
    else:
        raise OTLPError(f"unsupported content-encoding {enc!r}")
    if len(data) > MAX_BODY_BYTES:
        raise OTLPError("body too large")
    return data


def _any_value(v: dict[str, Any]) -> Any:
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "arrayValue" in v:
        return [_any_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return _attributes(v["kvlistValue"].get("values", []))
    if "bytesValue" in v:
        return v["bytesValue"]
    return None


def _attributes(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        key = item.get("key")
        if not isinstance(key, str):
            continue
        val = _any_value(item.get("value", {}))
        if isinstance(val, str) and len(val) > MAX_ATTR_CHARS:
            val = val[:MAX_ATTR_CHARS] + "…[truncated]"
        out[key] = val
    return out


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _id(value: Any, nbytes: int, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise OTLPError(f"missing {field}")
    if len(value) == nbytes * 2 and _HEX.match(value):
        return value.lower()
    # Some exporters (and protobuf -> JSON conversion) produce base64 ids.
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise OTLPError(f"bad {field}") from exc
    if len(raw) != nbytes:
        raise OTLPError(f"bad {field}")
    return raw.hex()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _legacy_prompt(attrs: dict[str, Any], prefix: str) -> list[dict[str, Any]] | None:
    """Collect OpenLLMetry-style ``gen_ai.prompt.0.role`` / ``.content`` attributes."""
    msgs: dict[int, dict[str, Any]] = {}
    pat = re.compile(rf"^{re.escape(prefix)}\.(\d+)\.(\w+)$")
    for k, v in attrs.items():
        if m := pat.match(k):
            msgs.setdefault(int(m.group(1)), {})[m.group(2)] = v
    return [msgs[i] for i in sorted(msgs)] or None


def _classify(name: str, attrs: dict[str, Any]) -> SpanKind:
    op = attrs.get("gen_ai.operation.name")
    if op in LLM_OPERATIONS:
        return "llm"
    if op == "execute_tool":
        return "tool"
    if op in AGENT_OPERATIONS:
        return "agent"
    if op == "retrieval":
        return "retrieval"
    oi = attrs.get("openinference.span.kind")
    if isinstance(oi, str) and oi.upper() in OPENINFERENCE_KINDS:
        return OPENINFERENCE_KINDS[oi.upper()]
    if "gen_ai.request.model" in attrs or "gen_ai.usage.input_tokens" in attrs:
        return "llm"
    if "gen_ai.tool.name" in attrs:
        return "tool"
    return "custom"


def _events_as_messages(events: list[dict[str, Any]]) -> tuple[list[Any], list[Any]]:
    """Older GenAI conventions put messages in span events (gen_ai.user.message, gen_ai.choice)."""
    inputs, outputs = [], []
    for ev in events:
        name = ev.get("name", "")
        body = _attributes(ev.get("attributes"))
        if name == "gen_ai.choice":
            outputs.append(_maybe_json(body.get("message", body)))
        elif name.startswith("gen_ai.") and name.endswith(".message"):
            role = name.removeprefix("gen_ai.").removesuffix(".message")
            content = _maybe_json(body.get("content", body))
            inputs.append({"role": role, "content": content})
    return inputs, outputs


def _to_span(raw: dict[str, Any], resource: dict[str, Any]) -> Span:
    attrs = _attributes(raw.get("attributes"))
    name = str(raw.get("name") or "span")[:500]
    kind = _classify(name, attrs)
    status = raw.get("status") or {}
    is_error = _int(status.get("code")) == 2 or status.get("code") == "STATUS_CODE_ERROR"
    parent = raw.get("parentSpanId") or None

    inp: Any = None
    out: Any = None
    model = attrs.get("gen_ai.response.model") or attrs.get("gen_ai.request.model")
    in_tok = attrs.get("gen_ai.usage.input_tokens", attrs.get("gen_ai.usage.prompt_tokens"))
    out_tok = attrs.get("gen_ai.usage.output_tokens", attrs.get("gen_ai.usage.completion_tokens"))

    if kind == "llm":
        system = attrs.get("gen_ai.system_instructions")
        messages = _maybe_json(attrs.get("gen_ai.input.messages")) or _legacy_prompt(
            attrs, "gen_ai.prompt"
        )
        output = _maybe_json(attrs.get("gen_ai.output.messages")) or _legacy_prompt(
            attrs, "gen_ai.completion"
        )
        ev_in, ev_out = _events_as_messages(raw.get("events") or [])
        messages = messages or ev_in or _maybe_json(attrs.get("input.value"))
        output = output or ev_out or _maybe_json(attrs.get("output.value"))
        inp = {"model": model, "messages": messages}
        if system:
            inp["system"] = _maybe_json(system)
        out = output
        model = model or attrs.get("llm.model_name")
        in_tok = in_tok if in_tok is not None else attrs.get("llm.token_count.prompt")
        out_tok = out_tok if out_tok is not None else attrs.get("llm.token_count.completion")
    elif kind == "tool":
        name = str(attrs.get("gen_ai.tool.name") or attrs.get("tool.name") or name)
        args = attrs.get("gen_ai.tool.call.arguments", attrs.get("input.value"))
        inp = _maybe_json(args)
        out = _maybe_json(attrs.get("gen_ai.tool.call.result", attrs.get("output.value")))
    else:
        inp = _maybe_json(attrs.get("input.value"))
        out = _maybe_json(attrs.get("output.value"))
        if kind == "agent":
            name = str(attrs.get("gen_ai.agent.name") or name)

    if resource.get("service.name"):
        attrs.setdefault("service.name", resource["service.name"])
    in_tokens = _int(in_tok) if in_tok is not None else None
    out_tokens = _int(out_tok) if out_tok is not None else None
    cost = None
    if kind == "llm" and (in_tokens or out_tokens):
        cost = cost_usd(model, in_tokens or 0, out_tokens or 0)

    return Span(
        trace_id=_id(raw.get("traceId"), 16, "traceId"),
        span_id=_id(raw.get("spanId"), 8, "spanId"),
        parent_id=_id(parent, 8, "parentSpanId") if parent else None,
        name=name,
        kind=kind,
        start_ns=_int(raw.get("startTimeUnixNano")),
        end_ns=_int(raw.get("endTimeUnixNano")) or None,
        status="error" if is_error else "ok",
        error=(status.get("message") or "error") if is_error else None,
        input=inp,
        output=out,
        attributes=attrs,
        model=str(model) if model else None,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
        cost_usd=cost,
    )


def parse_otlp_json(payload: Any) -> list[Span]:
    """Parse an OTLP ``ExportTraceServiceRequest`` in its JSON encoding."""
    if not isinstance(payload, dict):
        raise OTLPError("expected a JSON object")
    spans: list[Span] = []
    for rs in payload.get("resourceSpans") or []:
        resource = _attributes((rs.get("resource") or {}).get("attributes"))
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
            for raw in ss.get("spans") or []:
                if len(spans) >= MAX_SPANS_PER_REQUEST:
                    raise OTLPError("too many spans in one request")
                if isinstance(raw, dict):
                    spans.append(_to_span(raw, resource))
    return spans


def parse_otlp_protobuf(data: bytes) -> list[Span]:
    """Parse a protobuf-encoded export. Requires the ``opentelemetry-proto`` package."""
    try:
        from google.protobuf.json_format import MessageToDict
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise OTLPError(
            "protobuf OTLP needs `pip install tracejudge[otlp]`; or export with "
            "OTEL_EXPORTER_OTLP_PROTOCOL=http/json"
        ) from exc
    msg = ExportTraceServiceRequest()
    try:
        msg.ParseFromString(data)
    except Exception as exc:
        raise OTLPError("bad protobuf body") from exc
    # MessageToDict renders bytes ids as base64; _id() accepts both encodings.
    return parse_otlp_json(MessageToDict(msg))


def parse_request(
    body: bytes, content_type: str | None, content_encoding: str | None
) -> list[Span]:
    data = decode_body(body, content_encoding)
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in ("application/x-protobuf", "application/protobuf"):
        return parse_otlp_protobuf(data)
    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OTLPError("body is not valid JSON") from exc
    return parse_otlp_json(payload)

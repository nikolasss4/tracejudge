import gzip
import json
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tracejudge import otel
from tracejudge.server import create_app
from tracejudge.store import Store

DATA = Path(__file__).parent / "data" / "otlp_genai.json"


def payload() -> dict:
    return json.loads(DATA.read_text())


def test_genai_mapping() -> None:
    spans = {s.name: s for s in otel.parse_otlp_json(payload())}
    agent = spans["weather"]
    assert agent.kind == "agent" and agent.parent_id is None
    llm = spans["chat claude-sonnet-5-5"]
    assert llm.kind == "llm" and llm.model == "claude-sonnet-5-5"
    assert (llm.input_tokens, llm.output_tokens) == (1500, 60)
    assert llm.cost_usd == pytest.approx((1500 * 2 + 60 * 10) / 1e6)
    assert llm.input["messages"][0]["parts"][0]["content"] == "Weather in Paris?"
    assert llm.attributes["service.name"] == "weather-agent"
    tool = spans["get_weather"]
    assert tool.kind == "tool" and tool.input == {"city": "Paris"}
    assert tool.output == {"temp_c": 18}
    assert tool.status == "error" and tool.error == "upstream timeout"
    assert spans["vector search"].kind == "retrieval"
    assert agent.duration_ms == 2500


def test_legacy_prompt_attributes_and_base64_ids() -> None:
    raw = {
        "traceId": "W47/95gDgQPSabYzgT/GDA==",
        "spanId": "7uGbfsPBsXQ=",
        "name": "openai.chat",
        "startTimeUnixNano": "1",
        "endTimeUnixNano": "2",
        "attributes": [
            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-x"}},
            {"key": "gen_ai.prompt.0.role", "value": {"stringValue": "user"}},
            {"key": "gen_ai.prompt.0.content", "value": {"stringValue": "hi"}},
            {"key": "gen_ai.usage.prompt_tokens", "value": {"intValue": 3}},
        ],
    }
    req = {"resourceSpans": [{"scopeSpans": [{"spans": [raw]}]}]}
    (s,) = otel.parse_otlp_json(req)
    assert s.trace_id == "5b8efff798038103d269b633813fc60c"
    assert s.span_id == "eee19b7ec3c1b174"
    assert s.kind == "llm" and s.input["messages"] == [{"role": "user", "content": "hi"}]
    assert s.input_tokens == 3 and s.cost_usd is None


@pytest.mark.parametrize("bad", [[], {"resourceSpans": [{"scopeSpans": [{"spans": [{}]}]}]}])
def test_rejects_malformed(bad: object) -> None:
    with pytest.raises(otel.OTLPError):
        otel.parse_otlp_json(bad)


def test_decompression_bomb_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(otel, "MAX_BODY_BYTES", 1000)
    bomb = gzip.compress(b"0" * 100_000)
    with pytest.raises(otel.OTLPError, match="too large"):
        otel.decode_body(bomb, "gzip")
    assert otel.decode_body(zlib.compress(b"{}"), "deflate") == b"{}"


def test_endpoint_stores_spans(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    client = TestClient(create_app(store, otlp_token=""))
    body = gzip.compress(json.dumps(payload()).encode())
    r = client.post(
        "/v1/traces",
        content=body,
        headers={"content-type": "application/json", "content-encoding": "gzip"},
    )
    assert r.status_code == 200, r.text
    t = store.get_trace("5b8efff798038103d269b633813fc60c")
    assert t is not None and len(t.spans) == 4 and t.name == "weather"
    assert t.source == "otlp"
    assert client.post("/v1/traces", content=b"nope").status_code == 400


def test_endpoint_token(tmp_path: Path) -> None:
    client = TestClient(create_app(Store(tmp_path / "t.db"), otlp_token="s3cret"))
    assert client.post("/v1/traces", json=payload()).status_code == 401
    ok = client.post("/v1/traces", json=payload(), headers={"authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_protobuf_export_from_real_otel_sdk(tmp_path: Path) -> None:
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("invoke_agent support") as root:
        root.set_attribute("gen_ai.operation.name", "invoke_agent")
        with tracer.start_as_current_span("chat claude-haiku-5-5") as llm:
            llm.set_attribute("gen_ai.operation.name", "chat")
            llm.set_attribute("gen_ai.request.model", "claude-haiku-5-5")
            llm.set_attribute("gen_ai.usage.input_tokens", 400)
            llm.set_attribute("gen_ai.usage.output_tokens", 40)
    body = encode_spans(exporter.get_finished_spans()).SerializeToString()

    store = Store(tmp_path / "t.db")
    client = TestClient(create_app(store, otlp_token=""))
    r = client.post("/v1/traces", content=body, headers={"content-type": "application/x-protobuf"})
    assert r.status_code == 200, r.text
    (summary,) = store.list_traces()
    t = store.get_trace(summary["trace_id"])
    assert t is not None
    kinds = {s.name: s.kind for s in t.spans}
    assert kinds == {"invoke_agent support": "agent", "chat claude-haiku-5-5": "llm"}
    assert t.total_tokens == 440


def test_cli_imports_otlp_json(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from tracejudge.cli import app

    db = tmp_path / "t.db"
    result = CliRunner().invoke(app, ["import", str(DATA), "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert Store(db).get_trace("5b8efff798038103d269b633813fc60c") is not None

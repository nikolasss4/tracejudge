# ADR 0002: Map OpenTelemetry GenAI spans onto five span kinds

**Status:** accepted

## Context

Agents are built with many frameworks. Most can export OpenTelemetry, but they disagree on
attributes: the GenAI semantic conventions have moved from `gen_ai.prompt.N.*` attributes and
span events to `gen_ai.input.messages` / `gen_ai.output.messages`, `gen_ai.system` became
`gen_ai.provider.name`, and OpenInference (Arize Phoenix) uses its own `openinference.span.kind`.

## Decision

Normalise everything to five kinds (`agent`, `llm`, `tool`, `retrieval`, `custom`) at ingestion:

1. `gen_ai.operation.name` decides first (`chat`/`text_completion`/`embeddings` → llm,
   `execute_tool` → tool, `invoke_agent` → agent).
2. Else `openinference.span.kind`.
3. Else the presence of `gen_ai.request.model` / usage (llm) or `gen_ai.tool.name` (tool).
4. Everything else is `custom`, with all attributes kept.

Messages come from the newest convention available, falling back to legacy attributes, then
span events, then OpenInference `input.value`. Ids are accepted as hex or base64 (protobuf → JSON
conversion yields base64). Cost is computed from tokens and the model's price when known.

## Consequences

- The viewer, scorers and judge only ever see one shape; tool-call scorers work on OTLP traces
  exactly as on SDK traces.
- The OTLP endpoint is an attack surface: body size (16 MiB, also after decompression), span
  count and attribute length are capped, an optional bearer token is supported, and cross-origin
  browser writes are refused.

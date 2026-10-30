"""HTTP server: the OTLP trace endpoint plus the JSON API and static files for the viewer."""

from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, HTTPException, Request, Response

from tracejudge import otel
from tracejudge.store import Store


def create_app(store: Store, otlp_token: str | None = None) -> FastAPI:
    app = FastAPI(title="tracejudge", version="0.1.0")
    token = otlp_token if otlp_token is not None else os.environ.get("TRACEJUDGE_OTLP_TOKEN")

    @app.post("/v1/traces")
    async def otlp_traces(request: Request) -> Response:
        """OTLP/HTTP trace receiver (point OTEL_EXPORTER_OTLP_ENDPOINT at this server)."""
        if token:
            auth = request.headers.get("authorization", "")
            if not hmac.compare_digest(auth, f"Bearer {token}"):
                raise HTTPException(401, "missing or bad bearer token")
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > otel.MAX_BODY_BYTES:
            raise HTTPException(413, "body too large")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > otel.MAX_BODY_BYTES:
                raise HTTPException(413, "body too large")
        ctype = request.headers.get("content-type")
        try:
            spans = otel.parse_request(bytes(body), ctype, request.headers.get("content-encoding"))
        except otel.OTLPError as exc:
            raise HTTPException(400, str(exc)) from exc
        if spans:
            store.add_spans(spans)
        if ctype and "protobuf" in ctype:
            return Response(b"", media_type="application/x-protobuf")
        return Response(b"{}", media_type="application/json")

    return app

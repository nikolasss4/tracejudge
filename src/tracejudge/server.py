"""HTTP server: the OTLP trace endpoint plus the JSON API and static files for the viewer."""

from __future__ import annotations

import hmac
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tracejudge import __version__, otel
from tracejudge.calibration import calibrate, label_queue
from tracejudge.diff import diff_runs
from tracejudge.models import CaseResult, Label, Run
from tracejudge.store import Store

STATIC_DIR = Path(__file__).parent / "static"


class LabelIn(BaseModel):
    case_result_id: str
    criterion: str
    human_pass: bool
    note: str = ""
    labeler: str = ""


def _run_or_404(store: Store, run_id: str) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"no run {run_id!r}")
    return run


def _case_rows(results: list[CaseResult]) -> list[dict[str, Any]]:
    """Group trials by case for the run page."""
    grouped: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        grouped[r.case_id].append(r)
    rows = []
    for case_id, trials in grouped.items():
        failing = sorted(
            {f"{s.scorer}:{s.name}" for t in trials for s in t.scores if s.passed is False}
        )
        rows.append(
            {
                "case_id": case_id,
                "tags": trials[0].tags,
                "passed": sum(t.passed for t in trials),
                "trials": len(trials),
                "failing": failing,
                "cost_usd": sum(t.cost_usd for t in trials) / len(trials),
                "latency_ms": sum(t.latency_ms for t in trials) / len(trials),
                "steps": sum(t.steps for t in trials) / len(trials),
                "results": [
                    {
                        "id": t.id,
                        "trial": t.trial,
                        "passed": t.passed,
                        "trace_id": t.trace_id,
                        "error": t.error,
                        "latency_ms": t.latency_ms,
                        "cost_usd": t.cost_usd,
                    }
                    for t in trials
                ],
            }
        )
    return rows


def create_app(store: Store, otlp_token: str | None = None) -> FastAPI:
    app = FastAPI(title="tracejudge", version=__version__)
    token = otlp_token if otlp_token is not None else os.environ.get("TRACEJUDGE_OTLP_TOKEN")

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next: Any) -> Any:
        """Refuse cross-site writes. Browsers send an Origin header on cross-origin POSTs, and
        a plain-text POST needs no CORS preflight, so without this any web page could write
        labels or traces into a server running on localhost. OTLP exporters send no Origin."""
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            host = request.headers.get("host", "")
            if origin.split("://", 1)[-1] != host:
                return JSONResponse({"detail": "cross-origin write refused"}, status_code=403)
        return await call_next(request)

    # ---- OTLP ---------------------------------------------------------------------------

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

    # ---- API ----------------------------------------------------------------------------

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {"version": __version__, "db": str(store.path)}

    @app.get("/api/runs")
    def list_runs(
        suite: str | None = None, model: str | None = None, sha: str | None = None
    ) -> list[dict[str, Any]]:
        out = []
        for r in store.list_runs(suite=suite, model=model, git_sha=sha):
            d = r.model_dump(mode="json")
            d["summary"].pop("per_case", None)
            out.append(d)
        return out

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = _run_or_404(store, run_id)
        results = store.case_results(run.run_id)
        labels = store.labels(run.run_id)
        return {
            "run": run.model_dump(mode="json"),
            "cases": _case_rows(results),
            "trials": [
                {
                    "id": r.id,
                    "case_id": r.case_id,
                    "trial": r.trial,
                    "passed": r.passed,
                    "latency_ms": r.latency_ms,
                    "cost_usd": r.cost_usd,
                    "tokens": r.input_tokens + r.output_tokens,
                    "steps": r.steps,
                }
                for r in results
            ],
            "labels": len(labels),
        }

    @app.get("/api/results/{result_id}")
    def get_result(result_id: str) -> dict[str, Any]:
        cr = store.get_case_result(result_id)
        if cr is None:
            raise HTTPException(404, "no such result")
        trace = store.get_trace(cr.trace_id) if cr.trace_id else None
        labels = [
            lb.model_dump(mode="json")
            for lb in store.labels(cr.run_id)
            if lb.case_result_id == cr.id
        ]
        return {
            "result": cr.model_dump(mode="json"),
            "trace": trace.model_dump(mode="json") if trace else None,
            "labels": labels,
        }

    @app.get("/api/traces")
    def list_traces(limit: int = 200, standalone: bool = True) -> list[dict[str, Any]]:
        return store.list_traces(limit=min(limit, 1000), standalone=standalone)

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        t = store.get_trace(trace_id)
        if t is None:
            raise HTTPException(404, "no such trace")
        return t.model_dump(mode="json")

    @app.get("/api/diff")
    def get_diff(a: str, b: str) -> dict[str, Any]:
        d = diff_runs(store, _run_or_404(store, a), _run_or_404(store, b))
        out = d.to_dict()
        out["a"]["summary"] = {k: v for k, v in d.a.summary.items() if k != "per_case"}
        out["b"]["summary"] = {k: v for k, v in d.b.summary.items() if k != "per_case"}
        return out

    @app.get("/api/label-queue")
    def get_label_queue(run: str, criterion: str | None = None, limit: int = 100) -> dict[str, Any]:
        r = _run_or_404(store, run)
        judge_cfg = r.config.get("judge") or {}
        criteria = judge_cfg.get("criteria", [])
        queue = label_queue(store, r.run_id, criterion=criterion, limit=min(limit, 500))
        return {
            "run": r.model_dump(mode="json", include={"run_id", "suite", "label", "agent"}),
            "criteria": criteria,
            "items": [
                {"result_id": cr.id, "case_id": cr.case_id, "trial": cr.trial, "criterion": name}
                for cr, name in queue
            ],
            "labelled": len(store.labels(r.run_id)),
        }

    @app.post("/api/labels")
    def post_label(body: LabelIn) -> dict[str, Any]:
        cr = store.get_case_result(body.case_result_id)
        if cr is None:
            raise HTTPException(404, "no such result")
        names = {s.name for s in cr.scores if s.scorer == "judge"} | {"overall"}
        if body.criterion not in names:
            raise HTTPException(400, f"{body.criterion!r} is not a judge criterion of this trial")
        store.set_label(Label(**body.model_dump()))
        return {"ok": True}

    @app.delete("/api/labels/{result_id}/{criterion}")
    def delete_label(result_id: str, criterion: str) -> dict[str, Any]:
        store.delete_label(result_id, criterion)
        return {"ok": True}

    @app.get("/api/calibration")
    def get_calibration(run: list[str] | None = None) -> list[dict[str, Any]]:
        run_ids = [_run_or_404(store, r).run_id for r in run] if run else None
        return [c.to_dict() for c in calibrate(store, run_ids)]

    # ---- static viewer ------------------------------------------------------------------

    if STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith(("api/", "v1/")):
                raise HTTPException(404)
            candidate = (STATIC_DIR / path).resolve()
            if path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")

    return app

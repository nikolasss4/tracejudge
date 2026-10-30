"""Export runs (with traces and labels) to a JSON bundle and import them back.

Bundles move runs between machines: CI uploads one as an artifact, ``demo-data/`` ships a few,
and ``tracejudge diff`` accepts bundle files directly.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from tracejudge.models import CaseResult, Label, Run, Trace
from tracejudge.store import Store

FORMAT = "tracejudge.bundle/v1"


def export_runs(store: Store, run_ids: list[str]) -> dict[str, Any]:
    runs, results, traces, labels = [], [], [], []
    for run_id in run_ids:
        run = store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        runs.append(run.model_dump(mode="json"))
        crs = store.case_results(run.run_id)
        results += [cr.model_dump(mode="json") for cr in crs]
        for cr in crs:
            if cr.trace_id and (t := store.get_trace(cr.trace_id)):
                traces.append(t.model_dump(mode="json"))
        labels += [lb.model_dump(mode="json") for lb in store.labels(run.run_id)]
    return {"format": FORMAT, "runs": runs, "results": results, "traces": traces, "labels": labels}


def import_bundle(store: Store, data: dict[str, Any]) -> list[str]:
    if data.get("format") != FORMAT:
        raise ValueError(f"not a {FORMAT} file")
    for t in data.get("traces", []):
        store.save_trace(Trace(**t))
    for cr in data.get("results", []):
        store.save_case_result(CaseResult(**cr))
    for lb in data.get("labels", []):
        store.set_label(Label(**lb))
    ids = []
    for r in data.get("runs", []):
        run = Run(**r)
        store.save_run(run)
        ids.append(run.run_id)
    return ids


def write_bundle(data: dict[str, Any], path: Path) -> None:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def read_bundle(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    data: dict[str, Any] = json.loads(raw)
    return data

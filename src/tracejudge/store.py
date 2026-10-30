"""SQLite storage for traces, eval runs, case results and human labels.

SQLite keeps tracejudge local-first: one file, no server, and easy to commit small sample
databases or ship them as CI artifacts. Bulky payloads (prompts, tool results) live in JSON
columns; the fields the UI filters and aggregates on are real columns.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from tracejudge.models import CaseResult, Label, Run, ScoreResult, Span, Trace

DEFAULT_DB = Path(".tracejudge/tracejudge.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    suite TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT,
    label TEXT,
    git_sha TEXT,
    git_branch TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    run_id TEXT,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    start_ns INTEGER NOT NULL,
    end_ns INTEGER,
    attributes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS traces_run ON traces(run_id);
CREATE TABLE IF NOT EXISTS spans (
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_id TEXT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_ns INTEGER NOT NULL,
    end_ns INTEGER,
    status TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    data_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (trace_id, span_id)
);
CREATE TABLE IF NOT EXISTS case_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    trial INTEGER NOT NULL,
    trace_id TEXT,
    passed INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    cost_usd REAL NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    steps INTEGER NOT NULL,
    error TEXT,
    data_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS case_results_run ON case_results(run_id, case_id, trial);
CREATE TABLE IF NOT EXISTS labels (
    case_result_id TEXT NOT NULL,
    criterion TEXT NOT NULL,
    human_pass INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    labeler TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_result_id, criterion)
);
"""


def _dump(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._memory: sqlite3.Connection | None = None
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if str(self.path) == ":memory:":
            if self._memory is None:
                self._memory = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory.row_factory = sqlite3.Row
            yield self._memory
            self._memory.commit()
            return
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- traces -------------------------------------------------------------------------

    def save_trace(self, trace: Trace) -> None:
        """Insert or replace a trace and all of its spans."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces VALUES (?,?,?,?,?,?,?)",
                (
                    trace.trace_id,
                    trace.run_id,
                    trace.name,
                    trace.source,
                    trace.start_ns,
                    trace.end_ns,
                    _dump(trace.attributes),
                ),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [self._span_row(s) for s in trace.spans],
            )

    def add_spans(self, spans: list[Span], name: str = "trace", source: str = "otlp") -> None:
        """Append spans to their traces, creating the trace rows if needed (OTLP ingestion)."""
        with self._conn() as conn:
            for s in spans:
                conn.execute(
                    "INSERT OR IGNORE INTO traces VALUES (?,?,?,?,?,?,?)",
                    (s.trace_id, None, name, source, s.start_ns, s.end_ns, "{}"),
                )
                conn.execute(
                    "UPDATE traces SET start_ns = MIN(start_ns, ?),"
                    " end_ns = MAX(COALESCE(end_ns, 0), ?) WHERE trace_id = ?",
                    (s.start_ns, s.end_ns or s.start_ns, s.trace_id),
                )
                if s.parent_id is None:
                    conn.execute(
                        "UPDATE traces SET name = ? WHERE trace_id = ?", (s.name, s.trace_id)
                    )
            conn.executemany(
                "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [self._span_row(s) for s in spans],
            )

    @staticmethod
    def _span_row(s: Span) -> tuple[Any, ...]:
        data = {
            "input": s.input,
            "output": s.output,
            "attributes": s.attributes,
            "error": s.error,
        }
        return (
            s.trace_id,
            s.span_id,
            s.parent_id,
            s.name,
            s.kind,
            s.start_ns,
            s.end_ns,
            s.status,
            s.model,
            s.input_tokens,
            s.output_tokens,
            s.cost_usd,
            _dump(data),
        )

    def get_trace(self, trace_id: str) -> Trace | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            if row is None:
                return None
            span_rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_ns", (trace_id,)
            ).fetchall()
        spans = []
        for r in span_rows:
            data = json.loads(r["data_json"])
            spans.append(
                Span(
                    trace_id=r["trace_id"],
                    span_id=r["span_id"],
                    parent_id=r["parent_id"],
                    name=r["name"],
                    kind=r["kind"],
                    start_ns=r["start_ns"],
                    end_ns=r["end_ns"],
                    status=r["status"],
                    model=r["model"],
                    input_tokens=r["input_tokens"],
                    output_tokens=r["output_tokens"],
                    cost_usd=r["cost_usd"],
                    input=data.get("input"),
                    output=data.get("output"),
                    attributes=data.get("attributes") or {},
                    error=data.get("error"),
                )
            )
        return Trace(
            trace_id=row["trace_id"],
            run_id=row["run_id"],
            name=row["name"],
            source=row["source"],
            start_ns=row["start_ns"],
            end_ns=row["end_ns"],
            attributes=json.loads(row["attributes_json"]),
            spans=spans,
        )

    def list_traces(self, limit: int = 100, standalone: bool = False) -> list[dict[str, Any]]:
        """Trace summaries, newest first. ``standalone`` keeps only traces outside eval runs."""
        where = "WHERE t.run_id IS NULL" if standalone else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT t.trace_id, t.name, t.source, t.start_ns, t.end_ns, t.run_id,
                       COUNT(s.span_id) AS spans,
                       COALESCE(SUM(s.input_tokens), 0) + COALESCE(SUM(s.output_tokens), 0)
                           AS tokens,
                       COALESCE(SUM(s.cost_usd), 0) AS cost_usd,
                       SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS errors
                FROM traces t LEFT JOIN spans s ON s.trace_id = t.trace_id
                {where}
                GROUP BY t.trace_id ORDER BY t.start_ns DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- runs ---------------------------------------------------------------------------

    def save_run(self, run: Run) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.suite,
                    run.agent,
                    run.model,
                    run.label,
                    run.git_sha,
                    run.git_branch,
                    run.created_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.status,
                    _dump(run.config),
                    _dump(run.summary),
                ),
            )

    @staticmethod
    def _run_from_row(r: sqlite3.Row) -> Run:
        return Run(
            run_id=r["run_id"],
            suite=r["suite"],
            agent=r["agent"],
            model=r["model"],
            label=r["label"],
            git_sha=r["git_sha"],
            git_branch=r["git_branch"],
            created_at=datetime.fromisoformat(r["created_at"]),
            finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
            status=r["status"],
            config=json.loads(r["config_json"]),
            summary=json.loads(r["summary_json"]),
        )

    def get_run(self, run_id: str) -> Run | None:
        """Look a run up by full id, unique prefix, or label."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE run_id LIKE ? OR label = ? ORDER BY created_at DESC",
                    (run_id + "%", run_id),
                ).fetchall()
                row = rows[0] if rows else None
        return self._run_from_row(row) if row else None

    def list_runs(
        self, suite: str | None = None, model: str | None = None, git_sha: str | None = None
    ) -> list[Run]:
        clauses, params = [], []
        for col, val in (("suite", suite), ("model", model), ("git_sha", git_sha)):
            if val:
                clauses.append(f"{col} = ?" if col != "git_sha" else "git_sha LIKE ?")
                params.append(val if col != "git_sha" else val + "%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC", params
            ).fetchall()
        return [self._run_from_row(r) for r in rows]

    def delete_run(self, run_id: str) -> None:
        with self._conn() as conn:
            trace_ids = [
                r[0]
                for r in conn.execute("SELECT trace_id FROM traces WHERE run_id = ?", (run_id,))
            ]
            conn.executemany("DELETE FROM spans WHERE trace_id = ?", [(t,) for t in trace_ids])
            conn.execute("DELETE FROM traces WHERE run_id = ?", (run_id,))
            ids = [
                r[0]
                for r in conn.execute("SELECT id FROM case_results WHERE run_id = ?", (run_id,))
            ]
            conn.executemany("DELETE FROM labels WHERE case_result_id = ?", [(i,) for i in ids])
            conn.execute("DELETE FROM case_results WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    # ---- case results -------------------------------------------------------------------

    def save_case_result(self, cr: CaseResult) -> None:
        data = {
            "input": cr.input,
            "output": cr.output,
            "scores": [s.model_dump() for s in cr.scores],
            "tags": cr.tags,
        }
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO case_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cr.id,
                    cr.run_id,
                    cr.case_id,
                    cr.trial,
                    cr.trace_id,
                    int(cr.passed),
                    cr.latency_ms,
                    cr.cost_usd,
                    cr.input_tokens,
                    cr.output_tokens,
                    cr.steps,
                    cr.error,
                    _dump(data),
                ),
            )

    @staticmethod
    def _case_from_row(r: sqlite3.Row) -> CaseResult:
        data = json.loads(r["data_json"])
        return CaseResult(
            id=r["id"],
            run_id=r["run_id"],
            case_id=r["case_id"],
            trial=r["trial"],
            trace_id=r["trace_id"],
            passed=bool(r["passed"]),
            latency_ms=r["latency_ms"],
            cost_usd=r["cost_usd"],
            input_tokens=r["input_tokens"],
            output_tokens=r["output_tokens"],
            steps=r["steps"],
            error=r["error"],
            input=data.get("input"),
            output=data.get("output"),
            scores=[ScoreResult(**s) for s in data.get("scores", [])],
            tags=data.get("tags", []),
        )

    def case_results(self, run_id: str) -> list[CaseResult]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM case_results WHERE run_id = ? ORDER BY case_id, trial", (run_id,)
            ).fetchall()
        return [self._case_from_row(r) for r in rows]

    def get_case_result(self, case_result_id: str) -> CaseResult | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM case_results WHERE id = ?", (case_result_id,)
            ).fetchone()
        return self._case_from_row(row) if row else None

    # ---- labels -------------------------------------------------------------------------

    def set_label(self, label: Label) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?)",
                (
                    label.case_result_id,
                    label.criterion,
                    int(label.human_pass),
                    label.note,
                    label.labeler,
                    label.created_at.isoformat(),
                ),
            )

    def delete_label(self, case_result_id: str, criterion: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM labels WHERE case_result_id = ? AND criterion = ?",
                (case_result_id, criterion),
            )

    def labels(self, run_id: str | None = None) -> list[Label]:
        query = "SELECT l.* FROM labels l"
        params: tuple[Any, ...] = ()
        if run_id:
            query += " JOIN case_results c ON c.id = l.case_result_id WHERE c.run_id = ?"
            params = (run_id,)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Label(
                case_result_id=r["case_result_id"],
                criterion=r["criterion"],
                human_pass=bool(r["human_pass"]),
                note=r["note"],
                labeler=r["labeler"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

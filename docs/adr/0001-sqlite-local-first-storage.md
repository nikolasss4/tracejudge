# ADR 0001: SQLite as the only store

**Status:** accepted

## Context

tracejudge stores traces (trees of spans with large prompt/response payloads), eval runs,
per-trial results and human labels. It has to run on a laptop, inside a CI job and in one
Docker container, and runs must move between them (CI artifact → laptop).

Options considered: SQLite, DuckDB, Postgres, plain JSON files.

## Decision

One SQLite file. Columns the UI filters or aggregates on (run, suite, model, SHA, pass, cost,
latency, tokens, span kind and timing) are real columns; payloads (inputs, outputs, attributes,
scores) are JSON text. Runs move between databases as gzipped JSON bundles
(`tracejudge export` / `import`), not as database files.

## Consequences

- No server to run; `pip install` and go. WAL mode lets the viewer read while an eval writes.
- Aggregations stay small (hundreds of runs, tens of thousands of trials) and are done in
  Python. Past that, DuckDB over the same schema would be the next step; the store is one class.
- Bundles are diffable, reviewable and survive schema changes better than raw `.db` files.

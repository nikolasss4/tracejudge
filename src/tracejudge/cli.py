"""Command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from tracejudge import __version__
from tracejudge.models import CaseResult, Run
from tracejudge.store import DEFAULT_DB, Store

app = typer.Typer(help="Evals and trace viewer for tool-calling agents.", no_args_is_help=True)
console = Console()

DbOpt = Annotated[Path, typer.Option("--db", envvar="TRACEJUDGE_DB", help="SQLite database.")]


@app.callback()
def main() -> None:
    """tracejudge: run evals, diff runs and browse traces."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def print_summary(run: Run) -> None:
    s = run.summary
    lo, hi = s.get("pass_rate_ci95", [0, 0])
    table = Table(title=f"{run.suite} · {run.run_id}", show_header=False, title_justify="left")
    table.add_column(style="dim")
    table.add_column()
    table.add_row("agent", run.agent + (f"  [dim]({run.model})[/dim]" if run.model else ""))
    table.add_row("cases × repeats", f"{s['cases']} × {s['repeats']} = {s['trials']} trials")
    table.add_row(
        "pass rate", f"[bold]{_pct(s['pass_rate'])}[/bold]  (95% CI {_pct(lo)}–{_pct(hi)})"
    )
    table.add_row(
        f"pass@{s['k']} / pass^{s['k']}", f"{_pct(s['pass_at_k'])} / {_pct(s['pass_hat_k'])}"
    )
    table.add_row("flaky cases", f"{len(s['flaky_cases'])} ({_pct(s['flaky_rate'])})")
    table.add_row("cost", f"${s['cost_usd']:.4f} total, ${s['cost_per_trial_usd']:.5f}/trial")
    table.add_row(
        "latency p50 / p95", f"{s['latency_p50_ms']:.0f} ms / {s['latency_p95_ms']:.0f} ms"
    )
    table.add_row("mean LLM steps", f"{s['mean_steps']:.1f}")
    if s.get("skipped_scores"):
        table.add_row(
            "skipped scores", f"[yellow]{s['skipped_scores']}[/yellow] (judge had no fixture/key)"
        )
    if s.get("judge_cost_usd"):
        table.add_row("judge cost", f"${s['judge_cost_usd']:.4f}")
    if s.get("top_failures"):
        table.add_row(
            "top failures", "\n".join(f"{name} ×{n}" for name, n in s["top_failures"][:5])
        )
    console.print(table)


@app.command("eval")
def eval_cmd(
    suite_path: Annotated[Path, typer.Argument(help="Suite YAML file.")],
    agent: Annotated[
        str | None, typer.Option(help="Agent as module:function or file.py:function.")
    ] = None,
    repeats: Annotated[int | None, typer.Option("--repeats", "-n", help="Trials per case.")] = None,
    concurrency: Annotated[int, typer.Option("--concurrency", "-j")] = 4,
    label: Annotated[str | None, typer.Option(help="Name this run, e.g. 'baseline'.")] = None,
    case: Annotated[
        list[str] | None, typer.Option("--case", "-k", help="Only cases matching id glob or tag.")
    ] = None,
    no_judge: Annotated[bool, typer.Option("--no-judge", help="Skip LLM-judge criteria.")] = False,
    judge_model: Annotated[str | None, typer.Option(help="Override the judge model.")] = None,
    record: Annotated[
        bool, typer.Option(help="Call the judge API and record its answers as fixtures.")
    ] = False,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write results JSON.")] = None,
    fail_under: Annotated[
        float | None, typer.Option(help="Exit 1 if the pass rate is below this (0-1).")
    ] = None,
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Run a suite through an agent, score every trial and store the traces."""
    from tracejudge.runner import RunOptions, run_suite
    from tracejudge.suite import load_suite

    suite = load_suite(suite_path)
    agent_ref = agent or suite.agent
    if not agent_ref:
        raise typer.BadParameter("no --agent given and the suite has no `agent:`")
    judge = None
    judge_info: dict[str, object] = {}
    if suite.judge and suite.judge.criteria and not no_judge:
        from tracejudge.judge import make_judge

        judge, judge_info = make_judge(
            suite, model=judge_model, record=record, base_dir=suite_path.parent
        )
    store = Store(db)
    n = repeats if repeats is not None else suite.repeats
    total = len(suite.select(case)) * n
    done = {"n": 0}

    def progress(r: CaseResult) -> None:
        done["n"] += 1
        mark = "[green]✓[/green]" if r.passed else "[red]✗[/red]"
        console.print(f"  {mark} {r.case_id} #{r.trial}  [dim]{done['n']}/{total}[/dim]")

    run = run_suite(
        suite,
        store,
        RunOptions(
            agent=agent_ref,
            repeats=n,
            concurrency=concurrency,
            label=label,
            patterns=case,
            judge=judge,
            on_result=progress,
            config={"judge": judge_info} if judge_info else {},
        ),
    )
    print_summary(run)
    if json_out:
        results = [r.model_dump(mode="json") for r in store.case_results(run.run_id)]
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps({"run": run.model_dump(mode="json"), "results": results}, indent=2)
        )
    console.print(f"[dim]stored in {db} · view with `tracejudge serve`[/dim]")
    if fail_under is not None and run.summary["pass_rate"] < fail_under:
        console.print(f"[red]pass rate below {fail_under:.0%}[/red]")
        raise typer.Exit(1)


@app.command()
def runs(
    suite: Annotated[str | None, typer.Option()] = None,
    model: Annotated[str | None, typer.Option()] = None,
    sha: Annotated[str | None, typer.Option(help="Git SHA prefix.")] = None,
    db: DbOpt = DEFAULT_DB,
) -> None:
    """List stored runs."""
    table = Table("run", "label", "suite", "agent", "model", "sha", "pass", "pass^k", "cost")
    for r in Store(db).list_runs(suite=suite, model=model, git_sha=sha):
        s = r.summary
        table.add_row(
            r.run_id,
            r.label or "",
            r.suite,
            r.agent,
            r.model or "",
            (r.git_sha or "")[:7],
            _pct(s.get("pass_rate", 0)),
            _pct(s.get("pass_hat_k", 0)),
            f"${s.get('cost_usd', 0):.4f}",
        )
    console.print(table)


@app.command()
def show(run_id: str, db: DbOpt = DEFAULT_DB) -> None:
    """Show a run's summary and failing cases."""
    store = Store(db)
    run = store.get_run(run_id)
    if run is None:
        raise typer.BadParameter(f"no run {run_id!r}")
    print_summary(run)
    failing = [r for r in store.case_results(run.run_id) if not r.passed]
    if failing:
        table = Table("case", "trial", "why")
        for r in failing:
            why = "; ".join(
                f"{s.scorer}:{s.name}: {s.reason}" for s in r.scores if s.passed is False
            )
            table.add_row(r.case_id, str(r.trial), why[:200])
        console.print(table)


@app.command()
def calibrate(
    run: Annotated[
        list[str] | None, typer.Option("--run", "-r", help="Limit to these runs.")
    ] = None,
    show_disagreements: Annotated[bool, typer.Option("--disagreements", "-d")] = False,
    json_out: Annotated[Path | None, typer.Option("--json")] = None,
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Judge-vs-human agreement and Cohen's kappa per criterion."""
    from tracejudge.calibration import calibrate as run_calibration
    from tracejudge.calibration import interpret_kappa

    store = Store(db)
    run_ids = None
    if run:
        found = [store.get_run(r) for r in run]
        run_ids = [r.run_id for r in found if r]
    cals = run_calibration(store, run_ids)
    if not cals:
        console.print(
            "No labelled trials yet. Label some with `tracejudge label RUN` or in the UI."
        )
        return
    table = Table("criterion", "n", "agreement", "kappa", "", "J+H-", "J-H+")
    for c in cals:
        k = c.kappa
        table.add_row(
            c.criterion,
            str(c.n),
            _pct(c.agreement or 0),
            f"{k:.2f}" if k is not None else "–",
            interpret_kappa(k),
            str(c.judge_pass_human_fail),
            str(c.judge_fail_human_pass),
        )
    console.print(table)
    console.print("[dim]J+H- judge passed, human failed (too lenient) · J-H+ too strict[/dim]")
    if show_disagreements:
        for c in cals:
            for d in c.disagreements:
                judge_v = "PASS" if d.judge_pass else "FAIL"
                human_v = "PASS" if d.human_pass else "FAIL"
                console.print(
                    f"[bold]{c.criterion}[/bold] {d.case_id}#{d.trial}: judge {judge_v}, "
                    f"human {human_v}\n  judge: {d.judge_reason}\n  human: {d.human_note or '-'}"
                )
    if json_out:
        json_out.write_text(json.dumps([c.to_dict() for c in cals], indent=2))


@app.command()
def label(
    run_id: str,
    criterion: Annotated[str | None, typer.Option("--criterion", "-c")] = None,
    limit: Annotated[int, typer.Option(help="How many trials to queue.")] = 60,
    labeler: Annotated[str, typer.Option(envvar="USER")] = "",
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Label judge criteria pass/fail in the terminal (blind to the judge's verdict)."""
    from tracejudge.calibration import label_queue
    from tracejudge.judge import render_transcript
    from tracejudge.models import Label
    from tracejudge.scorers.deterministic import output_text

    store = Store(db)
    run = store.get_run(run_id)
    if run is None:
        raise typer.BadParameter(f"no run {run_id!r}")
    judge_cfg = run.config.get("judge") or {}
    criteria = {c["name"]: c.get("description", "") for c in judge_cfg.get("criteria", [])}
    queue = label_queue(store, run.run_id, criterion=criterion, limit=limit)
    console.print(
        f"{len(queue)} to label. Keys: [bold]p[/bold]ass [bold]f[/bold]ail "
        "[bold]s[/bold]kip [bold]q[/bold]uit; add a note after a space, e.g. 'f wrong id'."
    )
    for i, (cr, name) in enumerate(queue, 1):
        trace = store.get_trace(cr.trace_id) if cr.trace_id else None
        console.rule(f"{i}/{len(queue)} · {cr.case_id}#{cr.trial} · criterion [bold]{name}[/bold]")
        if criteria.get(name):
            console.print(f"[dim]{criteria[name]}[/dim]")
        console.print(f"[cyan]input[/cyan] {json.dumps(cr.input)}")
        if trace:
            console.print(render_transcript(trace), markup=False)
        console.print(f"[cyan]final answer[/cyan] {output_text(cr.output)}")
        answer = typer.prompt("p/f/s/q", default="s").strip()
        key, _, note = answer.partition(" ")
        if key == "q":
            break
        if key in ("p", "f"):
            store.set_label(
                Label(
                    case_result_id=cr.id,
                    criterion=name,
                    human_pass=key == "p",
                    note=note,
                    labeler=labeler,
                )
            )


def _resolve_run(store: Store, ref: str) -> Run:
    """A run id, id prefix, label, or a bundle file (imported into the store)."""
    path = Path(ref)
    if path.suffix in (".json", ".gz") and path.exists():
        from tracejudge.bundle import import_bundle, read_bundle

        ids = import_bundle(store, read_bundle(path))
        if len(ids) != 1:
            raise typer.BadParameter(f"{ref} holds {len(ids)} runs; export one run per file")
        ref = ids[0]
    run = store.get_run(ref)
    if run is None:
        raise typer.BadParameter(f"no run {ref!r}")
    return run


@app.command()
def diff(
    baseline: Annotated[str, typer.Argument(help="Run id, label, or bundle file.")],
    candidate: Annotated[str, typer.Argument(help="Run id, label, or bundle file.")],
    markdown: Annotated[Path | None, typer.Option(help="Write a markdown report here.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json")] = None,
    max_regressions: Annotated[
        int | None, typer.Option(help="Fail if more cases regress than this.")
    ] = None,
    max_pass_rate_drop: Annotated[
        float | None, typer.Option(help="Fail if pass rate drops by more than this (0-1).")
    ] = None,
    max_cost_increase: Annotated[
        float | None, typer.Option(help="Fail if cost per trial rises by more than this (0.2=20%).")
    ] = None,
    min_pass_rate: Annotated[float | None, typer.Option()] = None,
    viewer_url: Annotated[str | None, typer.Option(help="Link to include in the report.")] = None,
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Compare two runs: per-case flips, cost and latency changes, and a noise check."""
    from tracejudge.diff import Thresholds, check_thresholds, diff_runs
    from tracejudge.report import render_markdown

    store = Store(db)
    a, b = _resolve_run(store, baseline), _resolve_run(store, candidate)
    d = diff_runs(store, a, b)
    gates = Thresholds(
        max_regressions=max_regressions,
        max_pass_rate_drop=max_pass_rate_drop,
        max_cost_increase=max_cost_increase,
        min_pass_rate=min_pass_rate,
    )
    problems = check_thresholds(d, gates)

    console.print(
        f"[bold]{a.label or a.run_id}[/bold] → [bold]{b.label or b.run_id}[/bold]   "
        f"pass {_pct(d.pass_rate_a)} → {_pct(d.pass_rate_b)} "
        f"({d.pass_rate_delta * 100:+.1f} pts, p={d.p_value:.3g})   "
        f"cost/trial ${d.cost_a:.4f} → ${d.cost_b:.4f}   "
        f"p50 {d.latency_p50_a:.0f} → {d.latency_p50_b:.0f} ms"
    )
    changed = [c for c in d.cases if c.status != "unchanged"]
    if changed:
        table = Table("case", "status", "baseline", "candidate", "split at", "new failures")
        colors = {"regressed": "red", "degraded": "yellow", "fixed": "green", "improved": "green"}
        for c in sorted(changed, key=lambda c: (c.status != "regressed", c.case_id)):
            split = ""
            if c.diverged_at is not None:
                i = c.diverged_at
                left = c.trajectory_a[i] if i < len(c.trajectory_a) else "(end)"
                right = c.trajectory_b[i] if i < len(c.trajectory_b) else "(end)"
                split = f"{i + 1}: {left} → {right}"
            color = colors.get(c.status, "white")
            table.add_row(
                c.case_id,
                f"[{color}]{c.status}[/{color}]",
                f"{c.a_passed}/{c.a_trials}",
                f"{c.b_passed}/{c.b_trials}",
                split,
                ", ".join(c.new_failures)[:80],
            )
        console.print(table)
    else:
        console.print("No case changed outcome.")
    for note in d.notes:
        console.print(f"[dim]· {note}[/dim]")
    if markdown:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_markdown(d, problems, viewer_url))
    if json_out:
        json_out.write_text(
            json.dumps({**d.to_dict(), "gate_failures": problems}, indent=2, default=str)
        )
    if problems:
        for p in problems:
            console.print(f"[red]✗ {p}[/red]")
        raise typer.Exit(1)


@app.command("export")
def export_cmd(
    run_ids: Annotated[list[str], typer.Argument(help="Runs to export.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Bundle file (.json or .json.gz).")],
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Export runs with their traces and labels to a bundle file."""
    from tracejudge.bundle import export_runs, write_bundle

    store = Store(db)
    ids = [_resolve_run(store, r).run_id for r in run_ids]
    write_bundle(export_runs(store, ids), out)
    console.print(f"wrote {len(ids)} run(s) to {out}")


@app.command("import")
def import_cmd(
    paths: Annotated[list[Path], typer.Argument(help="Bundle files.")],
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Import run bundles into the database."""
    from tracejudge.bundle import import_bundle, read_bundle

    store = Store(db)
    for p in paths:
        ids = import_bundle(store, read_bundle(p))
        console.print(f"{p}: imported {', '.join(ids)}")


@app.command()
def serve(
    host: Annotated[
        str, typer.Option(help="Bind address. Use 0.0.0.0 only on trusted networks.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 7600,
    db: DbOpt = DEFAULT_DB,
) -> None:
    """Start the trace viewer, the JSON API and the OTLP endpoint (POST /v1/traces)."""
    import uvicorn

    from tracejudge.server import STATIC_DIR, create_app

    if not STATIC_DIR.exists():
        console.print("[yellow]UI not built; API only. Run `make ui` to build the viewer.[/yellow]")
    console.print(f"tracejudge on http://{host}:{port}  ·  OTLP: http://{host}:{port}/v1/traces")
    uvicorn.run(create_app(Store(db)), host=host, port=port, log_level="warning")

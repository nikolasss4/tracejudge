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

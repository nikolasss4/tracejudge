"""The eval runner: run every case N times through an agent, capture traces, score them."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tracejudge.models import CaseResult, Run, ScoreResult, Trace
from tracejudge.scorers import ScoreContext, build_scorers, run_scorers
from tracejudge.sdk import capture, span, to_jsonable
from tracejudge.stats import pass_at_k, pass_hat_k, percentile, wilson_interval
from tracejudge.store import Store
from tracejudge.suite import Case, Suite

AgentFn = Callable[[Any], Any]
JudgeFn = Callable[[Case, ScoreContext], list[ScoreResult]]


def load_agent(ref: str) -> AgentFn:
    """Resolve ``package.module:function`` or ``path/to/file.py:function``."""
    if ":" not in ref:
        raise ValueError(f"agent reference {ref!r} must look like module:function")
    target, _, attr = ref.rpartition(":")
    if target.endswith(".py") or "/" in target:
        path = Path(target).resolve()
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"cannot import {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)
    else:
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())
        module = importlib.import_module(target)
    fn = module
    for part in attr.split("."):
        fn = getattr(fn, part)
    if not callable(fn):
        raise ValueError(f"{ref} is not callable")
    return fn


def git_info() -> tuple[str | None, str | None]:
    sha = os.environ.get("GITHUB_SHA")
    branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    try:
        sha = (
            sha
            or subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        branch = (
            branch
            or subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        pass
    return sha or None, branch or None


@dataclass
class RunOptions:
    agent: str
    repeats: int = 3
    concurrency: int = 4
    label: str | None = None
    patterns: list[str] | None = None
    judge: JudgeFn | None = None
    on_result: Callable[[CaseResult], None] | None = None
    config: dict[str, Any] = field(default_factory=dict)


def _call_agent(fn: AgentFn, inp: Any) -> Any:
    result = fn(inp)
    if inspect.isawaitable(result):
        return asyncio.run(_await(result))
    return result


async def _await(aw: Any) -> Any:
    return await aw


def run_case(
    suite: Suite, case: Case, trial: int, fn: AgentFn, run_id: str, judge: JudgeFn | None
) -> tuple[CaseResult, Trace]:
    output: Any = None
    error: str | None = None
    with (
        capture(name=case.id, case_id=case.id, trial=trial) as t,
        span(case.id, kind="agent", input=case.input) as root,
    ):
        try:
            output = _call_agent(fn, case.input)
            root.set_output(output)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            root.set_error(error)
    t.run_id = run_id
    ctx = ScoreContext(output=output, trace=t, error=error, input=case.input, case_id=case.id)
    scores = run_scorers(build_scorers(suite.case_expect(case)), ctx)
    if judge is not None and error is None:
        judge_start = time.perf_counter()
        scores.extend(judge(case, ctx))
        ctx.metadata["judge_ms"] = (time.perf_counter() - judge_start) * 1000
    decided = [s.passed for s in scores if s.passed is not None]
    result = CaseResult(
        run_id=run_id,
        case_id=case.id,
        trial=trial,
        trace_id=t.trace_id,
        input=case.input,
        output=to_jsonable(output),
        error=error,
        passed=bool(decided) and all(decided),
        scores=scores,
        latency_ms=t.duration_ms,
        cost_usd=t.cost_usd,
        input_tokens=t.input_tokens,
        output_tokens=t.output_tokens,
        steps=t.llm_calls,
        tags=case.tags,
    )
    return result, t


def summarize(results: list[CaseResult], repeats: int) -> dict[str, Any]:
    by_case: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_case[r.case_id].append(r)
    n_trials = len(results)
    n_pass = sum(r.passed for r in results)
    k = max(1, repeats)
    per_case = {}
    for case_id, rs in by_case.items():
        c = sum(r.passed for r in rs)
        per_case[case_id] = {"passed": c, "trials": len(rs)}
    flaky = sorted(cid for cid, v in per_case.items() if 0 < v["passed"] < v["trials"])
    latencies = [r.latency_ms for r in results]
    failures: Counter[str] = Counter()
    for r in results:
        for s in r.scores:
            if s.passed is False:
                failures[f"{s.scorer}:{s.name}"] += 1
    lo, hi = wilson_interval(n_pass, n_trials)
    cases = len(per_case) or 1
    return {
        "cases": len(per_case),
        "trials": n_trials,
        "repeats": repeats,
        "passed_trials": n_pass,
        "pass_rate": n_pass / n_trials if n_trials else 0.0,
        "pass_rate_ci95": [lo, hi],
        "pass_at_k": sum(pass_at_k(v["trials"], v["passed"], k) for v in per_case.values()) / cases,
        "pass_hat_k": sum(pass_hat_k(v["trials"], v["passed"], k) for v in per_case.values())
        / cases,
        "k": k,
        "flaky_cases": flaky,
        "flaky_rate": len(flaky) / cases,
        "cost_usd": sum(r.cost_usd for r in results),
        "cost_per_trial_usd": sum(r.cost_usd for r in results) / n_trials if n_trials else 0,
        "tokens": sum(r.input_tokens + r.output_tokens for r in results),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "mean_steps": sum(r.steps for r in results) / n_trials if n_trials else 0,
        "errors": sum(1 for r in results if r.error),
        "top_failures": failures.most_common(10),
        "per_case": per_case,
    }


def run_suite(suite: Suite, store: Store, opts: RunOptions) -> Run:
    fn = load_agent(opts.agent)
    sha, branch = git_info()
    run = Run(
        suite=suite.name,
        agent=opts.agent,
        label=opts.label,
        git_sha=sha,
        git_branch=branch,
        config={"repeats": opts.repeats, "suite_path": suite.path, **opts.config},
    )
    store.save_run(run)
    cases = suite.select(opts.patterns)
    if not cases:
        raise ValueError(f"no cases match {opts.patterns}")
    jobs = [(c, trial) for c in cases for trial in range(opts.repeats)]
    results: list[CaseResult] = []
    models: Counter[str] = Counter()

    def job(item: tuple[Case, int]) -> tuple[CaseResult, Trace]:
        return run_case(suite, item[0], item[1], fn, run.run_id, opts.judge)

    try:
        with ThreadPoolExecutor(max_workers=max(1, opts.concurrency)) as pool:
            for result, t in pool.map(job, jobs):
                store.save_trace(t)
                store.save_case_result(result)
                results.append(result)
                models.update(s.model for s in t.spans if s.kind == "llm" and s.model)
                if opts.on_result:
                    opts.on_result(result)
    except BaseException:
        run.status = "failed"
        run.finished_at = datetime.now(UTC)
        run.summary = summarize(results, opts.repeats)
        store.save_run(run)
        raise
    run.summary = summarize(results, opts.repeats)
    run.summary["models"] = dict(models)
    run.model = models.most_common(1)[0][0] if models else None
    run.status = "finished"
    run.finished_at = datetime.now(UTC)
    store.save_run(run)
    return run

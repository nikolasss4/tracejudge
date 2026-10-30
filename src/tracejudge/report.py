"""Markdown report of a run diff, used for PR comments and job summaries."""

from __future__ import annotations

from tracejudge.diff import CaseDiff, RunDiff

MARKER = "<!-- tracejudge-report -->"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _delta_pts(x: float) -> str:
    arrow = "🔻" if x < 0 else ("🔺" if x > 0 else "")
    return f"{x * 100:+.1f} pts {arrow}".strip()


def _rel(a: float, b: float) -> str:
    if not a:
        return "n/a"
    return f"{(b - a) / a * 100:+.0f}%"


def _run_name(d: RunDiff, which: str) -> str:
    r = d.a if which == "a" else d.b
    name = r.label or r.run_id
    if r.git_sha:
        name += f" @ `{r.git_sha[:7]}`"
    return name


def _trials(c: CaseDiff, side: str) -> str:
    if side == "a":
        return f"{c.a_passed}/{c.a_trials}"
    return f"{c.b_passed}/{c.b_trials}"


def _divergence(c: CaseDiff) -> str:
    if c.diverged_at is None:
        return ""
    i = c.diverged_at
    a = c.trajectory_a[i] if i < len(c.trajectory_a) else "(end)"
    b = c.trajectory_b[i] if i < len(c.trajectory_b) else "(end)"
    return f"step {i + 1}: `{a}` → `{b}`"


def render_markdown(
    d: RunDiff, problems: list[str] | None = None, details_url: str | None = None
) -> str:
    problems = problems or []
    status = "❌ **Regression gate failed**" if problems else "✅ **No regressions over threshold**"
    lines = [
        MARKER,
        f"## tracejudge · `{d.b.suite}`",
        "",
        status,
        "",
        f"Baseline **{_run_name(d, 'a')}** → candidate **{_run_name(d, 'b')}**",
        "",
        "| | baseline | candidate | change |",
        "|:--|--:|--:|--:|",
        f"| pass rate (trials) | {_pct(d.pass_rate_a)} | {_pct(d.pass_rate_b)} | "
        f"{_delta_pts(d.pass_rate_delta)} |",
    ]
    sa, sb = d.a.summary, d.b.summary
    if "pass_hat_k" in sa and "pass_hat_k" in sb:
        k = sb.get("k", 3)
        lines.append(
            f"| pass^{k} (all trials pass) | {_pct(sa['pass_hat_k'])} | {_pct(sb['pass_hat_k'])} | "
            f"{_delta_pts(sb['pass_hat_k'] - sa['pass_hat_k'])} |"
        )
    lines += [
        f"| cost / trial | ${d.cost_a:.4f} | ${d.cost_b:.4f} | {_rel(d.cost_a, d.cost_b)} |",
        f"| latency p50 | {d.latency_p50_a:.0f} ms | {d.latency_p50_b:.0f} ms | "
        f"{_rel(d.latency_p50_a, d.latency_p50_b)} |",
        f"| latency p95 | {d.latency_p95_a:.0f} ms | {d.latency_p95_b:.0f} ms | "
        f"{_rel(d.latency_p95_a, d.latency_p95_b)} |",
        "",
    ]
    if problems:
        lines += ["**Gate:**", *[f"- {p}" for p in problems], ""]

    regressed = d.by_status("regressed")
    if regressed:
        lines += [
            f"### Newly failing ({len(regressed)})",
            "",
            "| case | baseline | candidate | trajectory split | why it fails |",
            "|:--|--:|--:|:--|:--|",
        ]
        shown = 10

        def row(c: CaseDiff) -> str:
            why = "<br>".join(r.replace("|", "\\|")[:160] for r in c.reasons[:2])
            return (
                f"| `{c.case_id}` | {_trials(c, 'a')} | {_trials(c, 'b')} | {_divergence(c)} | "
                f"{why} |"
            )

        lines += [row(c) for c in regressed[:shown]]
        lines.append("")
        if len(regressed) > shown:
            lines += [
                f"<details><summary>{len(regressed) - shown} more</summary>",
                "",
                "| case | baseline | candidate | trajectory split | why it fails |",
                "|:--|--:|--:|:--|:--|",
                *[row(c) for c in regressed[shown:]],
                "",
                "</details>",
                "",
            ]
    for status, title in (("fixed", "Fixed"), ("degraded", "Less reliable")):
        items = d.by_status(status)  # type: ignore[arg-type]
        if items:
            cases = ", ".join(
                f"`{c.case_id}` ({_trials(c, 'a')}→{_trials(c, 'b')})" for c in items[:20]
            )
            lines += [f"**{title} ({len(items)}):** {cases}", ""]
    if d.notes:
        lines += ["<details><summary>Is this noise?</summary>", ""]
        lines += [f"- {n}" for n in d.notes]
        lines += ["", "</details>", ""]
    if details_url:
        lines.append(
            f"[Workflow run]({details_url}) · to browse the traces, download the `tracejudge-runs` "
            "artifact, then `tracejudge import runs.json.gz && tracejudge serve`."
        )
    return "\n".join(lines).rstrip() + "\n"

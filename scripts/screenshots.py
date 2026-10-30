"""Capture the README screenshots from a running `make demo` (http://127.0.0.1:7600).

    uv run python scripts/screenshots.py [--base http://127.0.0.1:7600] [--report report.md]

With --report, also renders a diff report through GitHub's markdown API (needs `gh` logged in)
to show what the PR comment looks like.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parents[1] / "docs" / "img"


def get(base: str, path: str) -> object:
    with urllib.request.urlopen(base + path) as r:
        return json.load(r)


def shot(
    page: Page, base: str, path: str, name: str, full: bool = False, clip_h: int | None = None
) -> None:
    page.goto(base + path)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    kwargs: dict = {"path": str(OUT / f"{name}.png"), "full_page": full}
    if clip_h:
        kwargs["clip"] = {"x": 0, "y": 0, "width": page.viewport_size["width"], "height": clip_h}
        kwargs["full_page"] = True
    page.screenshot(**kwargs)
    print("wrote", name)


def render_report(page: Page, report: Path) -> None:
    html = subprocess.run(
        ["gh", "api", "markdown", "-f", f"text={report.read_text()}", "-f", "mode=gfm"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    page.emulate_media(color_scheme="dark")
    css = "https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.8.1/github-markdown.min.css"
    page.set_content(
        f"""<html><head><link rel="stylesheet" href="{css}">
        <style>body{{background:#0d1117;margin:0;padding:24px}}
        .c{{max-width:1120px;margin:auto;border:1px solid #30363d;border-radius:6px}}
        .h{{background:#161b22;color:#8b949e;padding:8px 16px;border-bottom:1px solid #30363d;
        font:14px -apple-system,sans-serif}} .markdown-body{{padding:16px}}
        .markdown-body td,.markdown-body th{{color:#e6edf3;opacity:1}}</style></head>
        <body><div class="c"><div class="h">
        <b style="color:#e6edf3">github-actions</b> bot commented</div>
        <div class="markdown-body">{html}</div></div></body></html>"""
    )
    page.wait_for_timeout(800)
    page.locator(".c").screenshot(path=str(OUT / "pr-comment.png"))
    print("wrote pr-comment")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7600")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    base = args.base
    OUT.mkdir(parents=True, exist_ok=True)
    runs = {r["label"]: r["run_id"] for r in get(base, "/api/runs")}  # type: ignore[union-attr]
    detail = get(base, f"/api/runs/{runs['v2']}")
    case = next(c for c in detail["cases"] if c["case_id"] == "refund-high-value-bike")  # type: ignore[index]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        shot(page, base, "/", "runs", clip_h=560)
        shot(
            page,
            base,
            f"/compare?a={runs['v1']}&b={runs['v2']}&case=refund-eligible-shoes",
            "diff",
            full=True,
        )
        shot(page, base, f"/results/{case['results'][0]['id']}", "trace")
        shot(page, base, f"/label?run={runs['v2']}&criterion=overall", "label")
        shot(page, base, "/dashboard", "dashboard")
        if args.report:
            render_report(page, args.report)
        browser.close()


if __name__ == "__main__":
    main()

"""Render a scan as an HTML page (on screen or downloaded) or a PDF."""

from __future__ import annotations

from datetime import datetime
from itertools import groupby
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from .aggregator import Summary, summarize
from .criteria import PRINCIPLES
from .models import ScanResult

env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["path"] = lambda url: (
    (urlsplit(url).path or "/") + (f"?{urlsplit(url).query}" if urlsplit(url).query else "")
)
env.filters["host"] = lambda url: urlsplit(url).netloc
env.filters["date"] = lambda iso: datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M UTC") if iso else ""


def render(template: str, **context) -> str:
    return env.get_template(template).render(**context)


def render_report(scan: ScanResult, standalone: bool = False, summary: Summary | None = None) -> str:
    summary = summary or summarize(scan)
    by_principle = [(name, list(rows)) for name, rows in groupby(summary.criteria, key=lambda r: r.criterion.principle)]
    principle_counts = {
        name: {s: sum(1 for r in rows if r.status == s) for s in ("fail", "review", "pass", "manual", "na")}
        for name, rows in by_principle
    }
    issue_criteria = sorted(
        (r for r in summary.criteria if r.groups), key=lambda r: (r.status != "fail", -r.fails, -r.reviews)
    )
    return render(
        "report.html",
        scan=scan,
        s=summary,
        by_principle=by_principle,
        issue_criteria=issue_criteria,
        principle_counts=principle_counts,
        principles=list(PRINCIPLES.values()),
        standalone=standalone,
    )


async def render_pdf(html: str) -> bytes:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        await page.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
        await page.emulate_media(media="print")
        pdf = await page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
        )
        await browser.close()
    return pdf

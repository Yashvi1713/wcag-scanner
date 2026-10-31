"""Layer 1: run the axe-core rules engine in a page and map its results to WCAG criteria."""

from __future__ import annotations

import re
from pathlib import Path

from playwright.async_api import Page

from .models import Finding, FindingStatus

AXE_SOURCE = (Path(__file__).parent / "static" / "axe.min.js").read_text()

LEVEL_TAGS = {
    "A": ["wcag2a", "wcag21a", "wcag22a"],
    "AA": ["wcag2a", "wcag21a", "wcag22a", "wcag2aa", "wcag21aa", "wcag22aa"],
    "AAA": ["wcag2a", "wcag21a", "wcag22a", "wcag2aa", "wcag21aa", "wcag22aa", "wcag2aaa", "wcag21aaa", "wcag22aaa"],
}

_SC_TAG = re.compile(r"^wcag(\d)(\d)(\d+)$")  # "wcag1410" -> 1.4.10

# Trim results inside the page so huge DOMs don't flood the Python side.
_RUN_JS = """
async (tags) => {
  const r = await axe.run(document, {
    runOnly: { type: 'tag', values: tags },
    resultTypes: ['violations', 'incomplete'],
  });
  const slim = (rules, withNodes) => rules.map(rule => ({
    id: rule.id, impact: rule.impact, help: rule.help, description: rule.description,
    helpUrl: rule.helpUrl, tags: rule.tags,
    nodes: withNodes ? rule.nodes.slice(0, 25).map(n => ({
      target: n.target, html: (n.html || '').slice(0, 300),
      summary: (n.failureSummary || '').slice(0, 400),
    })) : [],
  }));
  return {
    version: r.testEngine.version,
    violations: slim(r.violations, true),
    incomplete: slim(r.incomplete, true),
    passes: slim(r.passes, false),
  };
}
"""


def sc_from_tags(tags: list[str]) -> list[str]:
    out = []
    for tag in tags:
        m = _SC_TAG.match(tag)
        if m:
            out.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return out


async def inject(page: Page) -> None:
    if not await page.evaluate("() => typeof window.axe !== 'undefined'"):
        await page.add_script_tag(content=AXE_SOURCE)


async def coverage(page: Page, level: str) -> list[str]:
    """Criteria that at least one axe rule tests at this conformance level."""
    await inject(page)
    rules = await page.evaluate("(tags) => axe.getRules(tags).map(r => r.tags)", LEVEL_TAGS[level])
    return sorted({sc for tags in rules for sc in sc_from_tags(tags)})


async def run_axe(page: Page, level: str, viewport: str) -> tuple[list[Finding], set[str], str]:
    """Return (findings, criteria checked, axe version)."""
    await inject(page)
    result = await page.evaluate(_RUN_JS, LEVEL_TAGS[level])
    findings: list[Finding] = []
    checked: set[str] = set()

    outcomes: tuple[tuple[str, FindingStatus], ...] = (("violations", "fail"), ("incomplete", "review"))
    for kind, status in outcomes:
        for rule in result[kind]:
            scs = sc_from_tags(rule["tags"])
            checked.update(scs)
            for node in rule["nodes"]:
                target = node["target"]
                # Nested arrays mean the element is inside an iframe or shadow DOM.
                selector = " >>> ".join(t if isinstance(t, str) else " ".join(t) for t in target)
                for sc in scs:
                    findings.append(
                        Finding(
                            criterion=sc,
                            status=status,
                            source="axe",
                            rule=rule["id"],
                            message=rule["help"],
                            page=page.url,
                            selector=selector,
                            html=node["html"],
                            impact=rule["impact"],
                            fix=_first_line(node["summary"])
                            if status == "fail"
                            else "axe-core could not decide automatically. " + _first_line(node["summary"]),
                            help_url=rule["helpUrl"],
                            viewport=viewport,
                        )
                    )
    for rule in result["passes"]:
        checked.update(sc_from_tags(rule["tags"]))
    return findings, checked, result["version"]


def _first_line(summary: str) -> str:
    lines = [ln.strip() for ln in summary.splitlines() if ln.strip()]
    # axe summaries look like "Fix any of the following:\n  Element has no alt attribute"
    return " ".join(lines[:3])

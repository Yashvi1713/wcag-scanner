"""The contract between the API and the React app.

frontend/src/test/report.json is a report produced by the real server code. The React tests render
it, so if the API's shape changes without the fixture (and the TypeScript types) changing too, this
test fails. To regenerate after an intended change:  UPDATE_FIXTURES=1 pytest tests/test_contract.py
"""

import json
import os

from tests.conftest import ROOT
from wcag_scanner.api import build_report
from wcag_scanner.models import Finding, PageResult, PageSignals, ScanResult

FIXTURE = ROOT / "frontend" / "src" / "test" / "report.json"
SITE = "https://library.example"


def sample_scan() -> ScanResult:
    """A small but complete scan: every result type, a shared element on two pages, a page that
    couldn't load, an AI finding and a site-wide finding."""

    def axe(page, criterion, rule, selector, html, *, status="fail", fix="Fix any of the following: ..."):
        return Finding(criterion=criterion, status=status, source="axe", rule=rule, message="Rule help text",
                       page=page, selector=selector, html=html, impact="serious", fix=fix,
                       help_url=f"https://dequeuniversity.com/rules/axe/4.10/{rule}", viewport="desktop+mobile")  # fmt: skip

    home, events = f"{SITE}/", f"{SITE}/events"
    pages = [
        PageResult(
            url=home, title="Maple Grove Library", tab_stops=7, screenshot="aGVsbG8=", checked=["1.1.1", "1.4.3", "2.4.7", "3.1.1", "4.1.2", "2.4.2", "1.3.1"],
            signals=PageSignals(title="Maple Grove Library"),
            findings=[
                axe(home, "1.1.1", "image-alt", "img.hero", '<img src="hero.svg" class="hero">'),
                axe(home, "1.4.3", "color-contrast", ".notice", '<p class="notice">Library hours change</p>'),
                axe(home, "3.1.1", "html-has-lang", "html", "<html>"),
                Finding(criterion="2.4.7", status="fail", source="keyboard", rule="focus-not-visible",
                        message="No visible focus indicator: nothing about 'Events' changes when it receives keyboard focus.",
                        fix="Don't remove the outline.", page=home, selector="nav > a:nth-child(2)", html='<a href="events.html">Events</a>',
                        impact="serious"),
                Finding(criterion="2.4.4", status="review", source="ai", rule="ai-244", message="The link text 'click here' is unclear.",
                        fix="Describe the destination.", page=home, selector="main a", confidence="medium", impact="moderate"),
            ],
        ),
        PageResult(
            url=events, title="Events", tab_stops=12, checked=["1.4.3"], signals=PageSignals(title="Events"),
            findings=[axe(events, "1.4.3", "color-contrast", ".notice", '<p class="notice">Library hours change</p>')],
            notes=["Dismissed a cookie banner before the keyboard and layout tests."],
        ),
        PageResult(url=f"{SITE}/members", error="Needs a login (HTTP 401)"),
    ]  # fmt: skip
    return ScanResult(
        id="0123456789ab", start_url=f"{SITE}/", level="AA", ai_enabled=True, started_at="2026-10-31T09:00:00+00:00",
        finished_at="2026-10-31T09:01:30+00:00", axe_version="4.10.3", axe_coverage=["1.1.1", "1.4.3", "3.1.1"],
        notes=["Respected robots.txt."], pages=pages, sitewide_checked=["2.4.5"],
        sitewide_findings=[Finding(criterion="2.4.5", status="review", source="sitewide", rule="multiple-ways",
                                   message="Navigation is the only way found to locate pages.", fix="Add site search.", impact="moderate")],
    )  # fmt: skip


def test_react_fixture_matches_what_the_api_produces():
    produced = build_report(sample_scan()).model_dump(mode="json")
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.write_text(json.dumps(produced, indent=2) + "\n")
    assert FIXTURE.exists(), "Run UPDATE_FIXTURES=1 pytest tests/test_contract.py to create the fixture"
    assert json.loads(FIXTURE.read_text()) == produced, (
        "The report API changed: update frontend/src/types.ts if the shape changed, "
        "then regenerate with UPDATE_FIXTURES=1 pytest tests/test_contract.py"
    )


def test_sample_covers_every_case_the_ui_renders():
    report = build_report(sample_scan())
    statuses = {row.status for p in report.principles for row in p.criteria}
    assert {"fail", "review", "pass", "manual", "na"} <= statuses
    assert any(len(i.pages) == 2 for issue in report.issues for g in issue.groups for i in g.instances)
    assert any(p.error for p in report.pages) and any(p.has_screenshot for p in report.pages)

"""End-to-end: scan the demo site and check every planted failure is reported."""

import asyncio
from urllib.parse import urlsplit

import pytest

from tests.conftest import ROOT
from wcag_scanner.aggregator import summarize
from wcag_scanner.report import render, render_report
from wcag_scanner.scanner import ScanOptions, scan_site

pytestmark = pytest.mark.browser

# (criterion, rule, page) for each failure planted in demo_site/. Page None = site-wide.
PLANTED = {
    ("1.1.1", "image-alt", "/demo_site/"),
    ("1.4.3", "color-contrast", "/demo_site/"),
    ("3.1.1", "html-has-lang", "/demo_site/"),
    ("2.4.7", "focus-not-visible", "/demo_site/"),
    ("2.1.1", "mouse-only-control", "/demo_site/"),
    ("1.4.12", "text-spacing-clipped", "/demo_site/"),
    ("1.4.10", "reflow-overflow", "/demo_site/"),
    ("2.4.11", "focus-obscured", "/demo_site/events.html"),
    ("2.2.2", "infinite-animation", "/demo_site/events.html"),
    ("2.1.2", "keyboard-trap", "/demo_site/contact.html"),
    ("2.4.1", "skip-link-broken", "/demo_site/contact.html"),
    ("3.3.2", "placeholder-only-label", "/demo_site/contact.html"),
    ("1.4.3", "color-contrast", "/demo_site/contact.html"),
    ("2.4.2", "duplicate-title", "/demo_site/events.html"),
    ("3.2.3", "nav-order-changes", "/demo_site/events.html"),
    ("2.4.5", "multiple-ways", None),
}


def _found(scan):
    findings = [f for p in scan.pages for f in p.findings] + scan.sitewide_findings
    return {(f.criterion, f.rule, urlsplit(f.page).path if f.page else None) for f in findings}


def test_every_planted_issue_is_found(demo_scan):
    found = _found(demo_scan)
    missing = PLANTED - found
    assert not missing, f"not detected: {sorted(missing, key=str)}"


def test_demo_site_pages_are_crawled_once(demo_scan):
    paths = sorted(p.url.split("/demo_site/")[1] for p in demo_scan.pages)
    assert paths == ["", "contact.html", "events.html"]
    assert all(p.error is None for p in demo_scan.pages)


def test_demo_verdict_is_fail(demo_scan):
    s = summarize(demo_scan)
    assert s.verdict_status == "fail"
    assert s.pages_with_failures == 3
    assert len(s.criteria) == 55  # WCAG 2.2 Level A + AA


def test_accessible_page_has_no_failures(accessible_scan):
    fails = [f for p in accessible_scan.pages for f in p.findings if f.status == "fail"]
    assert fails == [], [(f.criterion, f.rule, f.selector) for f in fails]
    s = summarize(accessible_scan)
    assert s.verdict_status != "fail"
    assert accessible_scan.pages[0].tab_stops >= 4


def test_accessible_patterns_are_not_flagged_for_review(accessible_scan):
    """A focusable card wrapper, a pointer-events:none label and a two-column link list are all fine."""
    rules = {f.rule for p in accessible_scan.pages for f in p.findings}
    assert not rules & {"mouse-only-control", "focus-jumps-back"}, rules


def test_popup_is_one_finding_and_fixed_drawer_is_not_blamed_for_reflow(server):
    scan = asyncio.run(scan_site(f"{server}/tests/fixtures/overlay.html", ScanOptions(max_pages=1)))
    findings = scan.pages[0].findings
    obscured = [f for f in findings if f.rule == "focus-obscured"]
    assert len(obscured) == 1 and "popup" in obscured[0].message
    reflow = [f for f in findings if f.rule == "reflow-overflow"]
    assert reflow and all("drawer" not in (f.html or "") for f in reflow)
    assert any("wide" in (f.html or "") for f in reflow)


@pytest.mark.parametrize("page", ["report", "home"])
def test_scanner_ui_is_accessible_itself(page, demo_scan, server):
    """Our own pages must pass the same checks we report on, with nothing left to review."""
    if page == "report":
        html = render_report(demo_scan, standalone=True)
        assert "Does not meet WCAG 2.2 Level AA" in html
    else:
        html = render(
            "index.html",
            scans=[],
            ai_available=False,
            error=None,
            url="",
            demo_url="http://example.com/demo-site/",
            max_pages=50,
        )
    out = ROOT / "tests" / "fixtures" / f"_{page}.html"
    out.write_text(html)
    try:
        scan = asyncio.run(scan_site(f"{server}/tests/fixtures/_{page}.html", ScanOptions(max_pages=1)))
    finally:
        out.unlink()
    issues = [(f.status, f.criterion, f.rule, f.selector) for p in scan.pages for f in p.findings]
    assert issues == []

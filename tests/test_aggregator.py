"""Turning findings into verdicts: per criterion, per page, and for the whole site."""

import pytest

from wcag_scanner.aggregator import summarize
from wcag_scanner.criteria import in_scope
from wcag_scanner.models import Finding, PageResult, ScanResult

SITE = "https://s.com"


def _scan(*pages, level="AA", sitewide=()):
    return ScanResult(
        id="t",
        start_url=f"{SITE}/",
        level=level,
        started_at="2026-01-01T00:00:00+00:00",
        pages=list(pages),
        sitewide_findings=list(sitewide),
    )


def _f(criterion="1.4.3", status="fail", rule="color-contrast", page=f"{SITE}/", selector=".x", **kw):
    return Finding(
        criterion=criterion,
        status=status,
        source="axe",
        rule=rule,
        message="m",
        page=page,
        selector=selector,
        html=f"<p class='{selector}'>",
        **kw,
    )


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [PageResult(url=f"{SITE}/", error="Page not found (HTTP 404)")],
        [
            PageResult(url=f"{SITE}/", error="Blocked by bot protection (HTTP 403)"),
            PageResult(url=f"{SITE}/a", error="Needs a login (HTTP 401)"),
        ],
    ],
)
def test_nothing_scanned_is_never_a_pass(pages):
    s = summarize(_scan(*pages))
    assert s.verdict_status == "error"
    assert s.counts["pass"] == 0 and s.counts["fail"] == 0 and s.counts["review"] == 0
    assert s.pages_scanned == 0
    for page in pages:
        assert page.error.split(" (")[0] in s.verdict_detail


def test_a_few_broken_pages_do_not_hide_the_rest():
    ok = PageResult(url=f"{SITE}/", checked=["1.4.3"], findings=[_f()])
    broken = PageResult(url=f"{SITE}/gone", error="Page not found (HTTP 404)")
    s = summarize(_scan(ok, broken))
    assert s.verdict_status == "fail"
    assert s.pages_scanned == 1
    assert [p.error for p in s.pages] == [None, "Page not found (HTTP 404)"]


@pytest.mark.parametrize(
    ("findings", "verdict"),
    [
        ([_f(status="fail")], "fail"),
        ([_f(status="review")], "review"),
        ([_f(status="review"), _f(criterion="2.4.7", rule="focus", status="fail")], "fail"),
        ([], "pass"),
    ],
)
def test_verdict_follows_the_worst_finding(findings, verdict):
    page = PageResult(url=f"{SITE}/", checked=["1.4.3", "2.4.7"], findings=findings)
    assert summarize(_scan(page)).verdict_status == verdict


@pytest.mark.parametrize(("level", "count"), [("A", 31), ("AA", 55), ("AAA", 86)])
def test_every_criterion_at_the_level_gets_exactly_one_result(level, count):
    s = summarize(_scan(PageResult(url=f"{SITE}/"), level=level))
    assert len(s.criteria) == count == len(in_scope(level))
    assert sum(s.counts.values()) == count


def test_the_same_element_on_many_pages_is_one_instance():
    """A broken shared header is one fix, not one per page."""
    header = [_f(page=f"{SITE}/{p}", selector="header > button") for p in ("", "a", "b", "c")]
    one_off = [_f(page=f"{SITE}/a", selector="main > .promo")]
    page = PageResult(url=f"{SITE}/", checked=["1.4.3"], findings=header + one_off)
    group = next(r for r in summarize(_scan(page)).criteria if r.criterion.id == "1.4.3").groups[0]
    assert len(group.findings) == 5
    assert [len(i.pages) for i in group.instances] == [4, 1]  # most widespread first
    assert group.instances[0].finding.selector == "header > button"


def test_site_wide_findings_without_a_page_stay_one_instance():
    sitewide = [Finding(criterion="2.4.5", status="review", source="sitewide", rule="multiple-ways", message="m")]
    s = summarize(_scan(PageResult(url=f"{SITE}/", checked=[]), sitewide=sitewide))
    group = next(r for r in s.criteria if r.criterion.id == "2.4.5").groups[0]
    assert len(group.instances) == 1 and group.instances[0].pages == []


def test_findings_outside_the_level_do_not_count():
    aaa_only = _f(criterion="1.4.6", rule="color-contrast-enhanced")
    page = PageResult(url=f"{SITE}/", checked=["1.4.6"], findings=[aaa_only])
    s = summarize(_scan(page, level="AA"))
    assert s.verdict_status == "pass"
    assert s.pages[0].fails == 0


def test_failing_pages_are_counted_per_criterion():
    findings = [_f(page=f"{SITE}/{p}", selector=f".s{p}") for p in ("a", "a", "b")]
    page = PageResult(url=f"{SITE}/", checked=["1.4.3"], findings=findings)
    row = next(r for r in summarize(_scan(page)).criteria if r.criterion.id == "1.4.3")
    assert (row.fails, row.pages_failing) == (3, 2)


def test_status_precedence():
    page = PageResult(
        url="https://s.com/",
        checked=["1.4.3", "2.4.7", "1.1.1"],
        findings=[
            Finding(
                criterion="1.4.3",
                status="review",
                source="axe",
                rule="color-contrast",
                message="m",
                page="https://s.com/",
            ),
            Finding(
                criterion="1.4.3",
                status="fail",
                source="axe",
                rule="color-contrast",
                message="m",
                page="https://s.com/",
            ),
            Finding(
                criterion="2.4.7", status="review", source="keyboard", rule="x", message="m", page="https://s.com/"
            ),
        ],
    )
    scan = ScanResult(id="t", start_url="https://s.com/", started_at="2026-01-01T00:00:00+00:00", pages=[page])
    status = {r.criterion.id: r.status for r in summarize(scan).criteria}
    assert status["1.4.3"] == "fail"
    assert status["2.4.7"] == "review"
    assert status["1.1.1"] == "pass"
    assert status["1.2.2"] == "na"  # no media anywhere
    assert status["3.3.8"] == "manual"  # nothing tests it

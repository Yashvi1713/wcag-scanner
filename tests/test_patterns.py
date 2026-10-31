"""Interaction patterns that are easy to get wrong in both directions: real problems that must be
found, and correct implementations that must not be reported."""

import asyncio

import pytest

from wcag_scanner.scanner import ScanOptions, scan_site

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def page(server):
    scan = asyncio.run(scan_site(f"{server}/tests/fixtures/patterns.html", ScanOptions(max_pages=1)))
    assert scan.pages[0].error is None, scan.pages[0].error
    return scan.pages[0]


def _rules(page):
    return {(f.criterion, f.rule, f.status) for f in page.findings}


def test_sound_that_plays_on_its_own_without_controls_fails(page):
    assert ("1.4.2", "autoplay-audio", "fail") in _rules(page)


def test_moving_video_without_controls_needs_review(page):
    assert ("2.2.2", "autoplay-motion", "review") in _rules(page)


def test_a_modal_that_escape_closes_is_a_loop_not_a_trap(page):
    rules = _rules(page)
    assert ("2.1.2", "focus-loop", "review") in rules
    assert not any(rule == "keyboard-trap" for _, rule, _ in rules)


def test_content_that_fades_in_on_focus_is_not_invisible_focus(page):
    flagged = [f for f in page.findings if f.rule == "focus-invisible-element"]
    assert not [f for f in flagged if "Fades in" in f.message], flagged


def test_tabbing_through_an_iframe_is_not_reported(page):
    # Focus inside a frame is drawn by the frame's own document, and the walk continues after it.
    assert not [f for f in page.findings if f.rule.startswith("focus") and "iframe" in (f.html or "")]
    assert page.tab_stops >= 5

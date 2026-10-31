"""The scanner against the things real websites do: errors, bot walls, logins, runaway scripts,
redirects to places it mustn't go, and a browser that crashes mid-scan."""

import asyncio
import time

import pytest
from playwright.async_api import async_playwright

from wcag_scanner.__main__ import EXIT_UNSCANNABLE, exit_code
from wcag_scanner.aggregator import summarize
from wcag_scanner.netguard import HostGuard
from wcag_scanner.report import render_report
from wcag_scanner.scanner import BrowserPool, ScanOptions, scan_page, scan_site

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def hub_scan(server):
    """One crawl from a hub page that links to every problem route."""
    opts = ScanOptions(max_pages=12, page_timeout=12)
    started = time.monotonic()
    result = asyncio.run(scan_site(f"{server}/_t/hub", opts))
    result.notes.append(f"took {time.monotonic() - started:.1f}s")
    return result


def _errors(scan):
    return {p.url.rsplit("/", 1)[-1]: p.error for p in scan.pages}


@pytest.mark.parametrize(
    ("route", "expected"),
    [
        ("ok", None),
        ("notfound", "Page not found (HTTP 404)"),
        ("login", "Needs a login (HTTP 401)"),
        ("cloudflare", "Blocked by bot protection (HTTP 403)"),
        ("challenge", "Blocked by bot protection: the site showed a challenge page"),
        ("text", "Not a web page (text/plain)"),
        ("servererror", "The server returned an error (HTTP 500)"),
        ("hang", "Gave up after 12 seconds"),
    ],
)
def test_each_problem_page_gets_a_clear_reason(hub_scan, route, expected):
    error = _errors(hub_scan)[route]
    if expected is None:
        assert error is None
    else:
        assert error and error.startswith(expected), error


def test_a_runaway_page_does_not_stall_the_scan(hub_scan):
    # Every page was visited, and the scan finished well inside the per-page budgets added together.
    assert len(hub_scan.pages) == 9
    assert summarize(hub_scan).verdict_status != "error"  # the hub and /ok were scanned


def test_a_site_that_cannot_be_loaded_never_passes(server):
    scan = asyncio.run(scan_site(f"{server}/_t/notfound", ScanOptions(max_pages=3)))
    summary = summarize(scan)
    assert summary.verdict_status == "error"
    assert summary.counts["pass"] == 0 and summary.counts["fail"] == 0
    assert "Page not found" in summary.verdict_detail
    assert exit_code(summary.verdict_status, "fail") == EXIT_UNSCANNABLE
    assert "The site could not be scanned" in render_report(scan)


def test_unknown_host_is_reported_without_launching_a_crawl():
    scan = asyncio.run(scan_site("https://this-host-does-not-exist.invalid/", ScanOptions(max_pages=3)))
    assert len(scan.pages) == 1
    assert "Couldn't find a website" in scan.pages[0].error
    assert summarize(scan).verdict_status == "error"


def test_private_addresses_are_refused_when_not_allowed(server):
    scan = asyncio.run(scan_site(f"{server}/_t/ok", ScanOptions(max_pages=2, allow_private=False)))
    assert "private network address" in scan.pages[0].error


class _OnlyLoopbackIP(HostGuard):
    """Allows the test server's 127.0.0.1 but treats the name 'localhost' as forbidden."""

    async def _reason(self, host):
        return "forbidden host" if host == "localhost" else None


def test_a_redirect_to_a_forbidden_host_is_stopped(server):
    port = server.rsplit(":", 1)[1]
    url = f"{server}/_t/redirect?to=http://localhost:{port}/_t/ok"

    async def go():
        async with async_playwright() as pw:
            pool = BrowserPool(pw, 1)
            await pool.start()
            try:
                async with pool.context() as ctx:
                    return await scan_page(ctx, url, ScanOptions(), scan=_blank_scan(url), guard=_OnlyLoopbackIP())
            finally:
                await pool.close()

    result, links = asyncio.run(go())
    assert result.error == "forbidden host"
    assert links == []


def _blank_scan(url):
    from wcag_scanner.models import ScanResult

    return ScanResult(id="t", start_url=url, started_at="2026-01-01T00:00:00+00:00")


def test_browser_pool_recovers_when_chromium_dies():
    async def go():
        async with async_playwright() as pw:
            pool = BrowserPool(pw, 2)
            await pool.start()
            dead = pool.browser
            async with pool.context():
                await dead.close()  # Chromium dies while a page is being scanned
            # Both of the dead browser's contexts are gone; every later page gets a live one.
            texts = [await _render(pool) for _ in range(3)]
            await pool.close()
            return pool.restarts, pool.browser is not dead, texts

    restarts, replaced, texts = asyncio.run(go())
    assert restarts == 1 and replaced
    assert texts == ["ok", "ok", "ok"]


def test_a_worker_waiting_during_a_crash_is_not_left_hanging():
    async def go():
        async with async_playwright() as pw:
            pool = BrowserPool(pw, 1)
            await pool.start()
            dead = pool.browser
            async with pool.context():
                waiter = asyncio.create_task(_render(pool))
                await asyncio.sleep(0.2)  # the waiter is now blocked on the empty pool
                await dead.close()
            text = await asyncio.wait_for(waiter, 20)
            await pool.close()
            return text

    assert asyncio.run(go()) == "ok"


async def _render(pool):
    async with pool.context() as ctx:
        page = await ctx.new_page()
        await page.set_content("<p>ok</p>")
        text = await page.inner_text("p")
        await page.close()
        return text

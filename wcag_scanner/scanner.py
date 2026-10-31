"""Scan a whole site: crawl it, run every layer of checks on each page, then the site-wide checks."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import anthropic
from playwright.async_api import Browser, BrowserContext, Page, Playwright, Response, async_playwright

from . import ai_review, axe_runner
from .crawler import Frontier, normalize
from .interaction import DESKTOP, MOBILE, form_checks, inject_probe, keyboard_walk, layout_checks, media_checks
from .models import Finding, PageResult, PageSignals, ScanResult
from .netguard import BlockedAddress, HostGuard, UnknownHost
from .sitewide import sitewide_checks

log = logging.getLogger(__name__)

CONSENT_BUTTON = re.compile(
    r"^\s*(accept( all)?( cookies)?|allow( all)?( cookies)?|i agree|agree( and close)?|got it|ok(ay)?|i understand|"
    r"accept (and|&) close)\s*$",
    re.I,
)

# Interstitials served instead of the real page by bot protection (Cloudflare, Akamai, Imperva, ...).
BOT_WALL = re.compile(
    r"just a moment|attention required|access denied|verify(ing)? you are (a )?human|"
    r"are you a robot|pardon our interruption|request unsuccessful|security check",
    re.I,
)

ProgressFn = Callable[[dict], None]


@dataclass
class ScanOptions:
    max_pages: int = 10
    level: str = "AA"
    ai: bool = False
    ai_pages: int = 5
    concurrency: int = 3
    max_tabs: int = 80
    page_timeout: float = 120.0  # seconds for every check on one page; a hung page can't stall the scan
    scan_timeout: float = 900.0  # no new pages are started after this many seconds
    allow_private: bool = True  # the web app turns this off so visitors can't scan internal networks


class BrowserPool:
    """A fixed number of browser contexts shared by the page workers. If Chromium crashes,
    it is relaunched and the contexts recreated, so one bad page can't fail every page after it."""

    MAX_RESTARTS = 3

    def __init__(self, pw: Playwright, size: int):
        self.pw, self.size = pw, size
        self.browser: Browser | None = None
        self.restarts = 0
        self._idle: asyncio.Queue[BrowserContext] = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self.browser = await self.pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        ua = (
            f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{self.browser.version} Safari/537.36 WCAGScanner/1.0"
        )
        # Keep the same queue: workers may already be waiting on it. Drop contexts of a dead browser,
        # then refill to the full size (contexts still checked out are discarded when they come back).
        while not self._idle.empty():
            self._idle.get_nowait()
        for _ in range(self.size):
            await self._idle.put(await self.browser.new_context(viewport=DESKTOP, bypass_csp=True, user_agent=ua))

    @contextlib.asynccontextmanager
    async def context(self) -> AsyncIterator[BrowserContext]:
        ctx = await self._idle.get()
        try:
            yield ctx
        finally:
            if ctx.browser is self.browser and self.browser is not None and self.browser.is_connected():
                await self._idle.put(ctx)
            else:
                await self._recover(ctx)

    async def _recover(self, ctx: BrowserContext) -> None:
        async with self._lock:
            if ctx.browser is not self.browser:
                return  # another worker already restarted; this context belonged to the dead browser
            if self.restarts >= self.MAX_RESTARTS:
                raise RuntimeError("The browser crashed repeatedly; stopping the scan.")
            self.restarts += 1
            log.warning("Browser disconnected; restarting (%d/%d)", self.restarts, self.MAX_RESTARTS)
            await self.start()

    async def close(self) -> None:
        if self.browser is not None and self.browser.is_connected():
            await self.browser.close()


async def scan_site(
    start_url: str, options: ScanOptions | None = None, progress: ProgressFn | None = None, scan_id: str | None = None
) -> ScanResult:
    opts = options or ScanOptions()
    report = progress or (lambda _: None)
    result = ScanResult(
        id=scan_id or uuid.uuid4().hex[:12],
        start_url=start_url,
        level=opts.level,
        ai_enabled=opts.ai,
        started_at=_now(),
    )
    guard = HostGuard(allow_private=opts.allow_private)
    try:
        await guard.check(start_url)
    except (BlockedAddress, UnknownHost) as e:  # a typo, or a private address the web app may not scan
        result.pages.append(PageResult(url=start_url, error=str(e)))
        result.finished_at = _now()
        return result

    frontier = Frontier(start_url, opts.max_pages, guard)
    report({"stage": "crawl", "message": "Reading robots.txt and sitemap", "done": 0, "total": 1})
    result.notes += await frontier.prepare()

    ai_client = anthropic.AsyncAnthropic() if opts.ai else None
    ai_left = opts.ai_pages if opts.ai else 0
    deadline = time.monotonic() + opts.scan_timeout
    out_of_time = False
    scanned: set[str] = set()

    async with async_playwright() as pw:
        pool = BrowserPool(pw, opts.concurrency)
        await pool.start()

        async def run(url: str) -> tuple[PageResult, list[str]] | None:
            nonlocal ai_left, out_of_time
            async with pool.context() as ctx:
                if time.monotonic() > deadline:
                    out_of_time = True
                    return None
                use_ai = ai_client is not None and ai_left > 0
                if use_ai:
                    ai_left -= 1
                report(
                    {
                        "stage": "page",
                        "message": f"Scanning {url}",
                        "done": len(result.pages),
                        "total": len(frontier.planned),
                    }
                )
                try:
                    return await asyncio.wait_for(
                        scan_page(ctx, url, opts, scan=result, ai_client=ai_client if use_ai else None, guard=guard),
                        opts.page_timeout,
                    )
                except TimeoutError:
                    log.warning("Page timed out after %ss: %s", opts.page_timeout, url)
                    return PageResult(
                        url=url, error=f"Gave up after {opts.page_timeout:.0f} seconds: the page kept the browser busy"
                    ), []

        first = True
        try:
            while frontier.queue and not out_of_time:
                wave = frontier.take_wave()
                for outcome in await asyncio.gather(*(run(u) for u in wave)):
                    if outcome is None:
                        continue
                    page_result, links = outcome
                    key = normalize(page_result.url) or page_result.url
                    if key in scanned:
                        continue  # redirected to a page we already scanned
                    scanned.add(key)
                    result.pages.append(page_result)
                    if first and not page_result.error:
                        frontier.set_origin(page_result.url)
                    for link in links:
                        frontier.offer(link)
                if first and len(frontier.planned) < opts.max_pages:
                    frontier.fill_from_sitemap()
                first = False
                report(
                    {
                        "stage": "page",
                        "message": f"Scanned {len(result.pages)} pages",
                        "done": len(result.pages),
                        "total": len(frontier.planned),
                    }
                )
        finally:
            await pool.close()

    if out_of_time:
        result.notes.append(
            f"Stopped starting new pages after {opts.scan_timeout / 60:.0f} minutes; "
            f"{len(result.pages)} pages were scanned."
        )
    if pool.restarts:
        result.notes.append(f"The browser crashed and was restarted {pool.restarts} time(s) during the scan.")
    report({"stage": "sitewide", "message": "Comparing pages", "done": len(result.pages), "total": len(result.pages)})
    findings, checked = sitewide_checks(result.pages)
    result.sitewide_findings = findings
    result.sitewide_checked = sorted(checked)
    result.finished_at = _now()
    return result


async def scan_page(
    ctx: BrowserContext,
    url: str,
    opts: ScanOptions,
    *,
    scan: ScanResult,
    ai_client: anthropic.AsyncAnthropic | None = None,
    guard: HostGuard | None = None,
) -> tuple[PageResult, list[str]]:
    """Run every per-page check. Returns the result and the links found on the page."""
    guard = guard or HostGuard(allow_private=True)
    started = time.monotonic()
    result = PageResult(url=url)
    checked: set[str] = set()
    links: list[str] = []
    stage = _stage_timer(result.timings)
    page = await ctx.new_page()
    try:
        with stage("load"):
            await guard.check(url)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await guard.check(page.url)  # a redirect may have led somewhere we must not fetch
            if error := _load_error(response):
                result.error = error
                return result, links
            await _settle(page)
        result.url = page.url
        if BOT_WALL.search(await page.title()):
            result.error = "Blocked by bot protection: the site showed a challenge page instead of its content"
            return result, links

        # Layer 1: axe-core at desktop size (with any cookie banner still showing).
        with stage("axe_desktop"):
            if not scan.axe_coverage:
                scan.axe_coverage = await axe_runner.coverage(page, opts.level)
            findings, axe_checked, scan.axe_version = await axe_runner.run_axe(page, opts.level, "desktop")
        checked |= axe_checked

        with stage("cookie_banner"):
            if await _dismiss_cookie_banner(page):
                result.notes.append("Dismissed a cookie banner before the keyboard and layout tests.")
                await page.reload(wait_until="domcontentloaded")
                await _settle(page)

        await inject_probe(page)
        signals = await page.evaluate("() => window.__wcagProbe.signals()")
        result.title = signals["title"]
        links = [link["href"] for link in signals["links"]]

        # Layer 2: media, keyboard, layout.
        with stage("media_forms"):
            media_findings, media_checked, media_count = await media_checks(page)
            form_findings, form_checked = await form_checks(page)
        with stage("keyboard"):
            kb_findings, kb_checked, result.tab_stops = await keyboard_walk(page, opts.max_tabs)
        with stage("layout"):
            layout_findings, layout_checked = await layout_checks(page)
        findings += media_findings + kb_findings + form_findings + layout_findings
        checked |= media_checked | kb_checked | form_checked | layout_checked

        # Layer 1 again at phone size; merge duplicates.
        with stage("axe_mobile"):
            await page.set_viewport_size(MOBILE)
            await page.wait_for_timeout(400)
            mobile_findings, mobile_checked, _ = await axe_runner.run_axe(page, opts.level, "mobile")
            await page.set_viewport_size(DESKTOP)
            await page.wait_for_timeout(200)
        findings = _merge_viewports(findings, mobile_findings)
        checked |= mobile_checked

        # Layer 4: AI review. Optional, so a failure here costs only the AI findings, never the page.
        if ai_client is not None:
            try:
                with stage("ai"):
                    ai_findings, note = await ai_review.review_page(ai_client, page)
            except Exception as e:
                log.warning("AI review failed on %s", url, exc_info=True)
                ai_findings, note = [], f"AI review skipped: {type(e).__name__}."
            findings += ai_findings
            if note:
                result.notes.append(note)

        result.signals = PageSignals(
            title=signals["title"],
            nav_names=signals["navNames"],
            chrome_links=[(link["href"], link["name"]) for link in signals["links"] if link["chrome"]],
            help=signals["help"],
            has_search=signals["hasSearch"],
            has_sitemap_link=signals["hasSitemapLink"],
            media_count=media_count,
        )
        result.findings = findings
        result.checked = sorted(checked)
        if findings:  # a screenshot only earns its (large) place when it shows something to fix
            try:
                with stage("screenshot"):
                    result.screenshot = await _annotated_screenshot(page, findings)
            except Exception:
                log.warning("Screenshot failed on %s", url, exc_info=True)  # the findings still stand
    except (BlockedAddress, UnknownHost) as e:
        result.error = str(e)
    except Exception as e:  # one broken page must not stop the whole scan
        log.debug("Page failed: %s", url, exc_info=True)
        first_line = (str(e).splitlines() or [""])[0][:200]
        result.error = f"Scan failed: {type(e).__name__}: {first_line}"
    finally:
        result.seconds = round(time.monotonic() - started, 1)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(page.close(), 10)
    log.info(
        "%s %s in %.1fs (%d findings)",
        "Skipped" if result.error else "Scanned",
        url,
        result.seconds,
        len(result.findings),
    )
    return result, links


def _stage_timer(timings: dict[str, float]) -> Callable[[str], contextlib.AbstractContextManager[None]]:
    @contextlib.contextmanager
    def stage(name: str) -> Iterator[None]:
        t0 = time.monotonic()
        try:
            yield
        finally:
            timings[name] = round(time.monotonic() - t0, 2)

    return stage


def _load_error(response: Response | None) -> str | None:
    """Why a navigation can't be scanned, or None if it can."""
    if response is None:
        return "The server sent no response"
    status = response.status
    if status in (401, 407):
        return f"Needs a login (HTTP {status})"
    if status in (403, 429, 503) and _looks_like_bot_wall(response):
        return f"Blocked by bot protection (HTTP {status})"
    if status == 404:
        return "Page not found (HTTP 404)"
    if status >= 400:
        return f"The server returned an error (HTTP {status})"
    content_type = response.headers.get("content-type", "text/html")
    if "html" not in content_type:
        return f"Not a web page ({content_type.split(';')[0]})"
    return None


def _looks_like_bot_wall(response: Response) -> bool:
    headers = response.headers
    return (
        "cf-mitigated" in headers
        or headers.get("server", "").lower() in ("cloudflare", "akamaighost")
        or "x-amzn-waf-action" in headers
        or response.status == 429
    )


async def _settle(page: Page) -> None:
    """Wait until the page is ready to test. The load event covers images and stylesheets; a short
    network-idle grace then catches late client-side rendering. Sites with endless analytics traffic
    never go idle, so that wait is capped: measured on a busy shop it saved about 4 s per page."""
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("load", timeout=10000)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=2000)
    await page.wait_for_timeout(300)


async def _dismiss_cookie_banner(page: Page) -> bool:
    button = page.get_by_role("button", name=CONSENT_BUTTON)
    try:
        if await button.count() and await button.first.is_visible():
            await button.first.click(timeout=2000)
            await page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    return False


def _merge_viewports(desktop: list[Finding], mobile: list[Finding]) -> list[Finding]:
    index = {(f.criterion, f.rule, f.selector): f for f in desktop if f.source == "axe"}
    merged = list(desktop)
    for f in mobile:
        twin = index.get((f.criterion, f.rule, f.selector))
        if twin:
            twin.viewport = "desktop+mobile"
        else:
            merged.append(f)
    return merged


async def _annotated_screenshot(page: Page, findings: list[Finding]) -> str:
    selectors = list(
        dict.fromkeys(
            f.selector
            for f in findings
            if f.status == "fail" and f.selector and ">>>" not in f.selector and f.viewport != "mobile"
        )
    )[:40]
    await page.evaluate("(s) => window.__wcagProbe.annotate(s)", selectors)
    await page.evaluate("() => window.scrollTo(0, 0)")
    height = await page.evaluate("() => Math.min(document.documentElement.scrollHeight, 2400)")
    shot = await page.screenshot(
        type="jpeg",
        quality=55,
        full_page=True,
        clip={"x": 0, "y": 0, "width": DESKTOP["width"], "height": max(height, 200)},
    )
    return base64.standard_b64encode(shot).decode()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

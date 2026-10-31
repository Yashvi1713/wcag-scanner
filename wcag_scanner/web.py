"""The web app: enter a URL, watch the scan, read and download the report."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import storage
from .aggregator import summarize
from .ai_review import ai_available
from .crawler import is_scannable
from .criteria import LEVEL_RANK
from .netguard import BlockedAddress, HostGuard, UnknownHost
from .report import render, render_pdf, render_report
from .scanner import ScanOptions, scan_site

log = logging.getLogger(__name__)

DEMO_SITE = Path(__file__).parent.parent / "demo_site"
MAX_PAGES = int(os.environ.get("WCAG_SCANNER_MAX_PAGES", "50"))
MAX_ACTIVE = int(os.environ.get("WCAG_SCANNER_MAX_ACTIVE", "10"))  # queued + running scans
PARALLEL_SCANS = int(os.environ.get("WCAG_SCANNER_PARALLEL", "2"))  # scans driving browsers at once
ALLOW_PRIVATE = os.environ.get("WCAG_SCANNER_ALLOW_PRIVATE", "").lower() in ("1", "true", "yes")
SCAN_ID = re.compile(r"^[0-9a-f]{12}$")

_running: set[asyncio.Task] = set()
_slots = asyncio.Semaphore(PARALLEL_SCANS)
_pdf_cache: OrderedDict[str, bytes] = OrderedDict()  # finished reports never change, so PDFs can be reused
PDF_CACHE_SIZE = 8


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if recovered := storage.recover_interrupted():
        log.warning("Marked %d interrupted scan(s) as failed", recovered)
    yield
    for task in list(_running):
        task.cancel()


app = FastAPI(title="WCAG Scanner", lifespan=lifespan)
app.mount("/demo-site", StaticFiles(directory=DEMO_SITE, html=True), name="demo-site")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


def _page(template: str, status: int = 200, **context) -> HTMLResponse:
    return HTMLResponse(render(template, **context), status_code=status)


def _message(heading: str, text: str, status: int) -> HTMLResponse:
    return _page("message.html", status, heading=heading, text=text)


def _index(request: Request, error: str | None = None, url: str = "", status: int = 200) -> HTMLResponse:
    return _page(
        "index.html",
        status,
        scans=storage.recent(),
        ai_available=ai_available(),
        error=error,
        url=url,
        demo_url=_demo_url(request),
        max_pages=MAX_PAGES,
    )


def _demo_url(request: Request) -> str:
    """The demo's address as the visitor sees it (shown on the home page)."""
    return f"{request.base_url}demo-site/"


def _internal_base(request: Request) -> str:
    """This server's address as its own browser sees it. Behind a port mapping or a reverse proxy the
    visitor's address (e.g. localhost:8011) doesn't exist inside the container, but the socket the
    request arrived on always does."""
    host, port = request.scope.get("server") or ("127.0.0.1", 8000)
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}/"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _index(request)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "active_scans": len(_running)}


@app.post("/scans")
async def create_scan(
    request: Request,
    url: str = Form(""),
    max_pages: str = Form("10"),
    level: str = Form("AA"),
    ai: str | None = Form(None),
):
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    # The built-in demo is served by this app, at whatever address the app runs on (which may be
    # a private one, or a name without a dot such as a Docker service), so it skips the address checks.
    is_demo = url.startswith(_demo_url(request))
    if not is_demo and not is_scannable(url):
        return _index(request, "Enter a full web address, for example https://example.com.", url, 400)
    pages = int(max_pages) if max_pages.strip().isdigit() else 0
    if level not in LEVEL_RANK or not 1 <= pages <= MAX_PAGES:
        return _index(request, f"Choose a level of A, AA or AAA and between 1 and {MAX_PAGES} pages.", url, 400)

    allow_private = ALLOW_PRIVATE or is_demo
    if is_demo:
        url = _internal_base(request) + url.removeprefix(str(request.base_url))
    if not is_demo:
        try:
            await HostGuard(allow_private=allow_private).check(url)
        except UnknownHost as e:
            return _index(request, f"{e} Check the address for typos.", url, 400)
        except BlockedAddress as e:
            return _index(request, str(e), url, 400)

    if storage.active_count() >= MAX_ACTIVE:
        return _message("The scanner is busy", "Too many scans are running. Please try again in a few minutes.", 429)

    scan_id = uuid.uuid4().hex[:12]
    storage.create(scan_id, url)
    opts = ScanOptions(max_pages=pages, level=level, ai=bool(ai) and ai_available(), allow_private=allow_private)
    task = asyncio.create_task(_run_scan(scan_id, url, opts))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return RedirectResponse(f"/scans/{scan_id}", status_code=303)


async def _run_scan(scan_id: str, url: str, opts: ScanOptions) -> None:
    async with _slots:
        storage.set_status(scan_id, "running")
        try:
            result = await scan_site(url, opts, progress=lambda p: storage.update_progress(scan_id, p), scan_id=scan_id)
            summary = summarize(result)
            storage.finish(scan_id, result, summary.counts["fail"], summary.verdict_status)
        except asyncio.CancelledError:
            storage.fail(scan_id, "The server stopped before this scan finished. Please run it again.")
            raise
        except Exception as e:
            log.exception("Scan %s failed", scan_id)
            storage.fail(scan_id, f"{type(e).__name__}: {e}")


def _finished(scan_id: str) -> dict | None:
    scan = storage.get(scan_id) if SCAN_ID.match(scan_id) else None
    return scan if scan and scan["result"] else None


@app.get("/scans/{scan_id}", response_class=HTMLResponse)
async def show_scan(scan_id: str):
    status = storage.get_status(scan_id) if SCAN_ID.match(scan_id) else None
    if not status:
        return _message("Scan not found", "There's no scan with that ID.", 404)
    if status["status"] == "error":
        return _message("The scan failed", status["error"] or "Unknown error.", 500)
    if status["status"] == "done" and (scan := _finished(scan_id)):
        return HTMLResponse(render_report(scan["result"]))
    return _page("progress.html", scan=status)


@app.get("/scans/{scan_id}/status")
async def scan_status(scan_id: str):
    status = storage.get_status(scan_id) if SCAN_ID.match(scan_id) else None
    if not status:
        return JSONResponse({"status": "missing"}, status_code=404)
    return {"status": status["status"], "progress": status["progress"], "error": status["error"]}


def _not_ready() -> JSONResponse:
    return JSONResponse({"error": "This report doesn't exist or isn't finished yet."}, status_code=404)


def _download(scan_id: str, ext: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="wcag-report-{scan_id}.{ext}"'}


@app.get("/scans/{scan_id}/report.json")
async def report_json(scan_id: str):
    if not (scan := _finished(scan_id)):
        return _not_ready()
    body = scan["result"].model_dump_json(indent=2, exclude={"pages": {"__all__": {"screenshot"}}})
    return Response(body, media_type="application/json", headers=_download(scan_id, "json"))


@app.get("/scans/{scan_id}/report.html")
async def report_html(scan_id: str):
    if not (scan := _finished(scan_id)):
        return _not_ready()
    return HTMLResponse(render_report(scan["result"], standalone=True), headers=_download(scan_id, "html"))


@app.get("/scans/{scan_id}/report.pdf")
async def report_pdf(scan_id: str):
    if (pdf := _pdf_cache.get(scan_id)) is None:
        if not (scan := _finished(scan_id)):
            return _not_ready()
        pdf = await render_pdf(render_report(scan["result"], standalone=True))
        _pdf_cache[scan_id] = pdf
        while len(_pdf_cache) > PDF_CACHE_SIZE:
            _pdf_cache.popitem(last=False)
    _pdf_cache.move_to_end(scan_id)
    return Response(pdf, media_type="application/pdf", headers=_download(scan_id, "pdf"))

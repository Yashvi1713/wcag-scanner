"""The web server: the JSON API, the report downloads, and the React app."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import api, storage
from .report import render_pdf, render_report
from .settings import settings

log = logging.getLogger(__name__)

_pdf_cache: OrderedDict[str, bytes] = OrderedDict()  # finished reports never change, so PDFs can be reused
PDF_CACHE_SIZE = 8


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if recovered := storage.recover_interrupted():
        log.warning("Marked %d interrupted scan(s) as failed", recovered)
    if not (settings.frontend_dist / "index.html").exists():
        log.warning("The React app isn't built: run `npm ci && npm run build` in frontend/")
    yield
    api.cancel_running()


app = FastAPI(title="WCAG Scanner", lifespan=lifespan)
app.include_router(api.router)
app.add_exception_handler(api.ApiProblem, api.problem_handler)
app.mount("/demo-site", StaticFiles(directory=settings.demo_site, html=True), name="demo-site")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/assets/"):  # file names contain a content hash
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "active_scans": api.running_count()}


# ---- Downloads: self-contained documents that work offline and print to PDF ----


def _not_ready() -> JSONResponse:
    return JSONResponse({"error": "This report doesn't exist or isn't finished yet."}, status_code=404)


def _download(scan_id: str, ext: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="wcag-report-{scan_id}.{ext}"'}


@app.get("/scans/{scan_id}/report.json")
async def report_json(scan_id: str):
    if not (scan := api.finished_scan(scan_id)):
        return _not_ready()
    body = scan.model_dump_json(indent=2, exclude={"pages": {"__all__": {"screenshot"}}})
    return Response(body, media_type="application/json", headers=_download(scan_id, "json"))


@app.get("/scans/{scan_id}/report.html")
async def report_html(scan_id: str):
    if not (scan := api.finished_scan(scan_id)):
        return _not_ready()
    return HTMLResponse(render_report(scan), headers=_download(scan_id, "html"))


@app.get("/scans/{scan_id}/report.pdf")
async def report_pdf(scan_id: str):
    if (pdf := _pdf_cache.get(scan_id)) is None:
        if not (scan := api.finished_scan(scan_id)):
            return _not_ready()
        pdf = await render_pdf(render_report(scan))
        _pdf_cache[scan_id] = pdf
        while len(_pdf_cache) > PDF_CACHE_SIZE:
            _pdf_cache.popitem(last=False)
    _pdf_cache.move_to_end(scan_id)
    return Response(pdf, media_type="application/pdf", headers=_download(scan_id, "pdf"))


# ---- The React app: static assets, and index.html for every client-side route ----

if (settings.frontend_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        return JSONResponse({"error": "Not found."}, status_code=404)
    index = settings.frontend_dist / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<!doctype html><html lang='en'><title>WCAG Scanner</title><main><h1>The app isn't built yet</h1>"
            "<p>Run <code>npm ci &amp;&amp; npm run build</code> in the <code>frontend</code> folder, then reload.</p></main>",
            status_code=503,
        )
    return FileResponse(index, headers={"Cache-Control": "no-cache"})

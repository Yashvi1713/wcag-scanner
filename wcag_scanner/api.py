"""The JSON API the React front end talks to.

Every response has a schema, so FastAPI validates what goes out and documents it at /docs.
The report view is computed here, once, so the browser only renders it.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from itertools import groupby
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import storage
from .aggregator import CriterionResult, Instance, RuleGroup, Summary, summarize
from .ai_review import ai_available
from .crawler import is_scannable
from .criteria import LEVEL_RANK, Criterion
from .models import ScanResult
from .netguard import BlockedAddress, HostGuard, UnknownHost
from .scanner import ScanOptions, scan_site
from .settings import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

Status = Literal["fail", "review", "pass", "manual", "na"]
MAX_INSTANCES = 50  # per rule; the JSON download has every occurrence


# ---- Schemas ----------------------------------------------------------------


class Config(BaseModel):
    max_pages: int
    ai_available: bool
    demo_url: str


class RecentScan(BaseModel):
    id: str
    url: str
    status: Literal["queued", "running", "done", "error"]
    created_at: str
    pages: int | None
    fails: int | None
    verdict: str | None


class ScanRequest(BaseModel):
    url: str = ""
    max_pages: int | str = 10  # a string so "abc" gets a friendly error instead of a 422
    level: str = "AA"
    ai: bool = False


class ScanCreated(BaseModel):
    id: str


class ApiError(BaseModel):
    error: str
    field: Literal["url", "max_pages", "level"] | None = None


class ApiProblem(Exception):
    """Raised by an endpoint to answer with an ApiError body; see problem_handler."""

    def __init__(self, status: int, error: str, field: Literal["url", "max_pages", "level"] | None = None):
        super().__init__(error)
        self.status, self.body = status, ApiError(error=error, field=field)


async def problem_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiProblem)
    return JSONResponse(exc.body.model_dump(), status_code=exc.status)


class Progress(BaseModel):
    stage: Literal["crawl", "page", "sitewide"] | None = None
    message: str = ""
    done: int = 0
    total: int = 1


class ScanStatus(BaseModel):
    id: str
    url: str
    status: Literal["queued", "running", "done", "error"]
    progress: Progress
    error: str | None


class CriterionView(BaseModel):
    id: str
    name: str
    level: str
    principle: str
    what_to_check: str
    understanding_url: str


class CriterionRow(BaseModel):
    criterion: CriterionView
    status: Status
    methods: list[str]
    fails: int
    reviews: int
    pages_failing: int
    has_issues: bool


class Principle(BaseModel):
    number: int
    name: str
    counts: dict[Status, int]
    criteria: list[CriterionRow]


class InstanceView(BaseModel):
    pages: list[str]
    selector: str | None
    html: str | None
    message: str
    fix: str | None
    viewport: str | None
    confidence: str | None
    source: str


class GroupView(BaseModel):
    rule: str
    title: str
    status: Literal["fail", "review"]
    impact: str | None
    help_url: str | None
    fix: str | None  # shown once for the group (custom checks); axe gives a fix per element
    occurrences: int
    elements: int
    instances: list[InstanceView]


class IssueView(BaseModel):
    criterion: CriterionView
    status: Status
    groups: list[GroupView]


class PageView(BaseModel):
    index: int
    url: str
    title: str
    error: str | None
    fails: int
    reviews: int
    fails_by_principle: dict[str, int]
    reviews_by_principle: dict[str, int]
    failed_criteria: list[str]
    tab_stops: int
    notes: list[str]
    has_screenshot: bool


class Verdict(BaseModel):
    status: Literal["fail", "review", "pass", "error"]
    title: str
    detail: str


class ReportView(BaseModel):
    id: str
    start_url: str
    host: str
    level: str
    ai_enabled: bool
    finished_at: str | None
    axe_version: str
    axe_criteria: int
    notes: list[str]
    verdict: Verdict
    counts: dict[Status, int]
    fail_findings: int
    review_findings: int
    pages_scanned: int
    pages_with_failures: int
    principles: list[Principle]
    pages: list[PageView]
    issues: list[IssueView]


# ---- Building the report view -------------------------------------------------


def build_report(scan: ScanResult, summary: Summary | None = None) -> ReportView:
    s = summary or summarize(scan)
    principles: list[Principle] = []
    for name, rows in groupby(s.criteria, key=lambda r: r.criterion.principle):
        items = list(rows)
        principles.append(
            Principle(
                number=len(principles) + 1,
                name=name,
                counts={
                    st: sum(1 for r in items if r.status == st) for st in ("fail", "review", "pass", "manual", "na")
                },
                criteria=[_row(r) for r in items],
            )
        )
    issues = sorted((r for r in s.criteria if r.groups), key=lambda r: (r.status != "fail", -r.fails, -r.reviews))
    return ReportView(
        id=scan.id,
        start_url=scan.start_url,
        host=urlsplit(scan.start_url).netloc,
        level=scan.level,
        ai_enabled=scan.ai_enabled,
        finished_at=scan.finished_at,
        axe_version=scan.axe_version,
        axe_criteria=len(scan.axe_coverage),
        notes=scan.notes,
        verdict=Verdict(status=s.verdict_status, title=s.verdict, detail=s.verdict_detail),
        counts=s.counts,
        fail_findings=s.total_fail_findings,
        review_findings=s.total_review_findings,
        pages_scanned=s.pages_scanned,
        pages_with_failures=s.pages_with_failures,
        principles=principles,
        pages=[
            PageView(
                index=i,
                url=p.url,
                title=p.title,
                error=p.error,
                fails=p.fails,
                reviews=p.reviews,
                fails_by_principle=p.fails_by_principle,
                reviews_by_principle=p.reviews_by_principle,
                failed_criteria=p.failed_criteria,
                tab_stops=p.tab_stops,
                notes=p.notes,
                has_screenshot=bool(p.screenshot),
            )
            for i, p in enumerate(s.pages)
        ],
        issues=[
            IssueView(criterion=_criterion(r.criterion), status=r.status, groups=[_group(g) for g in r.groups])
            for r in issues
        ],
    )


def _criterion(c: Criterion) -> CriterionView:
    return CriterionView(
        id=c.id, name=c.name, level=c.level, principle=c.principle, what_to_check=c.manual, understanding_url=c.url
    )


def _row(r: CriterionResult) -> CriterionRow:
    return CriterionRow(
        criterion=_criterion(r.criterion),
        status=r.status,
        methods=r.methods,
        fails=r.fails,
        reviews=r.reviews,
        pages_failing=r.pages_failing,
        has_issues=bool(r.groups),
    )


def _group(g: RuleGroup) -> GroupView:
    return GroupView(
        rule=g.rule,
        title=g.title,
        status=g.status,
        impact=g.impact,
        help_url=g.help_url,
        fix=g.fix if g.source not in ("axe", "ai") else None,
        occurrences=len(g.findings),
        elements=len(g.instances),
        instances=[_instance(i) for i in g.instances[:MAX_INSTANCES]],
    )


def _instance(i: Instance) -> InstanceView:
    f = i.finding
    return InstanceView(
        pages=i.pages,
        selector=f.selector,
        html=f.html,
        message=f.message,
        fix=f.fix if f.source in ("axe", "ai") else None,
        viewport=f.viewport,
        confidence=f.confidence,
        source=f.source,
    )


# ---- Endpoints ----------------------------------------------------------------

_running: set[asyncio.Task] = set()
_slots = asyncio.Semaphore(settings.parallel_scans)


def demo_url(request: Request) -> str:
    """The demo's address as the visitor sees it."""
    return f"{request.base_url}demo-site/"


def internal_base(request: Request) -> str:
    """This server's address as its own browser sees it. Behind a port mapping or a reverse proxy the
    visitor's address (e.g. localhost:8011) doesn't exist inside the container, but the socket the
    request arrived on always does."""
    host, port = request.scope.get("server") or ("127.0.0.1", 8000)
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}/"


@router.get("/config")
async def get_config(request: Request) -> Config:
    return Config(max_pages=settings.max_pages, ai_available=ai_available(), demo_url=demo_url(request))


@router.get("/scans")
async def list_scans() -> list[RecentScan]:
    return [RecentScan(**row) for row in storage.recent()]


@router.post("/scans", status_code=201, responses={400: {"model": ApiError}, 429: {"model": ApiError}})
async def create_scan(body: ScanRequest, request: Request) -> ScanCreated:
    url = body.url.strip()
    if url and "://" not in url:
        url = "https://" + url
    # The built-in demo is served by this app, at whatever address the app runs on (which may be
    # a private one, or a name without a dot such as a Docker service), so it skips the address checks.
    is_demo = url.startswith(demo_url(request))
    if not is_demo and not is_scannable(url):
        raise ApiProblem(400, "Enter a full web address, for example https://example.com.", "url")
    pages = (
        body.max_pages
        if isinstance(body.max_pages, int)
        else (int(body.max_pages) if body.max_pages.strip().isdigit() else 0)
    )
    if not 1 <= pages <= settings.max_pages:
        raise ApiProblem(400, f"Choose between 1 and {settings.max_pages} pages.", "max_pages")
    if body.level not in LEVEL_RANK:
        raise ApiProblem(400, "Choose a level of A, AA or AAA.", "level")
    if not is_demo:
        try:
            await HostGuard(allow_private=settings.allow_private).check(url)
        except UnknownHost as e:
            raise ApiProblem(400, f"{e} Check the address for typos.", "url") from e
        except BlockedAddress as e:
            raise ApiProblem(400, str(e), "url") from e
    if storage.active_count() >= settings.max_active:
        raise ApiProblem(429, "Too many scans are running. Please try again in a few minutes.")

    scan_id = uuid.uuid4().hex[:12]
    storage.create(scan_id, url)
    if is_demo:
        url = internal_base(request) + url.removeprefix(str(request.base_url))
    opts = ScanOptions(
        max_pages=pages,
        level=body.level,
        ai=body.ai and ai_available(),
        allow_private=settings.allow_private or is_demo,
    )
    task = asyncio.create_task(_run_scan(scan_id, url, opts))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return ScanCreated(id=scan_id)


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


@router.get("/scans/{scan_id}", responses={404: {"model": ApiError}})
async def get_scan(scan_id: str) -> ScanStatus:
    row = storage.get_status(scan_id) if storage.valid_id(scan_id) else None
    if not row:
        raise ApiProblem(404, "There's no scan with that ID.")
    return ScanStatus(
        id=row["id"], url=row["url"], status=row["status"], progress=Progress(**row["progress"]), error=row["error"]
    )


@router.get("/scans/{scan_id}/report", responses={404: {"model": ApiError}})
async def get_report(scan_id: str) -> ReportView:
    scan = finished_scan(scan_id)
    if not scan:
        raise ApiProblem(404, "This report doesn't exist or isn't finished yet.")
    return build_report(scan)


@router.get("/scans/{scan_id}/pages/{index}/screenshot", response_class=Response, responses={404: {"model": ApiError}})
async def get_screenshot(scan_id: str, index: int) -> Response:
    scan = finished_scan(scan_id)
    if not scan or not 0 <= index < len(scan.pages) or not scan.pages[index].screenshot:
        raise ApiProblem(404, "No screenshot for that page.")
    image = base64.standard_b64decode(scan.pages[index].screenshot or "")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400, immutable"})


def finished_scan(scan_id: str) -> ScanResult | None:
    row = storage.get(scan_id) if storage.valid_id(scan_id) else None
    return row["result"] if row and row["result"] else None


def cancel_running() -> None:
    for task in list(_running):
        task.cancel()


def running_count() -> int:
    return len(_running)

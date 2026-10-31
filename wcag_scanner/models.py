"""Data shapes shared by the scanner, the aggregator and the report."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FindingStatus = Literal["fail", "review"]
Source = Literal["axe", "keyboard", "forms", "layout", "media", "sitewide", "ai"]


class Finding(BaseModel):
    criterion: str  # e.g. "1.4.3"
    status: FindingStatus
    source: Source
    rule: str  # e.g. "color-contrast", "focus-visible"
    message: str
    page: str | None = None  # None for site-wide findings that span pages
    selector: str | None = None
    html: str | None = None
    impact: str | None = None  # critical | serious | moderate | minor
    fix: str | None = None
    help_url: str | None = None
    viewport: str | None = None  # desktop | mobile | desktop+mobile
    confidence: str | None = None  # AI findings only


class PageSignals(BaseModel):
    """Facts gathered on each page that the site-wide checks compare."""

    title: str = ""
    nav_names: list[str] = Field(default_factory=list)
    chrome_links: list[tuple[str, str]] = Field(default_factory=list)  # (href, name) in header/nav/footer
    help: list[str] = Field(default_factory=list)
    has_search: bool = False
    has_sitemap_link: bool = False
    media_count: int = 0


class PageResult(BaseModel):
    url: str
    title: str = ""
    error: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)  # criteria a check actually ran on
    signals: PageSignals = Field(default_factory=PageSignals)
    screenshot: str | None = None  # base64 JPEG with failing elements outlined
    tab_stops: int = 0
    notes: list[str] = Field(default_factory=list)
    seconds: float = 0.0
    timings: dict[str, float] = Field(default_factory=dict)  # seconds per stage, for profiling slow sites


class ScanResult(BaseModel):
    id: str
    start_url: str
    level: str = "AA"
    ai_enabled: bool = False
    started_at: str
    finished_at: str | None = None
    pages: list[PageResult] = Field(default_factory=list)
    sitewide_findings: list[Finding] = Field(default_factory=list)
    sitewide_checked: list[str] = Field(default_factory=list)
    axe_coverage: list[str] = Field(default_factory=list)
    axe_version: str = ""
    notes: list[str] = Field(default_factory=list)

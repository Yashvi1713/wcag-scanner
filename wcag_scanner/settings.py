"""Configuration from environment variables, read in one place."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


@dataclass
class Settings:
    max_pages: int = _int("WCAG_SCANNER_MAX_PAGES", 50)  # largest scan the API accepts
    max_active: int = _int("WCAG_SCANNER_MAX_ACTIVE", 10)  # queued + running scans before answering 429
    parallel_scans: int = _int("WCAG_SCANNER_PARALLEL", 2)  # scans driving browsers at the same time
    allow_private: bool = _flag("WCAG_SCANNER_ALLOW_PRIVATE")  # let the API scan private addresses
    frontend_dist: Path = Path(os.environ.get("WCAG_SCANNER_FRONTEND", ROOT / "frontend" / "dist"))
    demo_site: Path = ROOT / "demo_site"


settings = Settings()

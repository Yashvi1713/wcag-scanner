"""Keep scans in SQLite so reports survive restarts and can be compared later.

A scan's result (with screenshots) can be several MB, so the frequent reads — the progress
poll and the recent-scans list — select only the small columns they need.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import ScanResult

DB_PATH = Path(os.environ.get("WCAG_SCANNER_DB", Path(__file__).parent.parent / "data" / "scans.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued | running | done | error
    created_at TEXT NOT NULL,
    progress TEXT,
    result TEXT,
    error TEXT,
    fails INTEGER,
    pages INTEGER,
    verdict TEXT                   -- fail | review | pass | error, once done
);
CREATE INDEX IF NOT EXISTS scans_created ON scans (created_at DESC);
CREATE INDEX IF NOT EXISTS scans_status ON scans (status);
"""
_MIGRATIONS = {"verdict": "ALTER TABLE scans ADD COLUMN verdict TEXT"}  # columns added after the first release
_ready: set[Path] = set()


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    path = DB_PATH  # read at call time so tests can point it elsewhere
    if path not in _ready:
        _init(path)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # commits, or rolls back on error
            yield conn
    finally:
        conn.close()


def _init(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the scan that is writing progress
        conn.executescript(_SCHEMA)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(scans)")}
        for column, ddl in _MIGRATIONS.items():
            if column not in existing:
                conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()
    _ready.add(path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create(scan_id: str, url: str) -> None:
    with _db() as db:
        db.execute(
            "INSERT INTO scans (id, url, status, created_at, progress) VALUES (?, ?, 'queued', ?, ?)",
            (scan_id, url, _now(), json.dumps({"message": "Waiting to start", "done": 0, "total": 1})),
        )


def set_status(scan_id: str, status: str) -> None:
    with _db() as db:
        db.execute("UPDATE scans SET status = ? WHERE id = ?", (status, scan_id))


def update_progress(scan_id: str, progress: dict) -> None:
    with _db() as db:
        db.execute("UPDATE scans SET progress = ? WHERE id = ?", (json.dumps(progress), scan_id))


def finish(scan_id: str, result: ScanResult, fails: int, verdict: str) -> None:
    with _db() as db:
        db.execute(
            "UPDATE scans SET status = 'done', result = ?, fails = ?, pages = ?, verdict = ? WHERE id = ?",
            (result.model_dump_json(), fails, sum(1 for p in result.pages if not p.error), verdict, scan_id),
        )


def fail(scan_id: str, error: str) -> None:
    with _db() as db:
        db.execute("UPDATE scans SET status = 'error', error = ? WHERE id = ?", (error, scan_id))


def get(scan_id: str) -> dict | None:
    """The whole scan, including the parsed result."""
    with _db() as db:
        row = db.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["progress"] = json.loads(out["progress"]) if out["progress"] else {}
    out["result"] = ScanResult.model_validate_json(out["result"]) if out["result"] else None
    return out


def get_status(scan_id: str) -> dict | None:
    """Just the status and progress: cheap enough to poll every couple of seconds."""
    with _db() as db:
        row = db.execute("SELECT id, url, status, progress, error FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["progress"] = json.loads(out["progress"]) if out["progress"] else {}
    return out


def recent(limit: int = 10) -> list[dict]:
    with _db() as db:
        rows = db.execute(
            "SELECT id, url, status, created_at, fails, pages, verdict FROM scans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def active_count() -> int:
    with _db() as db:
        return db.execute("SELECT COUNT(*) FROM scans WHERE status IN ('queued', 'running')").fetchone()[0]


def recover_interrupted() -> int:
    """Scans that were queued or running when the server stopped will never finish: mark them failed."""
    with _db() as db:
        cur = db.execute(
            "UPDATE scans SET status = 'error', error = ? WHERE status IN ('queued', 'running')",
            ("The server restarted before this scan finished. Please run it again.",),
        )
        return cur.rowcount

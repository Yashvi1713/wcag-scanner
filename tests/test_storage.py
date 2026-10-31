"""Scan history in SQLite: round trips, cheap status reads, migrations and crash recovery."""

import sqlite3

import pytest

from wcag_scanner import storage
from wcag_scanner.models import PageResult, ScanResult


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "scans.db"
    monkeypatch.setattr(storage, "DB_PATH", path)
    return path


def _result(screenshot="x" * 50_000):
    return ScanResult(
        id="abc123def456",
        start_url="https://s.com/",
        started_at="2026-01-01T00:00:00+00:00",
        pages=[
            PageResult(url="https://s.com/", screenshot=screenshot),
            PageResult(url="https://s.com/gone", error="Page not found (HTTP 404)"),
        ],
    )


def test_round_trip(db):
    storage.create("abc123def456", "https://s.com/")
    storage.set_status("abc123def456", "running")
    storage.update_progress("abc123def456", {"stage": "page", "done": 1, "total": 2})
    assert storage.get_status("abc123def456")["progress"]["done"] == 1
    storage.finish("abc123def456", _result(), fails=3, verdict="fail")
    scan = storage.get("abc123def456")
    assert scan["status"] == "done" and scan["result"] == _result()
    recent = storage.recent()[0]
    assert (recent["fails"], recent["pages"], recent["verdict"]) == (3, 1, "fail")  # only pages that loaded


def test_status_reads_skip_the_heavy_result(db):
    storage.create("abc123def456", "https://s.com/")
    storage.finish("abc123def456", _result(), fails=0, verdict="pass")
    status = storage.get_status("abc123def456")
    assert "result" not in status
    assert status["status"] == "done"


def test_missing_scans(db):
    assert storage.get("nope") is None
    assert storage.get_status("nope") is None


def test_interrupted_scans_are_marked_failed_on_restart(db):
    for scan_id, status in (("q", "queued"), ("r", "running"), ("d", "done")):
        storage.create(scan_id, "https://s.com/")
        storage.set_status(scan_id, status)
    assert storage.active_count() == 2
    assert storage.recover_interrupted() == 2
    assert storage.active_count() == 0
    assert storage.get_status("r")["status"] == "error"
    assert "restarted" in storage.get_status("q")["error"]
    assert storage.get_status("d")["status"] == "done"


def test_a_database_from_the_first_release_is_migrated(db):
    old = sqlite3.connect(db)
    old.execute(
        "CREATE TABLE scans (id TEXT PRIMARY KEY, url TEXT NOT NULL, status TEXT NOT NULL, "
        "created_at TEXT NOT NULL, progress TEXT, result TEXT, error TEXT, fails INTEGER, pages INTEGER)"
    )
    old.execute("INSERT INTO scans (id, url, status, created_at) VALUES ('old', 'https://s.com/', 'done', '2026')")
    old.commit()
    old.close()
    storage._ready.discard(db)
    assert storage.recent()[0]["verdict"] is None  # old rows survive, new column added
    storage.create("new", "https://s.com/")
    storage.finish("new", _result(), fails=0, verdict="pass")
    assert storage.get_status("new")["status"] == "done"


def test_wal_mode_lets_readers_and_the_writer_overlap(db):
    storage.create("abc123def456", "https://s.com/")
    mode = sqlite3.connect(db).execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_a_failed_write_is_rolled_back(db):
    storage.create("abc123def456", "https://s.com/")
    with pytest.raises(sqlite3.IntegrityError):
        storage.create("abc123def456", "https://s.com/")  # duplicate id
    assert len(storage.recent()) == 1

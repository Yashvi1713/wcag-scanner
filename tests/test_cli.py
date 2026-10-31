"""The command line: arguments, outputs and the exit codes a CI pipeline relies on."""

import asyncio
import json

import pytest

from wcag_scanner import __main__ as cli
from wcag_scanner.models import Finding, PageResult, ScanResult


@pytest.mark.parametrize(
    ("verdict", "fail_on", "code"),
    [
        ("fail", "fail", 1),
        ("review", "fail", 0),
        ("pass", "fail", 0),
        ("fail", "review", 1),
        ("review", "review", 1),
        ("pass", "review", 0),
        ("fail", "never", 0),
        ("review", "never", 0),
        ("error", "fail", 2),
        ("error", "review", 2),
        ("error", "never", 2),  # unscannable is never silently OK
    ],
)
def test_exit_codes(verdict, fail_on, code):
    assert cli.exit_code(verdict, fail_on) == code


@pytest.mark.parametrize(
    "argv",
    [
        ["scan", "https://s.com", "--pages", "0"],
        ["scan", "https://s.com", "--pages", "lots"],
        ["scan", "https://s.com", "--level", "AAAA"],
        ["scan", "https://s.com", "--fail-on", "sometimes"],
        [],
    ],
)
def test_bad_arguments_are_rejected(argv):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(argv)
    assert e.value.code == 2


def _result(url, error=None):
    page = (
        PageResult(url=url, error=error)
        if error
        else PageResult(
            url=url,
            checked=["1.1.1"],
            screenshot="eA==",
            findings=[Finding(criterion="1.1.1", status="fail", source="axe", rule="image-alt", message="m", page=url)],
        )
    )
    return ScanResult(id="t", start_url=url, started_at="2026-01-01T00:00:00+00:00", pages=[page])


def test_scan_writes_reports_and_fails_the_build(tmp_path, monkeypatch, capsys):
    seen = {}

    async def fake_scan(url, opts, progress):
        seen["opts"] = opts
        return _result(url)

    monkeypatch.setattr(cli, "scan_site", fake_scan)
    args = cli.build_parser().parse_args(
        [
            "scan",
            "https://s.com",
            "--pages",
            "7",
            "--max-minutes",
            "2",
            "--out",
            str(tmp_path / "r.html"),
            "--json",
            str(tmp_path / "r.json"),
        ]
    )
    assert asyncio.run(cli.run_scan(args)) == 1
    assert seen["opts"].max_pages == 7 and seen["opts"].scan_timeout == 120
    assert "Does not meet WCAG 2.2 Level AA" in (tmp_path / "r.html").read_text()
    data = json.loads((tmp_path / "r.json").read_text())
    assert "screenshot" not in data["pages"][0]
    assert "1.1.1" in capsys.readouterr().out


def test_an_unreachable_site_exits_2(tmp_path, monkeypatch, capsys):
    async def fake_scan(url, opts, progress):
        return _result(url, error="Couldn't find a website at s.invalid.")

    monkeypatch.setattr(cli, "scan_site", fake_scan)
    args = cli.build_parser().parse_args(["scan", "https://s.invalid", "--out", str(tmp_path / "r.html")])
    assert asyncio.run(cli.run_scan(args)) == 2
    out = capsys.readouterr().out
    assert "could not be scanned" in out and "skipped https://s.invalid" in out

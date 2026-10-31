"""The web app end to end, with the browser-driven scan replaced by a fast fake."""

import ipaddress
import time

import pytest
from fastapi.testclient import TestClient

from wcag_scanner import netguard, storage, web
from wcag_scanner.models import Finding, PageResult, ScanResult

PUBLIC = {"example.com", "testserver"}  # names the fake DNS answers with a public address


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "scans.db")

    async def resolve(host):
        if host in PUBLIC:
            return {ipaddress.ip_address("93.184.215.14")}
        if host in ("localhost", "127.0.0.1"):
            return {ipaddress.ip_address("127.0.0.1")}
        raise netguard.UnknownHost(f"Couldn't find a website at {host}.")

    monkeypatch.setattr(netguard, "resolve", resolve)
    monkeypatch.setattr(web, "scan_site", _fake_scan)
    web._pdf_cache.clear()
    with TestClient(web.app) as c:
        yield c


async def _fake_scan(url, opts, progress=None, scan_id=None):
    progress({"stage": "page", "message": f"Scanning {url}", "done": 0, "total": 1})
    finding = Finding(
        criterion="1.1.1",
        status="fail",
        source="axe",
        rule="image-alt",
        message="Images need alt",
        page=url,
        selector="img",
        html="<img src=x>",
    )
    return ScanResult(
        id=scan_id,
        start_url=url,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:01:00+00:00",
        axe_version="4.10.3",
        pages=[PageResult(url=url, title="Home", checked=["1.1.1"], findings=[finding], screenshot="c2NyZWVuc2hvdA==")],
    )


def _start(client, url="https://example.com", **form):
    return client.post("/scans", data={"url": url, "max_pages": "5", "level": "AA", **form}, follow_redirects=False)


def _wait(client, scan_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/scans/{scan_id}/status").json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_home_page_and_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "Can everyone use this website?" in r.text
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_health_check(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_full_flow_from_form_to_downloads(client, monkeypatch):
    r = _start(client, "example.com")  # no scheme: https:// is assumed
    assert r.status_code == 303
    scan_id = r.headers["location"].rsplit("/", 1)[1]
    assert _wait(client, scan_id)["status"] == "done"

    report = client.get(f"/scans/{scan_id}")
    assert report.status_code == 200 and "Does not meet WCAG 2.2 Level AA" in report.text

    data = client.get(f"/scans/{scan_id}/report.json")
    assert data.headers["content-disposition"] == f'attachment; filename="wcag-report-{scan_id}.json"'
    assert data.json()["start_url"] == "https://example.com"
    assert "screenshot" not in data.json()["pages"][0]  # the JSON export stays small

    standalone = client.get(f"/scans/{scan_id}/report.html")
    assert standalone.status_code == 200 and 'href="/scans/' not in standalone.text  # works offline

    renders = []

    async def fake_pdf(html):
        renders.append(html)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(web, "render_pdf", fake_pdf)
    for _ in range(3):
        pdf = client.get(f"/scans/{scan_id}/report.pdf")
        assert pdf.content == b"%PDF-1.7 fake" and pdf.headers["content-type"] == "application/pdf"
    assert len(renders) == 1  # finished reports never change, so the PDF is rendered once

    assert "1 criteria fail" in client.get("/").text


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"url": "not a url"}, "Enter a full web address"),
        ({"url": ""}, "Enter a full web address"),
        ({"max_pages": "abc"}, "between 1 and 50 pages"),
        ({"max_pages": "0"}, "between 1 and 50 pages"),
        ({"max_pages": "51"}, "between 1 and 50 pages"),
        ({"max_pages": "-3"}, "between 1 and 50 pages"),
        ({"level": "AAAA"}, "Choose a level of A, AA or AAA"),
        ({"url": "https://no-such-site.invalid"}, "find a website at no-such-site.invalid"),
        ({"url": "http://localhost:5432/"}, "private network address"),
        ({"url": "http://127.0.0.1/admin"}, "private network address"),
    ],
)
def test_bad_input_gets_an_accessible_error_not_a_crash(client, form, message):
    r = _start(client, **{"url": "https://example.com", **form})
    assert r.status_code == 400
    assert message in r.text
    assert 'role="alert"' in r.text and 'aria-invalid="true"' in r.text


def test_the_built_in_demo_is_the_one_local_address_allowed(client, monkeypatch):
    seen = []

    async def record(url, opts, progress=None, scan_id=None):
        seen.append((url, opts.allow_private))
        return await _fake_scan(url, opts, progress, scan_id)

    monkeypatch.setattr(web, "scan_site", record)
    scan_id = _start(client, "http://testserver/demo-site/").headers["location"].rsplit("/", 1)[1]
    _wait(client, scan_id)
    # Scanned at the address the request arrived on, which the server's own browser can always reach
    # (the visitor's address may be a port mapping or proxy that doesn't exist inside a container).
    assert seen == [("http://testserver:80/demo-site/", True)]


def test_operators_can_allow_private_addresses(client, monkeypatch):
    monkeypatch.setattr(web, "ALLOW_PRIVATE", True)
    assert _start(client, "http://localhost:8080/").status_code == 303


def test_busy_server_says_so(client, monkeypatch):
    monkeypatch.setattr(web, "MAX_ACTIVE", 0)
    r = _start(client)
    assert r.status_code == 429 and "The scanner is busy" in r.text


def test_a_crashing_scan_is_reported_not_lost(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("chromium exploded")

    monkeypatch.setattr(web, "scan_site", boom)
    scan_id = _start(client).headers["location"].rsplit("/", 1)[1]
    assert _wait(client, scan_id)["status"] == "error"
    page = client.get(f"/scans/{scan_id}")
    assert page.status_code == 500 and "chromium exploded" in page.text


def test_unscannable_sites_are_labelled_honestly(client):
    storage.create("aaaaaaaaaaaa", "https://example.com")
    result = ScanResult(
        id="aaaaaaaaaaaa",
        start_url="https://example.com",
        started_at="2026-01-01T00:00:00+00:00",
        pages=[PageResult(url="https://example.com", error="Blocked by bot protection (HTTP 403)")],
    )
    storage.finish("aaaaaaaaaaaa", result, fails=0, verdict="error")
    assert "Couldn't scan" in client.get("/").text
    assert "The site could not be scanned" in client.get("/scans/aaaaaaaaaaaa").text


@pytest.mark.parametrize(
    "path",
    [
        "/scans/doesnotexist",
        "/scans/0123456789ab",
        "/scans/../../etc/passwd",
    ],
)
def test_unknown_scans_are_404(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("ext", ["json", "html", "pdf"])
def test_downloads_of_unfinished_scans_are_404(client, ext):
    storage.create("bbbbbbbbbbbb", "https://example.com")
    r = client.get(f"/scans/bbbbbbbbbbbb/report.{ext}")
    assert r.status_code == 404 and "isn't finished" in r.json()["error"]


def test_progress_page_while_running(client):
    storage.create("cccccccccccc", "https://example.com")
    storage.update_progress(
        "cccccccccccc", {"stage": "page", "message": "Scanning https://example.com/a", "done": 3, "total": 10}
    )
    r = client.get("/scans/cccccccccccc")
    assert r.status_code == 200 and "30%" in r.text and 'role="status"' in r.text
    assert client.get("/scans/cccccccccccc/status").json()["progress"]["done"] == 3


def test_scans_interrupted_by_a_restart_are_marked_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "scans.db")
    storage.create("dddddddddddd", "https://example.com")
    storage.set_status("dddddddddddd", "running")
    with TestClient(web.app):  # startup runs the recovery
        pass
    assert storage.get_status("dddddddddddd")["status"] == "error"

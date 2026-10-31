"""The JSON API and the downloads, end to end, with the browser-driven scan replaced by a fast fake."""

import ipaddress
import time

import pytest
from fastapi.testclient import TestClient

from wcag_scanner import api, netguard, storage, web
from wcag_scanner.models import Finding, PageResult, ScanResult
from wcag_scanner.settings import settings

PUBLIC = {"example.com"}  # names the fake DNS answers with a public address


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "scans.db")

    async def resolve(host):
        try:
            return {ipaddress.ip_address(host.strip("[]"))}  # like the real resolver: IP literals need no DNS
        except ValueError:
            pass
        if host in PUBLIC:
            return {ipaddress.ip_address("93.184.215.14")}
        if host in ("localhost", "127.0.0.1"):
            return {ipaddress.ip_address("127.0.0.1")}
        raise netguard.UnknownHost(f"Couldn't find a website at {host}.")

    monkeypatch.setattr(netguard, "resolve", resolve)
    monkeypatch.setattr(api, "scan_site", _fake_scan)
    web._pdf_cache.clear()
    with TestClient(web.app) as c:
        yield c


async def _fake_scan(url, opts, progress=None, scan_id=None):
    progress({"stage": "page", "message": f"Scanning {url}", "done": 0, "total": 1})
    finding = Finding(criterion="1.1.1", status="fail", source="axe", rule="image-alt", message="Images need alt",
                      page=url, selector="img", html="<img src=x>", fix="Add an alt attribute")  # fmt: skip
    return ScanResult(
        id=scan_id, start_url=url, started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:01:00+00:00",
        axe_version="4.10.3", axe_coverage=["1.1.1"],
        pages=[PageResult(url=url, title="Home", checked=["1.1.1"], findings=[finding], screenshot="c2NyZWVuc2hvdA==")],
    )  # fmt: skip


def _start(client, **body):
    return client.post("/api/scans", json={"url": "https://example.com", "max_pages": 5, "level": "AA", **body})


def _wait(client, scan_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/api/scans/{scan_id}").json()
        if status["status"] in ("done", "error"):
            return status
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_config_and_security_headers(client):
    r = client.get("/api/config")
    body = r.json()
    assert body["max_pages"] == settings.max_pages and body["demo_url"] == "http://testserver/demo-site/"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_health_check(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_full_flow_from_request_to_report_and_downloads(client, monkeypatch):
    r = _start(client, url="example.com")  # no scheme: https:// is assumed
    assert r.status_code == 201
    scan_id = r.json()["id"]
    assert _wait(client, scan_id)["status"] == "done"

    report = client.get(f"/api/scans/{scan_id}/report").json()
    assert report["verdict"]["status"] == "fail"
    assert report["verdict"]["title"] == "Does not meet WCAG 2.2 Level AA"
    assert report["counts"]["fail"] == 1 and sum(report["counts"].values()) == 55
    assert [p["number"] for p in report["principles"]] == [1, 2, 3, 4]
    issue = report["issues"][0]
    assert issue["criterion"]["id"] == "1.1.1" and issue["groups"][0]["instances"][0]["fix"] == "Add an alt attribute"
    assert report["pages"][0]["has_screenshot"] is True

    shot = client.get(f"/api/scans/{scan_id}/pages/0/screenshot")
    assert shot.headers["content-type"] == "image/jpeg" and shot.content == b"screenshot"
    assert client.get(f"/api/scans/{scan_id}/pages/9/screenshot").status_code == 404

    data = client.get(f"/scans/{scan_id}/report.json")
    assert data.headers["content-disposition"] == f'attachment; filename="wcag-report-{scan_id}.json"'
    assert "screenshot" not in data.json()["pages"][0]  # the JSON export stays small

    html = client.get(f"/scans/{scan_id}/report.html")
    assert html.status_code == 200 and "Does not meet WCAG 2.2 Level AA" in html.text
    assert 'href="/' not in html.text  # a self-contained document: no links back into the app

    renders = []

    async def fake_pdf(document):
        renders.append(document)
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(web, "render_pdf", fake_pdf)
    for _ in range(3):
        pdf = client.get(f"/scans/{scan_id}/report.pdf")
        assert pdf.content == b"%PDF-1.7 fake" and pdf.headers["content-type"] == "application/pdf"
    assert len(renders) == 1  # finished reports never change, so the PDF is rendered once

    recent = client.get("/api/scans").json()
    assert recent[0]["id"] == scan_id and recent[0]["fails"] == 1 and recent[0]["verdict"] == "fail"


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"url": "not a url"}, "url", "Enter a full web address"),
        ({"url": ""}, "url", "Enter a full web address"),
        ({"max_pages": "abc"}, "max_pages", "between 1 and 50 pages"),
        ({"max_pages": 0}, "max_pages", "between 1 and 50 pages"),
        ({"max_pages": 51}, "max_pages", "between 1 and 50 pages"),
        ({"max_pages": "-3"}, "max_pages", "between 1 and 50 pages"),
        ({"level": "AAAA"}, "level", "Choose a level of A, AA or AAA"),
        ({"url": "https://no-such-site.invalid"}, "url", "Couldn't find a website at no-such-site.invalid"),
        ({"url": "http://localhost:5432/"}, "url", "private network address"),
        ({"url": "http://169.254.169.254/latest/meta-data/"}, "url", "private network address"),
    ],
)
def test_bad_requests_name_the_field_to_fix(client, body, field, message):
    r = _start(client, **body)
    assert r.status_code == 400
    assert r.json()["field"] == field
    assert message in r.json()["error"]


def test_the_built_in_demo_is_the_one_local_address_allowed(client, monkeypatch):
    seen = []

    async def record(url, opts, progress=None, scan_id=None):
        seen.append((url, opts.allow_private))
        return await _fake_scan(url, opts, progress, scan_id)

    monkeypatch.setattr(api, "scan_site", record)
    scan_id = _start(client, url="http://testserver/demo-site/").json()["id"]
    _wait(client, scan_id)
    # Scanned at the address the request arrived on, which the server's own browser can always reach
    # (the visitor's address may be a port mapping or proxy that doesn't exist inside a container).
    assert seen == [("http://testserver:80/demo-site/", True)]


def test_operators_can_allow_private_addresses(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_private", True)
    assert _start(client, url="http://localhost:8080/").status_code == 201


def test_busy_server_says_so(client, monkeypatch):
    monkeypatch.setattr(settings, "max_active", 0)
    r = _start(client)
    assert r.status_code == 429 and "Too many scans" in r.json()["error"]


def test_a_crashing_scan_is_reported_not_lost(client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("chromium exploded")

    monkeypatch.setattr(api, "scan_site", boom)
    scan_id = _start(client).json()["id"]
    status = _wait(client, scan_id)
    assert status["status"] == "error" and "chromium exploded" in status["error"]


def test_unscannable_sites_are_labelled_honestly(client):
    storage.create("aaaaaaaaaaaa", "https://example.com")
    result = ScanResult(id="aaaaaaaaaaaa", start_url="https://example.com", started_at="2026-01-01T00:00:00+00:00",
                        pages=[PageResult(url="https://example.com", error="Blocked by bot protection (HTTP 403)")])  # fmt: skip
    storage.finish("aaaaaaaaaaaa", result, fails=0, verdict="error")
    assert client.get("/api/scans").json()[0]["verdict"] == "error"
    report = client.get("/api/scans/aaaaaaaaaaaa/report").json()
    assert report["verdict"]["status"] == "error" and report["counts"]["pass"] == 0


@pytest.mark.parametrize("scan_id", ["doesnotexist", "0123456789ab", "..%2F..%2Fetc"])
def test_unknown_scans_are_404(client, scan_id):
    r = client.get(f"/api/scans/{scan_id}")
    assert r.status_code == 404 and r.json()["error"]  # a JSON error, never the app or a stack trace


@pytest.mark.parametrize("path", ["/api/scans/bbbbbbbbbbbb/report", "/scans/bbbbbbbbbbbb/report.json",
                                  "/scans/bbbbbbbbbbbb/report.html", "/scans/bbbbbbbbbbbb/report.pdf"])  # fmt: skip
def test_unfinished_reports_are_404(client, path):
    storage.create("bbbbbbbbbbbb", "https://example.com")
    r = client.get(path)
    assert r.status_code == 404 and "isn't finished" in r.json()["error"]


def test_progress_while_running(client):
    storage.create("cccccccccccc", "https://example.com")
    progress = {"stage": "page", "message": "Scanning https://example.com/a", "done": 3, "total": 10}
    storage.update_progress("cccccccccccc", progress)
    status = client.get("/api/scans/cccccccccccc").json()
    assert status["status"] == "queued" and status["progress"] == progress


def test_react_app_is_served_for_client_side_routes(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    monkeypatch.setattr(settings, "frontend_dist", dist)
    for path in ("/", "/scans/abc123def456", "/anything/else"):
        r = client.get(path)
        assert r.status_code == 200 and "<title>app</title>" in r.text and r.headers["cache-control"] == "no-cache"
    assert client.get("/api/nope").status_code == 404  # unknown API paths are JSON 404s, not the app


def test_a_missing_build_explains_itself(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frontend_dist", tmp_path / "not-built")
    r = client.get("/")
    assert r.status_code == 503 and "npm ci" in r.text


def test_scans_interrupted_by_a_restart_are_marked_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "scans.db")
    storage.create("dddddddddddd", "https://example.com")
    storage.set_status("dddddddddddd", "running")
    with TestClient(web.app):  # startup runs the recovery
        pass
    assert storage.get_status("dddddddddddd")["status"] == "error"


def test_api_is_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/config", "/api/scans", "/api/scans/{scan_id}", "/api/scans/{scan_id}/report"} <= set(paths)

import asyncio
import functools
import http.server
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from wcag_scanner.scanner import ScanOptions, scan_site

ROOT = Path(__file__).parent.parent

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title></head>
<body><main><h1>{title}</h1>{body}</main></body></html>"""

# Real-world situations the scanner must handle, served under /_t/.
# path -> (status, extra headers, content type, body)
ROUTES: dict[str, tuple[int, dict[str, str], str, str]] = {
    "/_t/ok": (200, {}, "text/html", _PAGE.format(title="A fine page", body="<p>Nothing wrong here.</p>")),
    "/_t/notfound": (404, {}, "text/html", _PAGE.format(title="Not found", body="<p>Gone.</p>")),
    "/_t/login": (401, {"WWW-Authenticate": 'Basic realm="x"'}, "text/html", _PAGE.format(title="Log in", body="")),
    "/_t/cloudflare": (
        403,
        {"Server": "cloudflare", "cf-mitigated": "challenge"},
        "text/html",
        _PAGE.format(title="Attention Required! | Cloudflare", body=""),
    ),
    "/_t/challenge": (
        200,
        {},
        "text/html",
        _PAGE.format(title="Just a moment...", body="<p>Checking your browser</p>"),
    ),
    "/_t/text": (200, {}, "text/plain", "just some text"),
    "/_t/servererror": (500, {}, "text/html", _PAGE.format(title="Oops", body="")),
    # Locks up the page's JavaScript thread a moment after it loads, like a runaway script.
    "/_t/hang": (
        200,
        {},
        "text/html",
        _PAGE.format(
            title="Runaway script", body="<p>Busy.</p><script>setTimeout(() => { for (;;) {} }, 300)</script>"
        ),
    ),
}
ROUTES["/_t/hub"] = (
    200,
    {},
    "text/html",
    _PAGE.format(title="Hub", body="<ul>" + "".join(f'<li><a href="{p}">{p}</a></li>' for p in ROUTES) + "</ul>"),
)


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/_t/redirect":  # /_t/redirect?to=<absolute url>
            self.send_response(302)
            self.send_header("Location", parse_qs(parts.query)["to"][0])
            self.end_headers()
            return
        if parts.path in ROUTES:
            status, headers, ctype, body = ROUTES[parts.path]
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def server():
    """Serve the project folder (demo_site/, tests/fixtures/) plus the /_t/ routes above."""
    handler = functools.partial(_Handler, directory=str(ROOT))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="session")
def demo_scan(server):
    return asyncio.run(scan_site(f"{server}/demo_site/", ScanOptions(max_pages=5)))


@pytest.fixture(scope="session")
def accessible_scan(server):
    return asyncio.run(scan_site(f"{server}/tests/fixtures/accessible.html", ScanOptions(max_pages=1)))

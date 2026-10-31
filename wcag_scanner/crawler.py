"""Decide which pages of a site to scan: same site, allowed by robots.txt, HTML only."""

from __future__ import annotations

import re
from collections import Counter, deque
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

from .netguard import HostGuard

USER_AGENT_TOKEN = "WCAGScanner"
MAX_QUERY_VARIANTS = 3  # /search?q=a, /search?q=b, ... are usually the same template: scan a few, not all
MAX_SITEMAP_URLS = 300
# Parameters that only track where a visitor came from; they never change the page.
TRACKING_PARAM = re.compile(r"^(utm_\w+|fbclid|gclid|dclid|msclkid|mc_[ce]id|_ga|_gl|ref|ref_src|igshid|yclid)$", re.I)
SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|avif|ico|zip|gz|docx?|xlsx?|pptx?|csv|mp4|mp3|mov|avi|webm|css|js|xml|json|"
    r"woff2?|ttf|eot|rss|atom|txt)$",
    re.I,
)


def normalize(url: str) -> str | None:
    """One canonical spelling per page, so the same page is never scanned twice."""
    url = urldefrag(url.strip())[0]
    try:
        parts = urlsplit(url)
        port = parts.port  # raises ValueError for an out-of-range port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"  # IPv6 literal
    else:
        try:
            host = host.encode("idna").decode("ascii")  # bücher.de -> xn--bcher-kva.de
        except UnicodeError:
            return None
    if port and port != {"http": 80, "https": 443}[scheme]:
        host = f"{host}:{port}"
    path = _INDEX_FILE.sub("/", parts.path) or "/"  # /about/index.html is the same page as /about/
    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAM.match(k))
    )
    return urlunsplit((scheme, host, path, query, ""))


_INDEX_FILE = re.compile(r"/(index|default)\.(html?|php|aspx?)$", re.I)
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?$")


def is_scannable(url: str) -> bool:
    """A real http(s) address: a host with a dot (or localhost) and no spaces."""
    n = normalize(url)
    if not n:
        return False
    host = urlsplit(n).netloc
    name = host.split(":")[0]
    return bool(_HOST.match(host)) and ("." in name or name == "localhost")


def host_key(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


class Frontier:
    """The ordered list of pages to scan, capped at max_pages."""

    def __init__(self, start_url: str, max_pages: int, guard: HostGuard | None = None):
        start = normalize(start_url)
        if not start:
            raise ValueError(f"Not a valid http(s) URL: {start_url}")
        self.start = start
        self.host = host_key(start)
        # Stay inside the starting folder: /docs/intro.html scans /docs/..., / scans the whole site.
        self.scope = urlsplit(start).path.rsplit("/", 1)[0] + "/"
        self.max_pages = max_pages
        self.queue: deque[str] = deque()
        self.planned: list[str] = []
        self.robots: RobotFileParser | None = None
        self.sitemap_urls: list[str] = []
        self.guard = guard or HostGuard(allow_private=True)
        self._variants: Counter[str] = Counter()  # path -> how many query-string variants are planned
        self.queue.append(start)
        self.planned.append(start)
        self._planned_set = {start}

    async def prepare(self, transport: httpx.AsyncBaseTransport | None = None) -> list[str]:
        """Read robots.txt and sitemap.xml. Returns notes for the report."""
        notes = []
        root = f"{urlsplit(self.start).scheme}://{urlsplit(self.start).netloc}"
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=10,
            max_redirects=5,
            headers={"User-Agent": f"{USER_AGENT_TOKEN}/1.0"},
            event_hooks={"request": [self.guard.httpx_hook()]},
            transport=transport,  # injectable so tests can serve robots.txt and sitemaps without a network
        ) as client:
            sitemaps = [root + "/sitemap.xml"]
            try:
                r = await client.get(root + "/robots.txt")
                if r.status_code == 200:
                    self.robots = RobotFileParser()
                    self.robots.parse(r.text.splitlines())
                    sitemaps = self.robots.site_maps() or sitemaps
                    notes.append("Respected robots.txt.")
            except (httpx.HTTPError, ValueError):  # ValueError: blocked or unknown host
                pass
            for sm in sitemaps[:3]:
                self.sitemap_urls += await _read_sitemap(client, sm, depth=0)
        if self.sitemap_urls:
            notes.append(f"Found {len(self.sitemap_urls)} URLs in the sitemap.")
        return notes

    def allowed(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(USER_AGENT_TOKEN, url)

    def set_origin(self, final_url: str) -> None:
        """Follow the start page's redirect (e.g. example.com -> www.example.com)."""
        self.host = host_key(final_url)

    def offer(self, url: str) -> bool:
        n = normalize(url)
        if not n or n in self._planned_set or len(self.planned) >= self.max_pages:
            return False
        parts = urlsplit(n)
        if (
            host_key(n) != self.host
            or not parts.path.startswith(self.scope)
            or SKIP_EXTENSIONS.search(parts.path)
            or not self.allowed(n)
        ):
            return False
        if parts.query:
            if self._variants[parts.path] >= MAX_QUERY_VARIANTS:
                return False
            self._variants[parts.path] += 1
        self.planned.append(n)
        self._planned_set.add(n)
        self.queue.append(n)
        return True

    def fill_from_sitemap(self) -> None:
        for url in self.sitemap_urls:
            if len(self.planned) >= self.max_pages:
                break
            self.offer(url)

    def take_wave(self) -> list[str]:
        wave = list(self.queue)
        self.queue.clear()
        return wave


async def _read_sitemap(client: httpx.AsyncClient, url: str, depth: int) -> list[str]:
    try:
        r = await client.get(url)
    except (httpx.HTTPError, ValueError):
        return []
    if r.status_code != 200 or "<" not in r.text[:200]:
        return []
    locs = [urljoin(url, m.strip()) for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text, re.S)][:MAX_SITEMAP_URLS]
    if "<sitemapindex" in r.text and depth == 0:
        out: list[str] = []
        for child in locs[:3]:
            out += await _read_sitemap(client, child, depth + 1)
        return out
    return locs

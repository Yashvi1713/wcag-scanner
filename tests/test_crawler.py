"""Which pages get scanned: URL canonicalisation, scope, robots.txt, sitemaps and crawl traps."""

import asyncio

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from wcag_scanner.crawler import MAX_QUERY_VARIANTS, Frontier, is_scannable, normalize
from wcag_scanner.netguard import HostGuard


class _NoDNS(HostGuard):
    """Unit tests mustn't depend on real DNS."""

    async def _reason(self, host):
        return None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.COM/a", "https://example.com/a"),
        ("HTTPS://example.com", "https://example.com/"),
        ("https://example.com/a#section", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),  # default port dropped
        ("http://example.com:80/", "http://example.com/"),
        ("http://example.com:8080/", "http://example.com:8080/"),  # other ports kept
        ("https://example.com/about/index.html", "https://example.com/about/"),
        ("https://example.com/default.aspx", "https://example.com/"),
        ("https://example.com/s?b=2&a=1", "https://example.com/s?a=1&b=2"),  # parameter order doesn't matter
        ("https://example.com/p?utm_source=x&id=7&fbclid=y&gclid=z", "https://example.com/p?id=7"),
        ("https://example.com/p?utm_campaign=x", "https://example.com/p"),
        ("https://bücher.de/", "https://xn--bcher-kva.de/"),  # internationalised domain
        ("http://[::1]:8000/x", "http://[::1]:8000/x"),
        ("  https://example.com/  ", "https://example.com/"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "mailto:a@b.com",
        "javascript:alert(1)",
        "tel:+15550100",
        "ftp://example.com/",
        "/relative/path",
        "https://",
        "https://example.com:99999/",
        "https://exa..mple.com/",
        "",
    ],
)
def test_normalize_rejects_what_is_not_a_web_page(raw):
    assert normalize(raw) is None


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://example.com", True),
        ("http://localhost:8000/", True),
        ("https://sub.example.co.uk/x", True),
        ("https://not a url", False),
        ("https://nodot", False),
        ("example.com", False),
        ("https://-bad-.com", False),
    ],
)
def test_is_scannable(url, ok):
    assert is_scannable(url) is ok


_label = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,10}[a-z0-9])?", fullmatch=True)
_urls = st.builds(
    lambda scheme, host, tld, path, query, frag: f"{scheme}://{host}.{tld}/{path}{query}{frag}",
    st.sampled_from(["http", "https", "HTTP"]),
    _label,
    st.sampled_from(["com", "org", "co.uk"]),
    st.text(alphabet="abcdefghij/-_.~%20", max_size=30),
    st.one_of(st.just(""), st.builds(lambda k, v: f"?{k}={v}", _label, st.text("abc123", max_size=5))),
    st.one_of(st.just(""), st.just("#frag")),
)


@given(_urls)
def test_normalize_is_idempotent(url):
    once = normalize(url)
    assert once is None or normalize(once) == once


@given(st.text(max_size=200))
def test_normalize_never_raises(text):
    normalize(text)  # crawled links are arbitrary text; a bad one must be skipped, not crash the scan


def test_query_string_variants_are_capped():
    f = Frontier("https://s.com/", max_pages=50)
    accepted = [f.offer(f"https://s.com/search?q={i}") for i in range(10)]
    assert sum(accepted) == MAX_QUERY_VARIANTS
    assert f.offer("https://s.com/other?id=1")  # a different path has its own allowance


def test_tracking_parameters_do_not_create_duplicates():
    f = Frontier("https://s.com/", max_pages=50)
    assert f.offer("https://s.com/a?utm_source=newsletter")
    assert not f.offer("https://s.com/a")
    assert not f.offer("https://s.com/a?fbclid=123")


def test_max_pages_is_a_hard_cap():
    f = Frontier("https://s.com/", max_pages=3)
    assert [f.offer(f"https://s.com/p{i}") for i in range(5)] == [True, True, False, False, False]
    assert len(f.planned) == 3


def test_scope_assets_and_other_sites():
    f = Frontier("https://s.com/docs/intro.html", max_pages=10)
    assert f.offer("https://s.com/docs/setup.html")
    assert not f.offer("https://s.com/blog/post.html")  # outside the starting folder
    assert not f.offer("https://other.com/docs/x.html")  # another site
    assert not f.offer("https://s.com/docs/manual.pdf")  # not a web page
    assert not f.offer("https://s.com/docs/setup.html")  # already planned
    assert Frontier("https://s.com/", max_pages=10).offer("https://www.s.com/blog/post.html")  # www is the same site


def test_redirected_start_moves_the_site():
    f = Frontier("https://s.com/", max_pages=10)
    f.set_origin("https://www.s-new.com/")
    assert f.offer("https://s-new.com/about")
    assert not f.offer("https://s.com/about")


def _site(routes):
    def handler(request):
        body = routes.get(request.url.path)
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)

    return httpx.MockTransport(handler)


def test_robots_txt_and_sitemap_index_are_followed():
    routes = {
        "/robots.txt": "User-agent: *\nDisallow: /private/\nSitemap: https://s.com/sitemap-index.xml\n",
        "/sitemap-index.xml": "<sitemapindex><sitemap><loc>https://s.com/pages.xml</loc></sitemap></sitemapindex>",
        "/pages.xml": "<urlset>"
        + "".join(f"<url><loc>https://s.com/{p}</loc></url>" for p in ("a", "private/secret", "b", "c.pdf"))
        + "</urlset>",
    }
    f = Frontier("https://s.com/", max_pages=10, guard=_NoDNS())
    notes = asyncio.run(f.prepare(transport=_site(routes)))
    assert "Respected robots.txt." in notes
    f.fill_from_sitemap()
    assert f.planned == ["https://s.com/", "https://s.com/a", "https://s.com/b"]


def test_missing_or_broken_robots_and_sitemap_are_harmless():
    f = Frontier("https://s.com/", max_pages=10, guard=_NoDNS())
    notes = asyncio.run(f.prepare(transport=_site({"/sitemap.xml": "this is not xml"})))
    assert notes == []
    assert f.allowed("https://s.com/anything")


def test_frontier_rejects_an_invalid_start():
    with pytest.raises(ValueError, match="Not a valid"):
        Frontier("notaurl", max_pages=5)

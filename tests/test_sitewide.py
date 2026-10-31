"""Checks that compare pages: titles, navigation order, link names and help."""

from wcag_scanner.models import PageResult, PageSignals
from wcag_scanner.sitewide import sitewide_checks


def _page(url, nav, title="T", help=()):
    return PageResult(url=url, checked=[], signals=PageSignals(title=title, nav_names=nav, help=list(help)))


def test_navigation_order_change_is_flagged():
    pages = [
        _page("https://s.com/", ["home", "about", "contact"], "Home"),
        _page("https://s.com/a", ["home", "about", "contact"], "About"),
        _page("https://s.com/b", ["about", "home", "contact"], "B"),
    ]
    findings, checked = sitewide_checks(pages)
    nav = [f for f in findings if f.rule == "nav-order-changes"]
    assert [f.page for f in nav] == ["https://s.com/b"]
    assert {"2.4.2", "3.2.3", "3.2.4", "3.2.5"} - checked == {"3.2.5"}


def test_duplicate_titles_and_consistent_help():
    pages = [
        _page("https://s.com/", ["a", "b"], "Same", help=["contact", "phone"]),
        _page("https://s.com/x", ["a", "b"], "Same", help=["contact"]),
    ]
    rules = {(f.rule, f.page) for f in sitewide_checks(pages)[0]}
    assert ("duplicate-title", "https://s.com/x") in rules
    assert ("help-missing", "https://s.com/x") in rules


def test_link_names_compare_pages_not_links():
    def page(url, links):
        return PageResult(url=url, checked=[], signals=PageSignals(title=url, chrome_links=links))

    home = "https://s.com"
    # A logo and a "Home" link on every page, plus a skip link: consistent.
    same = [
        page(f"{home}/{p}", [(home + "/", "Acme"), (home + "/", "Home"), (f"{home}/{p}#main", "Skip to content")])
        for p in ("a", "b")
    ]
    assert not [f for f in sitewide_checks(same)[0] if f.criterion == "3.2.4"]
    # The same link with no name in common between two pages: flagged.
    differ = [page(f"{home}/a", [(f"{home}/help", "Help")]), page(f"{home}/b", [(f"{home}/help", "Support centre")])]
    assert [f.rule for f in sitewide_checks(differ)[0] if f.criterion == "3.2.4"] == ["inconsistent-link-names"]


def test_a_different_menu_is_review_not_fail():
    main = ["home", "services", "pricing", "about", "contact"]
    pages = [
        _page("https://s.com/", main, "A"),
        _page("https://s.com/b", main, "B"),
        _page("https://s.com/academy/", ["academy", "courses", "login"], "C"),
    ]
    nav = [(f.rule, f.status) for f in sitewide_checks(pages)[0] if f.criterion == "3.2.3"]
    assert nav == [("nav-different", "review")]

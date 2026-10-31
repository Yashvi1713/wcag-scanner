"""Layer 3: criteria that only make sense when comparing pages across the site."""

from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urldefrag

from .models import Finding, PageResult


def sitewide_checks(pages: list[PageResult]) -> tuple[list[Finding], set[str]]:
    ok = [p for p in pages if not p.error]
    findings: list[Finding] = []
    checked: set[str] = set()
    if not ok:
        return findings, checked

    findings += _unique_titles(ok)
    checked.add("2.4.2")
    findings += _multiple_ways(ok)
    checked.add("2.4.5")
    if len(ok) >= 2:
        findings += _consistent_navigation(ok)
        findings += _consistent_identification(ok)
        findings += _consistent_help(ok)
        checked.update({"3.2.3", "3.2.4", "3.2.6"})
    return findings, checked


def _unique_titles(pages: list[PageResult]) -> list[Finding]:
    counts = Counter(p.signals.title for p in pages if p.signals.title)
    return [
        Finding(
            criterion="2.4.2",
            status="fail",
            source="sitewide",
            rule="duplicate-title",
            message=f'The title "{p.signals.title}" is used by {counts[p.signals.title]} different pages, so it doesn\'t describe this page.',
            fix='Give each page a unique title, e.g. "Contact us | Site name".',
            page=p.url,
            impact="moderate",
        )
        for p in pages
        if p.signals.title and counts[p.signals.title] > 1
    ]


def _multiple_ways(pages: list[PageResult]) -> list[Finding]:
    if len(pages) == 1 and not pages[0].signals.nav_names:
        return []  # a single-page site is exempt
    if any(p.signals.has_search or p.signals.has_sitemap_link for p in pages):
        return []
    return [
        Finding(
            criterion="2.4.5",
            status="review",
            source="sitewide",
            rule="multiple-ways",
            message="Navigation is the only way found to locate pages: no search box or sitemap page was detected.",
            fix="Add site search or a sitemap page, unless every page is reachable from the home page in one step.",
            impact="moderate",
        )
    ]


def _consistent_navigation(pages: list[PageResult]) -> list[Finding]:
    with_nav = [p for p in pages if len(p.signals.nav_names) >= 2]
    if len(with_nav) < 2:
        return []
    reference = list(Counter(tuple(_dedupe(p.signals.nav_names)) for p in with_nav).most_common(1)[0][0])
    findings = []
    for p in with_nav:
        names = _dedupe(p.signals.nav_names)
        shared = set(names) & set(reference)
        overlap = len(shared) / len(set(names) | set(reference))
        if overlap < 0.5 or len(shared) < 3:
            # A different menu altogether, e.g. a separate product section of the site.
            findings.append(
                Finding(
                    criterion="3.2.3",
                    status="review",
                    source="sitewide",
                    rule="nav-different",
                    message=f"This page uses a different navigation menu ({', '.join(names[:6])}) from most pages ({', '.join(reference[:6])}).",
                    fix="If this page belongs to the same site, show the same main navigation; a separate section may have its own.",
                    page=p.url,
                    impact="minor",
                )
            )
        elif [n for n in names if n in shared] != [n for n in reference if n in shared]:
            findings.append(
                Finding(
                    criterion="3.2.3",
                    status="fail",
                    source="sitewide",
                    rule="nav-order-changes",
                    message=f"Navigation order on this page ({', '.join(names[:8])}) differs from the rest of the site ({', '.join(reference[:8])}).",
                    fix="Render the same navigation component, in the same order, on every page.",
                    page=p.url,
                    impact="moderate",
                )
            )
    if len(with_nav) >= len(pages) / 2:
        for p in pages:
            if len(p.signals.nav_names) < 2:
                findings.append(
                    Finding(
                        criterion="3.2.3",
                        status="review",
                        source="sitewide",
                        rule="nav-missing",
                        message="Most pages have a navigation menu but none was found on this page.",
                        fix="Check this page uses the shared site navigation.",
                        page=p.url,
                        impact="minor",
                    )
                )
    return findings


def _consistent_identification(pages: list[PageResult]) -> list[Finding]:
    # href -> page -> the names that page gives it. A logo and a "Home" link on every page is
    # consistent; a link with no name in common between two pages is not.
    names: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for p in pages:
        here = urldefrag(p.url)[0].rstrip("/")
        for href, name in p.signals.chrome_links:
            key, fragment = urldefrag(href)
            key = key.rstrip("/")
            label = " ".join(name.lower().split())
            if fragment and key == here:
                continue  # in-page links such as "Skip to content"
            if label and key.startswith("http"):
                names[key][p.url].add(label)
    findings = []
    for href, by_page in names.items():
        label_sets = list(by_page.values())
        if len(label_sets) >= 2 and not set.intersection(*label_sets):
            labels = sorted(set.union(*label_sets))
            findings.append(
                Finding(
                    criterion="3.2.4",
                    status="review",
                    source="sitewide",
                    rule="inconsistent-link-names",
                    message=f"Links to {href} in the header/footer are labelled differently across pages: "
                    + ", ".join(f'"{label}"' for label in labels)
                    + ".",
                    fix="Use the same text for links that do the same thing.",
                    impact="minor",
                )
            )
    return findings[:10]


def _consistent_help(pages: list[PageResult]) -> list[Finding]:
    if not any(p.signals.help for p in pages):
        return []
    reference = list(Counter(tuple(p.signals.help) for p in pages).most_common(1)[0][0])
    findings = []
    for p in pages:
        shared = set(p.signals.help) & set(reference)
        missing = [h for h in reference if h not in p.signals.help]
        if missing:
            findings.append(
                Finding(
                    criterion="3.2.6",
                    status="review",
                    source="sitewide",
                    rule="help-missing",
                    message=f"Help options found on other pages are missing here: {', '.join(missing)}.",
                    fix="Show the same help options (contact, phone, chat, FAQ) on every page.",
                    page=p.url,
                    impact="minor",
                )
            )
        elif [h for h in p.signals.help if h in shared] != [h for h in reference if h in shared]:
            findings.append(
                Finding(
                    criterion="3.2.6",
                    status="review",
                    source="sitewide",
                    rule="help-order",
                    message="Help options appear in a different order on this page than elsewhere on the site.",
                    fix="Keep help links in the same relative order on every page.",
                    page=p.url,
                    impact="minor",
                )
            )
    return findings


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))

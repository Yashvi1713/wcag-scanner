"""Layer 5: turn raw findings into a verdict per WCAG criterion, per page and for the site."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Literal

from .criteria import CUSTOM_COVERAGE, MEDIA_CRITERIA, PRINCIPLES, Criterion, in_scope, sort_key
from .models import Finding, FindingStatus, ScanResult

Status = Literal["fail", "review", "pass", "manual", "na"]
VerdictStatus = Literal["fail", "review", "pass", "error"]

IMPACT_RANK = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3, None: 4}
METHOD_LABELS = {
    "axe": "Automated rules",
    "keyboard": "Keyboard test",
    "forms": "Form test",
    "layout": "Zoom / reflow test",
    "media": "Media test",
    "sitewide": "Cross-page test",
    "ai": "AI review",
}

RULE_TITLES = {
    "no-keyboard-focus": "Nothing on the page can be reached with Tab",
    "keyboard-trap": "Keyboard trap",
    "focus-loop": "Focus loop that only Escape releases",
    "focus-invisible-element": "Focus lands on invisible elements",
    "focus-not-visible": "No visible focus indicator",
    "focus-obscured": "Focused element hidden behind sticky content",
    "positive-tabindex": "Positive tabindex overrides the focus order",
    "focus-jumps-back": "Focus order jumps around the page",
    "skip-link-broken": "Skip link points nowhere",
    "no-skip-link": "No way to skip repeated navigation",
    "mouse-only-control": "Clickable elements the keyboard can't reach",
    "placeholder-only-label": "Placeholder used as the only label",
    "text-spacing-clipped": "Text cut off when spacing is increased",
    "zoom-clipped": "Text cut off at 200% zoom",
    "reflow-overflow": "Horizontal scrolling at 320px wide",
    "reflow-exempt-content": "Wide tables, code or media at 320px wide",
    "autoplay-audio": "Sound plays automatically",
    "autoplay-motion": "Video plays automatically without controls",
    "infinite-animation": "Animation that never stops",
    "duplicate-title": "Page title shared with other pages",
    "multiple-ways": "Only one way to find pages",
    "nav-order-changes": "Navigation order changes between pages",
    "nav-missing": "Navigation missing on some pages",
    "nav-different": "Some pages use a different navigation menu",
    "inconsistent-link-names": "Same destination, different link names",
    "help-missing": "Help options missing on some pages",
    "help-order": "Help options in a different order",
    "ai-111": "AI review: text alternatives don't describe the image",
    "ai-133": "AI review: instructions rely on shape, colour or position",
    "ai-141": "AI review: information conveyed by colour alone",
    "ai-145": "AI review: images of text",
    "ai-244": "AI review: unclear link text",
    "ai-246": "AI review: headings or labels don't describe their purpose",
}


@dataclass
class Instance:
    """One element with a problem. A shared header or footer has the same problem on every page:
    that is one thing to fix, so it's one instance listing all the pages it was found on."""

    finding: Finding
    pages: list[str]


@dataclass
class RuleGroup:
    rule: str
    title: str
    fix: str | None
    help_url: str | None
    source: str
    status: FindingStatus
    impact: str | None
    findings: list[Finding]
    instances: list[Instance] = field(default_factory=list)


@dataclass
class CriterionResult:
    criterion: Criterion
    status: Status
    methods: list[str]
    fails: int = 0
    reviews: int = 0
    pages_failing: int = 0
    groups: list[RuleGroup] = field(default_factory=list)


@dataclass
class PageRow:
    url: str
    title: str
    error: str | None
    fails_by_principle: dict[str, int]
    reviews_by_principle: dict[str, int]
    fails: int
    reviews: int
    failed_criteria: list[str]
    screenshot: str | None
    tab_stops: int
    notes: list[str]


@dataclass
class Summary:
    verdict: str
    verdict_detail: str
    verdict_status: VerdictStatus  # "error": nothing could be scanned
    criteria: list[CriterionResult]
    counts: dict[Status, int]
    pages: list[PageRow]
    total_fail_findings: int
    total_review_findings: int
    pages_scanned: int
    pages_with_failures: int


def summarize(scan: ScanResult) -> Summary:
    all_findings = [f for p in scan.pages for f in p.findings] + scan.sitewide_findings
    by_criterion: dict[str, list[Finding]] = defaultdict(list)
    for f in all_findings:
        by_criterion[f.criterion].append(f)
    checked = {c for p in scan.pages for c in p.checked} | set(scan.sitewide_checked)
    has_media = any(p.signals.media_count for p in scan.pages if not p.error)

    criteria_results = []
    for crit in in_scope(scan.level):
        found = by_criterion.get(crit.id, [])
        fails = [f for f in found if f.status == "fail"]
        reviews = [f for f in found if f.status == "review"]
        status: Status
        if fails:
            status = "fail"
        elif reviews:
            status = "review"
        elif crit.id in checked:
            status = "pass"
        elif crit.id in MEDIA_CRITERIA and not has_media:
            status = "na"
        else:
            status = "manual"
        criteria_results.append(
            CriterionResult(
                criterion=crit,
                status=status,
                methods=_methods(crit.id, scan),
                fails=len(fails),
                reviews=len(reviews),
                pages_failing=len({f.page for f in fails if f.page}) or (1 if fails else 0),
                groups=_group(found),
            )
        )

    counts = Counter(r.status for r in criteria_results)
    in_scope_ids = {c.id for c in in_scope(scan.level)}

    pages = []
    for p in scan.pages:
        fails_p: Counter = Counter()
        reviews_p: Counter = Counter()
        failed = set()
        for f in p.findings + [f for f in scan.sitewide_findings if f.page == p.url]:
            if f.criterion not in in_scope_ids:
                continue
            principle = PRINCIPLES[f.criterion[0]]
            if f.status == "fail":
                fails_p[principle] += 1
                failed.add(f.criterion)
            else:
                reviews_p[principle] += 1
        pages.append(
            PageRow(
                url=p.url,
                title=p.title,
                error=p.error,
                fails_by_principle={k: fails_p[k] for k in PRINCIPLES.values()},
                reviews_by_principle={k: reviews_p[k] for k in PRINCIPLES.values()},
                fails=sum(fails_p.values()),
                reviews=sum(reviews_p.values()),
                failed_criteria=sorted(failed, key=sort_key),
                screenshot=p.screenshot,
                tab_stops=p.tab_stops,
                notes=p.notes,
            )
        )

    pages_scanned = sum(1 for p in scan.pages if not p.error)
    verdict_status: VerdictStatus
    if not pages_scanned:
        # Never report "passed" for a site we couldn't load: no test ran, so nothing passed.
        verdict_status = "error"
        verdict = "The site could not be scanned"
        reasons = list(dict.fromkeys(p.error for p in scan.pages if p.error)) or ["No pages were found to scan."]
        detail = f"No page loaded, so no tests ran. {'; '.join(reasons[:3])}"
        criteria_results = [
            CriterionResult(criterion=r.criterion, status="manual", methods=r.methods) for r in criteria_results
        ]
        counts = Counter(r.status for r in criteria_results)
    elif counts["fail"]:
        verdict_status = "fail"
        verdict = f"Does not meet WCAG 2.2 Level {scan.level}"
        detail = (
            f"{counts['fail']} success criteria fail on at least one page. "
            f"Fix the failures below, then complete the manual checks before claiming conformance."
        )
    elif counts["review"]:
        verdict_status = "review"
        verdict = "No definite failures found, but some items need human review"
        detail = (
            "Automated, keyboard and cross-page tests found no definite failures. "
            "Review the flagged items and complete the manual checks before claiming conformance."
        )
    else:
        verdict_status = "pass"
        verdict = f"Passed every automated check for WCAG 2.2 Level {scan.level}"
        detail = (
            "No issues were found by any automated test. Automated testing can't prove conformance on its own: "
            "complete the manual checks to confirm."
        )

    return Summary(
        verdict=verdict,
        verdict_detail=detail,
        verdict_status=verdict_status,
        criteria=criteria_results,
        counts={k: counts[k] for k in ("fail", "review", "pass", "manual", "na")},
        pages=pages,
        total_fail_findings=sum(r.fails for r in criteria_results),
        total_review_findings=sum(r.reviews for r in criteria_results),
        pages_scanned=pages_scanned,
        pages_with_failures=sum(1 for p in pages if p.fails),
    )


def _methods(criterion_id: str, scan: ScanResult) -> list[str]:
    methods = []
    if criterion_id in scan.axe_coverage:
        methods.append(METHOD_LABELS["axe"])
    for key, ids in CUSTOM_COVERAGE.items():
        if criterion_id in ids and (key != "ai" or scan.ai_enabled):
            methods.append(METHOD_LABELS[key])
    return methods


def _group(findings: list[Finding]) -> list[RuleGroup]:
    groups: dict[tuple[str, FindingStatus], list[Finding]] = defaultdict(list)
    for f in findings:
        groups[(f.rule, f.status)].append(f)
    out = [
        RuleGroup(
            rule=rule,
            title=RULE_TITLES.get(rule) or items[0].message,
            fix=items[0].fix,
            help_url=items[0].help_url,
            source=items[0].source,
            status=status,
            impact=min((i.impact for i in items), key=lambda x: IMPACT_RANK.get(x, 4)),
            findings=items,
            instances=_instances(items),
        )
        for (rule, status), items in groups.items()
    ]
    return sorted(out, key=lambda g: (g.status != "fail", IMPACT_RANK.get(g.impact, 4), -len(g.findings)))


def _instances(findings: list[Finding]) -> list[Instance]:
    """Merge findings for the same element (same selector and HTML) across pages, most widespread first."""
    merged: dict[tuple, Instance] = {}
    for f in findings:
        key = (f.selector, f.html) if f.selector else (f.message,)
        inst = merged.get(key)
        if inst is None:
            merged[key] = Instance(finding=f, pages=[f.page] if f.page else [])
        elif f.page and f.page not in inst.pages:
            inst.pages.append(f.page)
    return sorted(merged.values(), key=lambda i: -len(i.pages))

"""Layer 2: drive the page like a keyboard / zoom / small-screen user would."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from playwright.async_api import Page, ViewportSize

from .models import Finding, FindingStatus, Source

PROBE_SOURCE = (Path(__file__).parent / "static" / "probe.js").read_text()

DESKTOP: ViewportSize = {"width": 1280, "height": 800}
MOBILE: ViewportSize = {"width": 375, "height": 812}
REFLOW: ViewportSize = {"width": 320, "height": 640}  # WCAG 1.4.10: 320 CSS px
# 200% browser zoom on the desktop window lays the page out at half the CSS width.
ZOOM_200: ViewportSize = {"width": DESKTOP["width"] // 2, "height": DESKTOP["height"] // 2}

TEXT_SPACING_CSS = """
* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }
p { margin-bottom: 2em !important; }
"""


async def inject_probe(page: Page) -> None:
    if not await page.evaluate("() => !!window.__wcagProbe"):
        await page.add_script_tag(content=PROBE_SOURCE)


def _f(  # noqa: PLR0917 - every check calls this positionally
    page: Page,
    criterion: str,
    status: FindingStatus,
    source: Source,
    rule: str,
    message: str,
    fix: str,
    **kw,
) -> Finding:
    """Shorthand used by every check: (page, criterion, status, source, rule, message, fix)."""
    return Finding(
        criterion=criterion, status=status, source=source, rule=rule, message=message, fix=fix, page=page.url, **kw
    )


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------


async def keyboard_walk(page: Page, max_tabs: int = 80) -> tuple[list[Finding], set[str], int]:
    """Tab through the page. Returns (findings, criteria checked, number of tab stops)."""
    await inject_probe(page)
    await page.evaluate("() => window.__wcagProbe.resetFocusWalk()")
    # Smooth scrolling animates the page towards the focused element; measure where it ends up.
    no_smooth = await page.add_style_tag(content="*, html, body { scroll-behavior: auto !important; }")

    stops: list[dict] = []
    rechecks = 0
    seen: set[int] = set()
    no_indicator: list[dict] = []
    trap: dict | None = None
    repeats = 0
    empty_presses = 0
    frame_presses = 0

    for _ in range(max_tabs):
        await page.keyboard.press("Tab")
        step = await page.evaluate("() => window.__wcagProbe.focusStep()")
        if step["prevIndicator"] is False and stops:
            no_indicator.append(stops[-1])
        cur = step["current"]
        if cur is None:
            if stops:
                break  # focus left the page (to the browser UI): the walk is complete
            empty_presses += 1
            if empty_presses >= 3:
                break
            continue
        if stops and cur["key"] == stops[-1]["key"]:
            if cur["tag"] == "iframe":  # tabbing inside an embedded frame; the top document can't see where
                frame_presses += 1
                if frame_presses > 30:
                    break
                continue
            repeats += 1
            if repeats >= 3:
                trap = cur
                break
            continue
        repeats = 0
        if cur["key"] in seen:
            if cur["key"] != stops[0]["key"]:
                trap = cur  # a cycle that doesn't include the first stop: focus can't get back out
            break
        if (cur["hidden"] or cur["tiny"] or cur["offscreen"]) and rechecks < 15:
            rechecks += 1  # some sites fade content in as it scrolls into view
            await page.wait_for_timeout(400)
            cur.update(await page.evaluate("() => window.__wcagProbe.recheckFocus()") or {})
        seen.add(cur["key"])
        stops.append(cur)

    await no_smooth.evaluate("el => el.remove()")
    findings: list[Finding] = []
    checked = {"2.1.1", "2.1.2", "2.4.1", "2.4.3", "2.4.7", "2.4.11"}

    if not stops:
        has_links = await page.evaluate(
            "() => document.querySelectorAll('a[href],button,input,select,textarea').length"
        )
        if has_links:
            findings.append(
                _f(
                    page,
                    "2.1.1",
                    "fail",
                    "keyboard",
                    "no-keyboard-focus",
                    "Pressing Tab never moved focus to any element on the page.",
                    'Make sure links and controls are real <a href>/<button> elements or have tabindex="0".',
                )
            )
        return findings, checked, 0

    if trap:
        start = next((i for i, s in enumerate(stops) if s["key"] == trap["key"]), len(stops) - 1)
        cycle_keys = {s["key"] for s in stops[start:]}
        await page.keyboard.press("Escape")
        await page.keyboard.press("Tab")
        after = (await page.evaluate("() => window.__wcagProbe.focusStep()"))["current"]
        escaped = after is None or after["key"] not in cycle_keys
        if escaped:
            findings.append(
                _f(
                    page,
                    "2.1.2",
                    "review",
                    "keyboard",
                    "focus-loop",
                    "Tab keeps focus inside a small loop; pressing Escape releases it.",
                    "If this is a modal dialog that's fine, as long as Escape is the documented way out.",
                    selector=trap["selector"],
                    html=trap["html"],
                    impact="serious",
                )
            )
        else:
            findings.append(
                _f(
                    page,
                    "2.1.2",
                    "fail",
                    "keyboard",
                    "keyboard-trap",
                    "Keyboard trap: once focus reaches this element, neither Tab nor Escape moves it away.",
                    "Remove key handlers that call preventDefault() on Tab, or provide a documented way out.",
                    selector=trap["selector"],
                    html=trap["html"],
                    impact="critical",
                )
            )

    hidden_keys = set()
    for s in stops:
        # Focus inside an iframe doesn't scroll the outer page, so "offscreen" isn't meaningful there.
        if s["hidden"] or s["tiny"] or (s["offscreen"] and s["tag"] != "iframe"):
            hidden_keys.add(s["key"])
            findings.append(
                _f(
                    page,
                    "2.4.7",
                    "fail",
                    "keyboard",
                    "focus-invisible-element",
                    f"Keyboard focus lands on an element that isn't visible on screen ('{s['name'] or s['tag']}').",
                    "Hide it with display:none / inert when it's not shown, or make it visible when focused.",
                    selector=s["selector"],
                    html=s["html"],
                    impact="serious",
                )
            )
    for s in no_indicator[:15]:
        # Iframes draw focus inside the frame; overlays and other tricks are caught by comparing pixels.
        if s["key"] in hidden_keys or s["tag"] == "iframe" or await _focus_changes_pixels(page, s["key"]):
            continue
        findings.append(
            _f(
                page,
                "2.4.7",
                "fail",
                "keyboard",
                "focus-not-visible",
                f"No visible focus indicator: nothing about '{s['name'] or s['tag']}' changes when it receives keyboard focus.",
                "Don't remove the outline; add a :focus-visible style such as outline: 2px solid currentColor.",
                selector=s["selector"],
                html=s["html"],
                impact="serious",
            )
        )
    # One finding per covering element: a popup that hides the whole page is one problem, not 300.
    covered: dict[str, list[dict]] = {}
    for s in stops:
        if s["obscuredBy"]:
            covered.setdefault(s["obscuredBy"], []).append(s)
    for coverer, hidden in covered.items():
        s = hidden[0]
        names = ", ".join(f"'{h['name'] or h['tag']}'" for h in hidden[:3])
        more = f" and {len(hidden) - 3} more" if len(hidden) > 3 else ""
        message = (
            f"When focused, {names}{more} {'are' if len(hidden) > 1 else 'is'} completely hidden "
            f"behind a fixed/sticky element ({coverer})."
        )
        fix = "Add scroll-padding-top equal to the sticky header height, or make the banner dismissible."
        if len(hidden) > 10:
            message += " It looks like a popup or overlay that keyboard focus moves behind."
            fix = 'Make the popup a modal dialog (role="dialog" aria-modal="true") that keeps focus inside until it\'s closed.'
        findings.append(
            _f(
                page,
                "2.4.11",
                "fail",
                "keyboard",
                "focus-obscured",
                message,
                fix,
                selector=s["selector"],
                html=s["html"],
                impact="serious",
            )
        )

    positive = [s for s in stops if s["tabindex"] and s["tabindex"].lstrip("-").isdigit() and int(s["tabindex"]) > 0]
    for s in positive[:5]:
        findings.append(
            _f(
                page,
                "2.4.3",
                "review",
                "keyboard",
                "positive-tabindex",
                f'tabindex="{s["tabindex"]}" overrides the natural focus order.',
                'Use tabindex="0" and order the DOM to match the visual order.',
                selector=s["selector"],
                html=s["html"],
                impact="moderate",
            )
        )
    jumps = 0
    for a, b in pairwise(stops):
        # Moving from the bottom of one column to the top of the next one is normal reading order.
        next_column = b["left"] > a["left"] + 100
        if b["top"] < a["top"] - 400 and not next_column and jumps < 3:
            jumps += 1
            findings.append(
                _f(
                    page,
                    "2.4.3",
                    "review",
                    "keyboard",
                    "focus-jumps-back",
                    f"Focus jumps {int(a['top'] - b['top'])}px back up the page, from '{a['name'] or a['tag']}' to '{b['name'] or b['tag']}'.",
                    "Check the tab order follows the reading order; reorder the DOM if not.",
                    selector=b["selector"],
                    html=b["html"],
                    impact="moderate",
                )
            )

    first = stops[0]
    if first["tag"] == "a" and first["href"] and first["href"].startswith("#") and len(first["href"]) > 1:
        if not await page.evaluate("(h) => window.__wcagProbe.skipTargetExists(h)", first["href"]):
            findings.append(
                _f(
                    page,
                    "2.4.1",
                    "fail",
                    "keyboard",
                    "skip-link-broken",
                    f"The skip link points to '{first['href']}', but no element has that id.",
                    "Point the skip link at the id of the <main> element.",
                    selector=first["selector"],
                    html=first["html"],
                    impact="serious",
                )
            )
    else:
        main_at = next((i for i, s in enumerate(stops) if s["inMain"]), None)
        if (main_at is None and len(stops) > 10) or (main_at is not None and main_at > 10):
            n = main_at if main_at is not None else len(stops)
            findings.append(
                _f(
                    page,
                    "2.4.1",
                    "review",
                    "keyboard",
                    "no-skip-link",
                    f"No skip link: keyboard users press Tab {n} times before reaching the main content.",
                    "Add a 'Skip to main content' link as the first focusable element.",
                    impact="moderate",
                )
            )

    for el in await page.evaluate("() => window.__wcagProbe.mouseOnly()"):
        findings.append(
            _f(
                page,
                "2.1.1",
                "fail" if el["strong"] else "review",
                "keyboard",
                "mouse-only-control",
                f"'{el['name'] or 'Element'}' looks clickable but can't be reached with the keyboard.",
                'Use a <button> or <a href>, or add tabindex="0", a role and Enter/Space key handlers.',
                selector=el["selector"],
                html=el["html"],
                impact="serious" if el["strong"] else "moderate",
            )
        )

    return findings, checked, len(stops)


async def _focus_changes_pixels(page: Page, key: int) -> bool:
    """Screenshot the element unfocused and focused. Any visible difference counts as an indicator."""
    clip = await page.evaluate("(k) => window.__wcagProbe.prepareFocusShot(k)", key)
    if not clip:
        return False
    await page.wait_for_timeout(100)
    before = await page.screenshot(clip=clip, animations="disabled", caret="initial")
    await page.evaluate("(k) => window.__wcagProbe.focusByKey(k)", key)
    await page.wait_for_timeout(150)
    after = await page.screenshot(clip=clip, animations="disabled", caret="initial")
    return before != after


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------


async def form_checks(page: Page) -> tuple[list[Finding], set[str]]:
    await inject_probe(page)
    findings = [
        _f(
            page,
            "3.3.2",
            "fail",
            "forms",
            "placeholder-only-label",
            f'The field labelled only by its placeholder ("{f["placeholder"]}") loses its label as soon as the user types.',
            "Add a visible <label for=...>; keep the placeholder for an example value only.",
            selector=f["selector"],
            html=f["html"],
            impact="serious",
        )
        for f in await page.evaluate("() => window.__wcagProbe.placeholderOnly()")
    ]
    return findings, {"3.3.2"}


# ---------------------------------------------------------------------------
# Layout: text spacing, 200% zoom, reflow at 320px
# ---------------------------------------------------------------------------


async def layout_checks(page: Page) -> tuple[list[Finding], set[str]]:
    await inject_probe(page)
    findings: list[Finding] = []
    baseline = {c["key"] for c in await page.evaluate("() => window.__wcagProbe.clippedText()")}

    # 1.4.12 Text Spacing: apply the spacing values from the success criterion.
    handle = await page.add_style_tag(content=TEXT_SPACING_CSS)
    await page.wait_for_timeout(150)
    for c in [c for c in await page.evaluate("() => window.__wcagProbe.clippedText()") if c["key"] not in baseline][
        :10
    ]:
        findings.append(
            _f(
                page,
                "1.4.12",
                "fail",
                "layout",
                "text-spacing-clipped",
                f"Text is cut off when users increase text spacing: '{c['text']}'.",
                "Avoid fixed heights and overflow:hidden on text containers; use min-height instead.",
                selector=c["selector"],
                html=c["html"],
                impact="serious",
            )
        )
    await handle.evaluate("el => el.remove()")

    # 1.4.4 Resize Text: 200% browser zoom on a 1280px window lays the page out at 640 CSS px,
    # so responsive breakpoints apply exactly as they would for a user who zooms.
    await page.set_viewport_size(ZOOM_200)
    await page.wait_for_timeout(300)
    for c in [c for c in await page.evaluate("() => window.__wcagProbe.clippedText()") if c["key"] not in baseline][
        :10
    ]:
        findings.append(
            _f(
                page,
                "1.4.4",
                "fail",
                "layout",
                "zoom-clipped",
                f"Text is cut off at 200% zoom: '{c['text']}'.",
                "Size text containers with relative units and let them grow with their content.",
                selector=c["selector"],
                html=c["html"],
                impact="serious",
                viewport="200% zoom",
            )
        )

    # 1.4.10 Reflow: 320 CSS px wide must not need horizontal scrolling.
    await page.set_viewport_size(REFLOW)
    await page.wait_for_timeout(300)
    reflow = await page.evaluate("() => window.__wcagProbe.reflow()")
    if reflow["scrollWidth"] > reflow["viewport"] + 1:
        # Carousels and other script-driven layouts re-measure after a resize; confirm before reporting.
        await page.wait_for_timeout(1500)
        reflow = await page.evaluate("() => window.__wcagProbe.reflow()")
    if reflow["scrollWidth"] > reflow["viewport"] + 1:
        real = [o for o in reflow["offenders"] if not o["exempt"]]
        for o in real[:5]:
            findings.append(
                _f(
                    page,
                    "1.4.10",
                    "fail",
                    "layout",
                    "reflow-overflow",
                    f"At 320px wide the page scrolls sideways: this element is {o['width']}px wide.",
                    "Use max-width: 100%, flexible grids and flex-wrap instead of fixed widths.",
                    selector=o["selector"],
                    html=o["html"],
                    impact="serious",
                    viewport="320px",
                )
            )
        for o in [o for o in reflow["offenders"] if o["exempt"]][:3]:
            findings.append(
                _f(
                    page,
                    "1.4.10",
                    "review",
                    "layout",
                    "reflow-exempt-content",
                    f"At 320px wide this {o['width']}px table/code/media block scrolls sideways. That's allowed only if two-dimensional layout is essential.",
                    "Wrap wide tables in a scrollable container with overflow-x: auto.",
                    selector=o["selector"],
                    html=o["html"],
                    impact="minor",
                    viewport="320px",
                )
            )
        if not reflow["offenders"]:
            findings.append(
                _f(
                    page,
                    "1.4.10",
                    "review",
                    "layout",
                    "reflow-overflow",
                    f"At 320px wide the page is {reflow['scrollWidth']}px wide, but no single element was identified as the cause.",
                    "Check for off-canvas menus or absolutely positioned elements.",
                    impact="moderate",
                    viewport="320px",
                )
            )
    await page.set_viewport_size(DESKTOP)
    return findings, {"1.4.4", "1.4.10", "1.4.12"}


# ---------------------------------------------------------------------------
# Media and motion
# ---------------------------------------------------------------------------


async def media_checks(page: Page) -> tuple[list[Finding], set[str], int]:
    await inject_probe(page)
    data = await page.evaluate("() => window.__wcagProbe.media()")
    findings: list[Finding] = []
    for m in data["media"]:
        long_enough = m["duration"] == -1 or m["duration"] > 3
        if m["playing"] and not m["muted"] and long_enough:
            findings.append(
                _f(
                    page,
                    "1.4.2",
                    "fail" if not m["controls"] else "review",
                    "media",
                    "autoplay-audio",
                    f"<{m['tag']}> starts playing sound automatically"
                    + ("" if m["controls"] else " and has no controls to stop it")
                    + ".",
                    "Don't autoplay sound; if you must, start muted and provide a visible pause/mute button.",
                    selector=m["selector"],
                    html=m["html"],
                    impact="serious",
                )
            )
        elif m["tag"] == "video" and m["playing"] and not m["controls"] and (m["loop"] or long_enough):
            findings.append(
                _f(
                    page,
                    "2.2.2",
                    "review",
                    "media",
                    "autoplay-motion",
                    "A video plays automatically for more than 5 seconds with no visible controls.",
                    "Provide a pause button, or stop the video after 5 seconds.",
                    selector=m["selector"],
                    html=m["html"],
                    impact="moderate",
                )
            )
    for a in data["animations"]:
        findings.append(
            _f(
                page,
                "2.2.2",
                "review",
                "media",
                "infinite-animation",
                "This element animates forever. Users need a way to pause moving content that lasts more than 5 seconds.",
                "Add a pause control, or stop the animation under prefers-reduced-motion.",
                selector=a["selector"],
                html=a["html"],
                impact="moderate",
            )
        )
    return findings, {"1.4.2", "2.2.2"}, data["count"]

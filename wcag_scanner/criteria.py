"""The WCAG 2.2 success criteria and which of our checks can test each one."""

from __future__ import annotations

import re
from dataclasses import dataclass

PRINCIPLES = {"1": "Perceivable", "2": "Operable", "3": "Understandable", "4": "Robust"}
LEVEL_RANK = {"A": 1, "AA": 2, "AAA": 3}


@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    level: str
    manual: str  # what a human tester should check

    @property
    def principle(self) -> str:
        return PRINCIPLES[self.id[0]]

    @property
    def url(self) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", self.name.lower()).strip("-")
        return f"https://www.w3.org/WAI/WCAG22/Understanding/{slug}.html"


CRITERIA: list[Criterion] = [
    # 1. Perceivable
    Criterion(
        "1.1.1",
        "Non-text Content",
        "A",
        "Every image, icon and chart has a text alternative that conveys the same meaning; decorative images are hidden from screen readers.",
    ),
    Criterion(
        "1.2.1",
        "Audio-only and Video-only (Prerecorded)",
        "A",
        "Audio-only content has a transcript; silent video has a transcript or audio track.",
    ),
    Criterion(
        "1.2.2",
        "Captions (Prerecorded)",
        "A",
        "Every prerecorded video with sound has accurate, synchronised captions.",
    ),
    Criterion(
        "1.2.3",
        "Audio Description or Media Alternative (Prerecorded)",
        "A",
        "Video has audio description or a full text alternative of what is shown.",
    ),
    Criterion("1.2.4", "Captions (Live)", "AA", "Live video streams have real-time captions."),
    Criterion(
        "1.2.5",
        "Audio Description (Prerecorded)",
        "AA",
        "Prerecorded video has audio description of important visual information.",
    ),
    Criterion("1.2.6", "Sign Language (Prerecorded)", "AAA", "Prerecorded video has sign language interpretation."),
    Criterion(
        "1.2.7",
        "Extended Audio Description (Prerecorded)",
        "AAA",
        "Video pauses to allow extended audio description where needed.",
    ),
    Criterion(
        "1.2.8",
        "Media Alternative (Prerecorded)",
        "AAA",
        "A full text alternative is provided for all prerecorded media.",
    ),
    Criterion("1.2.9", "Audio-only (Live)", "AAA", "Live audio has a real-time text alternative."),
    Criterion(
        "1.3.1",
        "Info and Relationships",
        "A",
        "Headings, lists, tables and form groups are marked up so their structure is available to screen readers.",
    ),
    Criterion("1.3.2", "Meaningful Sequence", "A", "Reading order in the DOM matches the visual, meaningful order."),
    Criterion(
        "1.3.3",
        "Sensory Characteristics",
        "A",
        "Instructions don't rely only on shape, colour, size, position or sound (e.g. 'click the round button').",
    ),
    Criterion("1.3.4", "Orientation", "AA", "Content works in both portrait and landscape."),
    Criterion("1.3.5", "Identify Input Purpose", "AA", "Personal-data fields use the correct autocomplete attribute."),
    Criterion(
        "1.3.6",
        "Identify Purpose",
        "AAA",
        "The purpose of UI components, icons and regions can be determined programmatically.",
    ),
    Criterion(
        "1.4.1",
        "Use of Color",
        "A",
        "Colour is never the only way information is conveyed (links, errors, required fields, charts).",
    ),
    Criterion(
        "1.4.2", "Audio Control", "A", "Audio that plays automatically for more than 3 seconds can be paused or muted."
    ),
    Criterion(
        "1.4.3",
        "Contrast (Minimum)",
        "AA",
        "Text has at least 4.5:1 contrast (3:1 for large text), including text over images.",
    ),
    Criterion("1.4.4", "Resize Text", "AA", "Text can be zoomed to 200% without loss of content or function."),
    Criterion("1.4.5", "Images of Text", "AA", "Real text is used instead of images of text, except logos."),
    Criterion("1.4.6", "Contrast (Enhanced)", "AAA", "Text has at least 7:1 contrast (4.5:1 for large text)."),
    Criterion("1.4.7", "Low or No Background Audio", "AAA", "Speech audio has little or no background sound."),
    Criterion(
        "1.4.8",
        "Visual Presentation",
        "AAA",
        "Users can choose colours, line width is limited, text is not justified, line spacing is adequate.",
    ),
    Criterion(
        "1.4.9",
        "Images of Text (No Exception)",
        "AAA",
        "Images of text are used only for decoration or where essential.",
    ),
    Criterion("1.4.10", "Reflow", "AA", "At 320 CSS px wide (400% zoom) content reflows with no horizontal scrolling."),
    Criterion(
        "1.4.11",
        "Non-text Contrast",
        "AA",
        "Input borders, icons, focus indicators and chart elements have at least 3:1 contrast.",
    ),
    Criterion(
        "1.4.12",
        "Text Spacing",
        "AA",
        "Increasing line, letter, word and paragraph spacing doesn't cut off or overlap text.",
    ),
    Criterion(
        "1.4.13",
        "Content on Hover or Focus",
        "AA",
        "Tooltips and popovers can be dismissed with Esc, can be hovered, and stay visible until dismissed.",
    ),
    # 2. Operable
    Criterion("2.1.1", "Keyboard", "A", "Every function can be operated with the keyboard alone."),
    Criterion("2.1.2", "No Keyboard Trap", "A", "Keyboard focus can always be moved away from any component."),
    Criterion("2.1.3", "Keyboard (No Exception)", "AAA", "All functionality is keyboard operable without exception."),
    Criterion(
        "2.1.4",
        "Character Key Shortcuts",
        "A",
        "Single-key shortcuts can be turned off, remapped, or only work when the component has focus.",
    ),
    Criterion("2.2.1", "Timing Adjustable", "A", "Time limits can be turned off, adjusted or extended."),
    Criterion(
        "2.2.2",
        "Pause, Stop, Hide",
        "A",
        "Carousels, animations and auto-updating content can be paused, stopped or hidden.",
    ),
    Criterion("2.2.3", "No Timing", "AAA", "Timing is not an essential part of any activity."),
    Criterion("2.2.4", "Interruptions", "AAA", "Interruptions can be postponed or suppressed."),
    Criterion(
        "2.2.5", "Re-authenticating", "AAA", "Data is preserved when a session expires and the user signs in again."
    ),
    Criterion("2.2.6", "Timeouts", "AAA", "Users are warned about inactivity timeouts that could lose data."),
    Criterion("2.3.1", "Three Flashes or Below Threshold", "A", "Nothing flashes more than three times per second."),
    Criterion("2.3.2", "Three Flashes", "AAA", "Nothing flashes more than three times per second, regardless of size."),
    Criterion(
        "2.3.3",
        "Animation from Interactions",
        "AAA",
        "Motion triggered by interaction can be disabled (prefers-reduced-motion).",
    ),
    Criterion("2.4.1", "Bypass Blocks", "A", "A skip link or landmarks let users jump past repeated navigation."),
    Criterion("2.4.2", "Page Titled", "A", "Each page has a unique title that describes its topic or purpose."),
    Criterion("2.4.3", "Focus Order", "A", "Tab order follows a logical sequence that preserves meaning."),
    Criterion(
        "2.4.4",
        "Link Purpose (In Context)",
        "A",
        "The purpose of each link is clear from its text or surrounding context.",
    ),
    Criterion(
        "2.4.5", "Multiple Ways", "AA", "There is more than one way to find a page (navigation, search, sitemap)."
    ),
    Criterion("2.4.6", "Headings and Labels", "AA", "Headings and labels describe their topic or purpose."),
    Criterion("2.4.7", "Focus Visible", "AA", "Every focusable element shows a visible focus indicator."),
    Criterion(
        "2.4.8", "Location", "AAA", "Users can tell where they are within the site (breadcrumbs, current-page markers)."
    ),
    Criterion("2.4.9", "Link Purpose (Link Only)", "AAA", "Every link's purpose is clear from its text alone."),
    Criterion("2.4.10", "Section Headings", "AAA", "Content is organised with section headings."),
    Criterion(
        "2.4.11",
        "Focus Not Obscured (Minimum)",
        "AA",
        "Focused elements are never entirely hidden by sticky headers, banners or chat widgets.",
    ),
    Criterion(
        "2.4.12",
        "Focus Not Obscured (Enhanced)",
        "AAA",
        "No part of a focused element is hidden by author-created content.",
    ),
    Criterion("2.4.13", "Focus Appearance", "AAA", "Focus indicators are at least 2 CSS px thick with 3:1 contrast."),
    Criterion(
        "2.5.1",
        "Pointer Gestures",
        "A",
        "Multipoint or path-based gestures (pinch, swipe) have a single-pointer alternative.",
    ),
    Criterion("2.5.2", "Pointer Cancellation", "A", "Actions fire on pointer up, not down, or can be aborted."),
    Criterion("2.5.3", "Label in Name", "A", "A control's accessible name contains its visible label text."),
    Criterion(
        "2.5.4",
        "Motion Actuation",
        "A",
        "Functions triggered by shaking or tilting have a UI alternative and can be disabled.",
    ),
    Criterion("2.5.5", "Target Size (Enhanced)", "AAA", "Touch targets are at least 44×44 CSS px."),
    Criterion(
        "2.5.6",
        "Concurrent Input Mechanisms",
        "AAA",
        "Users can switch between mouse, keyboard, touch and other inputs.",
    ),
    Criterion("2.5.7", "Dragging Movements", "AA", "Anything done by dragging can also be done with single clicks."),
    Criterion(
        "2.5.8", "Target Size (Minimum)", "AA", "Touch targets are at least 24×24 CSS px or have enough spacing."
    ),
    # 3. Understandable
    Criterion("3.1.1", "Language of Page", "A", "The page's main language is set with the lang attribute."),
    Criterion("3.1.2", "Language of Parts", "AA", "Passages in a different language are marked with lang."),
    Criterion("3.1.3", "Unusual Words", "AAA", "Jargon and idioms are explained."),
    Criterion("3.1.4", "Abbreviations", "AAA", "Abbreviations are expanded or explained."),
    Criterion("3.1.5", "Reading Level", "AAA", "Content above lower-secondary reading level has a simpler version."),
    Criterion("3.1.6", "Pronunciation", "AAA", "Pronunciation is given where meaning depends on it."),
    Criterion(
        "3.2.1", "On Focus", "A", "Focusing an element never triggers a change of context (e.g. opening a new page)."
    ),
    Criterion("3.2.2", "On Input", "A", "Changing a field's value doesn't change context unless the user was warned."),
    Criterion("3.2.3", "Consistent Navigation", "AA", "Repeated navigation appears in the same order on every page."),
    Criterion(
        "3.2.4",
        "Consistent Identification",
        "AA",
        "Components with the same function are labelled the same way across pages.",
    ),
    Criterion("3.2.5", "Change on Request", "AAA", "Changes of context only happen when the user asks for them."),
    Criterion(
        "3.2.6",
        "Consistent Help",
        "A",
        "Help links (contact, chat, FAQ) appear in the same relative order on every page.",
    ),
    Criterion("3.3.1", "Error Identification", "A", "Form errors are identified and described to the user in text."),
    Criterion("3.3.2", "Labels or Instructions", "A", "Form fields have visible labels or instructions."),
    Criterion("3.3.3", "Error Suggestion", "AA", "Error messages suggest how to fix the problem."),
    Criterion(
        "3.3.4",
        "Error Prevention (Legal, Financial, Data)",
        "AA",
        "Legal or financial submissions can be reviewed, corrected or reversed.",
    ),
    Criterion("3.3.5", "Help", "AAA", "Context-sensitive help is available."),
    Criterion("3.3.6", "Error Prevention (All)", "AAA", "All submissions can be reviewed, corrected or reversed."),
    Criterion(
        "3.3.7",
        "Redundant Entry",
        "A",
        "Information already entered in a process is auto-filled or selectable, not re-typed.",
    ),
    Criterion(
        "3.3.8",
        "Accessible Authentication (Minimum)",
        "AA",
        "Login doesn't require a cognitive test (e.g. remembering or transcribing) unless an alternative exists; paste is allowed.",
    ),
    Criterion(
        "3.3.9",
        "Accessible Authentication (Enhanced)",
        "AAA",
        "Login doesn't require any cognitive function test, including object recognition.",
    ),
    # 4. Robust
    Criterion(
        "4.1.2",
        "Name, Role, Value",
        "A",
        "Custom controls expose the correct name, role and state to assistive technology.",
    ),
    Criterion(
        "4.1.3",
        "Status Messages",
        "AA",
        "Status messages (e.g. 'item added to cart') are announced without moving focus.",
    ),
]


# Criteria tested by our own checks (axe-core's coverage is read from axe at runtime).
CUSTOM_COVERAGE: dict[str, set[str]] = {
    "keyboard": {"2.1.1", "2.1.2", "2.4.1", "2.4.3", "2.4.7", "2.4.11"},
    "forms": {"3.3.2"},
    "layout": {"1.4.4", "1.4.10", "1.4.12"},
    "media": {"1.4.2", "2.2.2"},
    "sitewide": {"2.4.2", "2.4.5", "3.2.3", "3.2.4", "3.2.6"},
    "ai": {"1.1.1", "1.3.3", "1.4.1", "1.4.5", "2.4.4", "2.4.6"},
}

# Criteria that only apply when a page has audio or video.
MEDIA_CRITERIA = {c.id for c in CRITERIA if c.id.startswith("1.2.")}


def in_scope(level: str) -> list[Criterion]:
    return [c for c in CRITERIA if LEVEL_RANK[c.level] <= LEVEL_RANK[level]]


def sort_key(criterion_id: str) -> tuple[int, ...]:
    return tuple(int(p) for p in criterion_id.split("."))

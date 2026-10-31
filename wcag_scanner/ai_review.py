"""Layer 4: ask Claude the questions rules can't answer ("is this alt text meaningful?")."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Literal

import anthropic
from playwright.async_api import Page
from pydantic import BaseModel

from .models import Finding

MODEL = "claude-opus-5-5"

SYSTEM = """You are an expert WCAG 2.2 accessibility auditor reviewing one web page.
Automated tools have already checked whether attributes exist (missing alt, missing labels, contrast).
Your job is the human-judgement part they can't do. Judge ONLY these success criteria:

- 1.1.1 Non-text Content: does each image's alt text convey what the image shows or does? Flag alt text that is
  a file name, generic ("image", "photo", "logo" alone when the image carries more), wrong, or missing meaning.
  Decorative images with alt="" are fine. For a linked image, the alt should describe the link destination.
- 1.4.5 Images of Text: images that are mostly text which could have been real text (logos are exempt).
- 2.4.4 Link Purpose (In Context): link text that is unclear even with its surrounding context
  ("click here", "read more", "learn more" repeated with no context).
- 2.4.6 Headings and Labels: headings or form labels that don't describe their topic or purpose.
- 1.3.3 Sensory Characteristics: instructions that rely only on shape, colour, size, location or sound.
- 1.4.1 Use of Color: in the screenshot, information conveyed only by colour (e.g. links distinguished only by colour
  inside body text, required fields or errors shown only in red).

Rules:
- Report problems only. Do not report things that are fine.
- Be conservative: use status "fail" only when you are confident a real user would be affected; otherwise "review".
- target must be one of the ids given (img-3, link-12, heading-2, field-1) or "page" for screenshot-level issues.
- Keep issue and fix to one or two short sentences each, written for a web developer."""


class AIFinding(BaseModel):
    criterion: Literal["1.1.1", "1.3.3", "1.4.1", "1.4.5", "2.4.4", "2.4.6"]
    status: Literal["fail", "review"]
    target: str
    issue: str
    fix: str
    confidence: Literal["high", "medium", "low"]


class AIPageReview(BaseModel):
    findings: list[AIFinding]


def ai_available() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or (Path.home() / ".config" / "anthropic").exists()
    )


async def collect_inputs(page: Page) -> tuple[list[Any], dict[str, str]]:
    """Build the message content blocks and a map of target id -> CSS selector."""
    data = await page.evaluate("() => window.__wcagProbe.aiData()")
    shot = await page.screenshot(type="jpeg", quality=60)
    blocks: list[Any] = [
        {"type": "text", "text": f"Page URL: {page.url}\nScreenshot of the first screen:"},
        _image(shot),
    ]
    selectors: dict[str, str] = {}
    for img in data["imgs"]:
        selectors[img["id"]] = img["selector"]
        desc = {k: img[k] for k in ("alt", "ariaLabel", "role", "src", "linkText") if img[k] is not None}
        blocks.append({"type": "text", "text": f"{img['id']}: {json.dumps(desc)}"})
        try:
            crop = await page.locator(f'[data-wcag-ai="{img["id"]}"]').first.screenshot(
                type="jpeg", quality=60, timeout=3000
            )
            blocks.append(_image(crop))
        except Exception:
            blocks.append({"type": "text", "text": "(image could not be captured)"})
    for kind in ("links", "headings", "fields"):
        for item in data[kind]:
            selectors[item["id"]] = item["selector"]
    listing = {
        "links": [{k: v for k, v in link.items() if k != "selector"} for link in data["links"]],
        "headings": [{k: v for k, v in h.items() if k != "selector"} for h in data["headings"]],
        "form_fields": [{k: v for k, v in f.items() if k != "selector"} for f in data["fields"]],
        "instruction_text_mentioning_colour_shape_or_position": data["instructions"],
    }
    blocks.append(
        {"type": "text", "text": "Page content extracted from the DOM:\n" + json.dumps(listing, ensure_ascii=False)}
    )
    return blocks, selectors


async def review_page(client: anthropic.AsyncAnthropic, page: Page) -> tuple[list[Finding], str | None]:
    """Returns (findings, note). The note explains why the review was skipped, if it was."""
    blocks, selectors = await collect_inputs(page)
    try:
        response = await client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            messages=[{"role": "user", "content": blocks}],
            output_format=AIPageReview,
        )
    except anthropic.AuthenticationError:
        return [], "AI review skipped: no valid Anthropic credentials."
    except anthropic.RateLimitError:
        return [], "AI review skipped: rate limited by the Anthropic API."
    except anthropic.APIStatusError as e:
        return [], f"AI review skipped: API error {e.status_code}."
    except anthropic.APIConnectionError:
        return [], "AI review skipped: could not reach the Anthropic API."

    if response.stop_reason == "refusal" or response.parsed_output is None:
        return [], "AI review returned no result for this page."
    findings = [
        Finding(
            criterion=f.criterion,
            status=f.status,
            source="ai",
            rule="ai-" + f.criterion.replace(".", ""),
            message=f.issue,
            fix=f.fix,
            page=page.url,
            selector=selectors.get(f.target),
            impact="moderate",
            confidence=f.confidence,
        )
        for f in response.parsed_output.findings
    ]
    return findings, None


def _image(jpeg: bytes) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode()},
    }

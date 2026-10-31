"""The optional Claude layer: every way the API call can go wrong degrades to a note, never a crash."""

import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from playwright.async_api import async_playwright

from wcag_scanner import ai_review
from wcag_scanner.models import ScanResult
from wcag_scanner.report import render_pdf, render_report
from wcag_scanner.scanner import BrowserPool, ScanOptions, scan_page

_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, code):
    return cls("error", response=httpx.Response(code, request=_REQUEST), body=None)


def _client(parse):
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))


@pytest.fixture
def no_page_inputs(monkeypatch):
    async def fake_inputs(page):
        return [{"type": "text", "text": "..."}], {"link-1": "main a"}

    monkeypatch.setattr(ai_review, "collect_inputs", fake_inputs)


@pytest.mark.parametrize(("error", "note"), [
    (_status_error(anthropic.AuthenticationError, 401), "no valid Anthropic credentials"),
    (_status_error(anthropic.RateLimitError, 429), "rate limited"),
    (_status_error(anthropic.InternalServerError, 500), "API error 500"),
    (_status_error(anthropic.BadRequestError, 400), "API error 400"),
    (anthropic.APIConnectionError(request=_REQUEST), "could not reach the Anthropic API"),
])  # fmt: skip
def test_api_errors_become_notes(no_page_inputs, error, note):
    async def parse(**kwargs):
        raise error

    findings, message = asyncio.run(ai_review.review_page(_client(parse), SimpleNamespace(url="https://s.com/")))
    assert findings == []
    assert note in message


@pytest.mark.parametrize("response", [
    SimpleNamespace(stop_reason="refusal", parsed_output=None),
    SimpleNamespace(stop_reason="max_tokens", parsed_output=None),
])  # fmt: skip
def test_no_usable_answer_becomes_a_note(no_page_inputs, response):
    async def parse(**kwargs):
        return response

    findings, message = asyncio.run(ai_review.review_page(_client(parse), SimpleNamespace(url="https://s.com/")))
    assert findings == [] and "no result" in message


def test_ai_model_only_answers_for_its_criteria():
    with pytest.raises(ValueError, match="criterion"):
        ai_review.AIFinding(criterion="2.1.1", status="fail", target="x", issue="i", fix="f", confidence="high")


@pytest.mark.browser
def test_real_page_inputs_reach_the_model_and_findings_map_back(server):
    """collect_inputs on a real page: screenshot, links and headings go in; targets come back as selectors."""
    seen = {}

    async def parse(**kwargs):
        seen.update(kwargs)
        review = ai_review.AIPageReview(
            findings=[
                ai_review.AIFinding(
                    criterion="2.4.4",
                    status="review",
                    target="link-1",
                    issue="unclear",
                    fix="say where",
                    confidence="medium",
                )
            ]
        )
        return SimpleNamespace(stop_reason="end_turn", parsed_output=review)

    result = _scan_one(f"{server}/demo_site/", _client(parse))
    content = seen["messages"][0]["content"]
    assert any(block["type"] == "image" for block in content)
    assert "click here" in content[-1]["text"]  # the page's links were extracted for the model
    ai = [f for f in result.findings if f.source == "ai"]
    assert ai and ai[0].selector and ai[0].confidence == "medium"


@pytest.mark.browser
def test_a_failing_ai_layer_keeps_every_other_finding(server):
    async def parse(**kwargs):
        raise RuntimeError("unexpected SDK failure")

    result = _scan_one(f"{server}/demo_site/", _client(parse))
    assert result.error is None
    assert any(f.source == "axe" for f in result.findings)
    assert "AI review skipped: RuntimeError." in result.notes


@pytest.mark.browser
def test_pdf_export_is_a_real_pdf(demo_scan):
    pdf = asyncio.run(render_pdf(render_report(demo_scan, standalone=True)))
    assert pdf.startswith(b"%PDF") and len(pdf) > 50_000


def _scan_one(url, client):
    async def go():
        async with async_playwright() as pw:
            pool = BrowserPool(pw, 1)
            await pool.start()
            try:
                async with pool.context() as ctx:
                    scan = ScanResult(id="t", start_url=url, started_at="2026-01-01T00:00:00+00:00")
                    return (await scan_page(ctx, url, ScanOptions(), scan=scan, ai_client=client))[0]
            finally:
                await pool.close()

    return asyncio.run(go())


def test_ai_findings_map_back_to_elements(monkeypatch):
    review = ai_review.AIPageReview(
        findings=[
            ai_review.AIFinding(
                criterion="2.4.4",
                status="fail",
                target="link-2",
                issue="'click here' is unclear",
                fix="Describe the destination",
                confidence="high",
            )
        ]
    )

    async def fake_inputs(page):
        return [{"type": "text", "text": "..."}], {"link-2": "main > p > a:nth-of-type(2)"}

    class FakeMessages:
        async def parse(self, **kwargs):
            assert kwargs["model"] == "claude-opus-5-5"
            return SimpleNamespace(stop_reason="end_turn", parsed_output=review)

    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setattr(ai_review, "collect_inputs", fake_inputs)
    page = SimpleNamespace(url="https://s.com/")
    findings, note = asyncio.run(ai_review.review_page(client, page))
    assert note is None
    assert findings[0].selector == "main > p > a:nth-of-type(2)"
    assert findings[0].source == "ai" and findings[0].confidence == "high"

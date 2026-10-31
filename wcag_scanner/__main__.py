"""Command line: `python -m wcag_scanner scan <url>` or `python -m wcag_scanner serve`.

Exit codes for `scan`, so it can gate a CI pipeline:
  0  nothing at or above the --fail-on threshold
  1  failures (or, with --fail-on review, items to review) were found
  2  the site couldn't be scanned at all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .aggregator import summarize
from .report import render_pdf, render_report
from .scanner import ScanOptions, scan_site

ICONS = {"fail": "✕ FAIL", "review": "! REVIEW", "pass": "✓ pass", "manual": "? manual", "na": "– n/a"}
EXIT_OK, EXIT_ISSUES, EXIT_UNSCANNABLE = 0, 1, 2


def _positive(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wcag_scanner", description="Check a website against WCAG 2.2.")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every page as it's scanned")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan a site and write a report")
    scan.add_argument("url")
    scan.add_argument("--pages", type=_positive, default=10, help="maximum pages to scan (default 10)")
    scan.add_argument("--level", choices=["A", "AA", "AAA"], default="AA")
    scan.add_argument("--ai", action="store_true", help="add the Claude review layer (needs Anthropic credentials)")
    scan.add_argument("--concurrency", type=_positive, default=3, help="pages scanned in parallel (default 3)")
    scan.add_argument("--max-minutes", type=_positive, default=15, help="stop starting new pages after this")
    scan.add_argument(
        "--fail-on",
        choices=["fail", "review", "never"],
        default="fail",
        help="which results make the exit code 1 (default: fail)",
    )
    scan.add_argument("--out", type=Path, default=Path("wcag-report.html"), help="HTML report path")
    scan.add_argument("--json", type=Path, help="also write the raw results as JSON")
    scan.add_argument("--pdf", type=Path, help="also write a PDF report")

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose or args.command == "serve" else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.command == "serve":
        import uvicorn

        uvicorn.run("wcag_scanner.web:app", host=args.host, port=args.port)
        return
    sys.exit(asyncio.run(run_scan(args)))


async def run_scan(args: argparse.Namespace) -> int:
    def progress(p: dict) -> None:
        print(f"  [{p.get('done', 0)}/{p.get('total', '?')}] {p.get('message', '')}", flush=True)

    print(f"Scanning {args.url} (up to {args.pages} pages, WCAG 2.2 {args.level})")
    opts = ScanOptions(
        max_pages=args.pages,
        level=args.level,
        ai=args.ai,
        concurrency=args.concurrency,
        scan_timeout=args.max_minutes * 60,
    )
    result = await scan_site(args.url, opts, progress)
    summary = summarize(result)

    print(f"\n{summary.verdict}\n{summary.verdict_detail}\n")
    for r in summary.criteria:
        if r.status in ("fail", "review"):
            print(
                f"  {ICONS[r.status]:9} {r.criterion.id:7} {r.criterion.name:42} "
                f"{r.fails} failures, {r.reviews} to review"
            )
    c = summary.counts
    print(
        f"\nCriteria: {c['fail']} fail · {c['review']} need review · {c['pass']} pass · "
        f"{c['manual']} manual only · {c['na']} not applicable"
    )
    for p in result.pages:
        if p.error:
            print(f"  skipped {p.url}: {p.error}")

    html = render_report(result, summary=summary)
    args.out.write_text(html, encoding="utf-8")
    print(f"\nReport: {args.out.resolve()}")
    if args.json:
        args.json.write_text(
            result.model_dump_json(indent=2, exclude={"pages": {"__all__": {"screenshot"}}}), encoding="utf-8"
        )
        print(f"JSON:   {args.json.resolve()}")
    if args.pdf:
        args.pdf.write_bytes(await render_pdf(html))
        print(f"PDF:    {args.pdf.resolve()}")
    return exit_code(summary.verdict_status, args.fail_on)


def exit_code(verdict: str, fail_on: str) -> int:
    if verdict == "error":
        return EXIT_UNSCANNABLE
    if fail_on == "never":
        return EXIT_OK
    if verdict == "fail" or (fail_on == "review" and verdict == "review"):
        return EXIT_ISSUES
    return EXIT_OK


if __name__ == "__main__":
    main()

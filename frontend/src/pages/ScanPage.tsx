import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router";

import { ApiError, useReport, useScan } from "../api";
import { focusHeading, restoreLostFocus, usePageTitle } from "../components/Layout";
import { hostOf } from "../format";
import { ReportView } from "../report/ReportView";
import type { ScanStatus } from "../types";

/** One scan: progress while it runs, then the report. */
export function ScanPage() {
  const { id = "" } = useParams();
  const scan = useScan(id);
  const done = scan.data?.status === "done";
  const report = useReport(id, done);

  // When a scan finishes while someone is watching, the page changes under them: move focus to
  // the report's heading so screen reader users hear the result.
  const wasRunning = useRef(false);
  const ready = done && report.isSuccess;
  const view = scan.isError
    ? "error"
    : !scan.data || (done && report.isPending)
      ? "loading"
      : scan.data.status === "error"
        ? "failed"
        : done
          ? "report"
          : "progress";
  useEffect(() => {
    if (scan.data && !done) wasRunning.current = true;
    if (ready && wasRunning.current) {
      wasRunning.current = false;
      focusHeading();
    } else {
      restoreLostFocus();
    }
  }, [view, scan.data, done, ready]);

  if (scan.isError) {
    const missing = scan.error instanceof ApiError && scan.error.status === 404;
    return <Message title={missing ? "Scan not found" : "Something went wrong"} text={scan.error.message} />;
  }
  if (!scan.data || (done && report.isPending)) return <Loading />;
  if (scan.data.status === "error") return <Message title="The scan failed" text={scan.data.error ?? "Unknown error."} />;
  if (done) {
    if (report.isError) return <Message title="The report couldn't be loaded" text={report.error.message} />;
    if (report.data) return <ReportView report={report.data} />;
  }
  return <ScanProgress scan={scan.data} />;
}

const STAGES = [
  { key: "crawl", title: "Finding pages", text: "robots.txt, the sitemap and links from the start page." },
  { key: "page", title: "Testing each page", text: "Rules, keyboard walk, zoom, text spacing and reflow." },
  { key: "sitewide", title: "Comparing pages", text: "Navigation, titles, names and help, then the verdict for every criterion." },
] as const;
const STATE_LABEL = { done: "Done", active: "Running", todo: "Waiting" } as const;

export function ScanProgress({ scan }: { scan: ScanStatus }) {
  usePageTitle(`Scanning ${hostOf(scan.url)}`);
  const { done, total, message, stage } = scan.progress;
  const max = Math.max(total, 1);
  const at = Math.max(
    STAGES.findIndex((s) => s.key === (stage ?? "crawl")),
    0,
  );

  return (
    <div className="wrap">
      <div className="progress-wrap">
        <p className="kicker">Audit in progress</p>
        <h1>{hostOf(scan.url)}</h1>
        <p className="lede">The report opens here when it&apos;s ready. You can leave and come back to it from Past audits.</p>

        <div className="progress-figure">
          <label htmlFor="bar" className="field-label">
            Pages tested
          </label>
          <span className="progress-pct" aria-hidden="true">
            {Math.round((100 * done) / max)}%
          </span>
        </div>
        <progress id="bar" max={max} value={done}>
          {done} of {max} pages
        </progress>
        {/* Announced politely, and only when the text changes, so screen readers aren't flooded. */}
        <p className="status-line" role="status" aria-live="polite">
          {message || "Starting"} ({done} of {max} pages)
        </p>

        <ol className="steps" aria-label="Stages">
          {STAGES.map((s, i) => {
            const state = i < at ? "done" : i === at ? "active" : "todo";
            return (
              <li key={s.key} className="step" data-state={state}>
                <span className="num" aria-hidden="true">
                  0{i + 1}
                </span>
                <div>
                  <strong>{s.title}</strong>
                  <p>{s.text}</p>
                </div>
                <span className="step-state">{STATE_LABEL[state]}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function Loading() {
  usePageTitle("Loading");
  return (
    <div className="wrap">
      <div className="message">
        <h1>Loading…</h1>
      </div>
    </div>
  );
}

export function Message({ title, text }: { title: string; text: string }) {
  usePageTitle(title);
  return (
    <div className="wrap">
      <div className="message">
        <h1>{title}</h1>
        <p className="lede">{text}</p>
        <Link className="button" to="/">
          Start a new audit
        </Link>
      </div>
    </div>
  );
}

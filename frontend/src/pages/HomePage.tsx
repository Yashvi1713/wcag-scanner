import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, api, useConfig, useRecentScans } from "../api";
import { Badge, Icon } from "../components/Icon";
import { usePageTitle } from "../components/Layout";
import { formatDate, hostOf } from "../format";
import type { Level, RecentScan, ScanRequest } from "../types";

const LEVELS: Level[] = ["A", "AA", "AAA"];
type Field = "url" | "max_pages" | "level";

export function HomePage() {
  usePageTitle("Check a website for accessibility");
  const navigate = useNavigate();
  const config = useConfig();
  const [url, setUrl] = useState("");
  const [maxPages, setMaxPages] = useState("10");
  const [level, setLevel] = useState<Level>("AA");
  const [ai, setAi] = useState(false);
  const [error, setError] = useState<{ message: string; field: Field | null } | null>(null);
  const urlInput = useRef<HTMLInputElement>(null);
  const pagesInput = useRef<HTMLInputElement>(null);

  const start = useMutation({
    mutationFn: api.createScan,
    onSuccess: ({ id }) => navigate(`/scans/${id}`),
    onError: (e) => {
      const field = e instanceof ApiError && isField(e.field) ? e.field : null;
      setError({ message: e.message, field });
      // Put the user back where the problem is; the alert above the form announces it.
      (field === "max_pages" ? pagesInput : urlInput).current?.focus();
    },
  });

  const submit = (request: ScanRequest) => {
    if (start.isPending) return;
    setError(null);
    start.mutate(request);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit({ url, max_pages: maxPages, level, ai });
  };

  const aiAvailable = config.data?.ai_available ?? false;
  const maxAllowed = config.data?.max_pages ?? 50;
  const invalid = (field: Field) => error?.field === field || (error !== null && error.field === null && field === "url");

  return (
    <div className="wrap">
      <div className="intro">
        <div>
          <p className="kicker">Accessibility audit · WCAG 2.2</p>
          <h1>Can everyone use this website?</h1>
          <p className="lede">
            Give it an address. It reads the whole site, uses every page the way a keyboard, zoom or screen reader user would, and tells you
            which of the WCAG success criteria fail, where, and what to change.
          </p>

          <form className="scan-form" onSubmit={onSubmit} noValidate aria-labelledby="scan-h">
            <h2 id="scan-h" className="visually-hidden">
              Start an audit
            </h2>
            {error && (
              <p className="error" id="form-error" role="alert">
                {error.message}
              </p>
            )}
            <label className="field-label" htmlFor="url">
              Website address
            </label>
            <p className="hint" id="url-hint">
              For example https://www.example.com
            </p>
            <div className="url-row">
              <input
                ref={urlInput}
                type="url"
                id="url"
                name="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
                autoComplete="url"
                spellCheck={false}
                aria-describedby={invalid("url") ? "url-hint form-error" : "url-hint"}
                aria-invalid={invalid("url") || undefined}
              />
              <button className="button" type="submit">
                {start.isPending ? "Starting…" : "Run audit"} <Icon name="arrow" />
              </button>
            </div>

            <div className="options">
              <div>
                <label className="field-label" htmlFor="max_pages">
                  Pages
                </label>
                <p className="hint" id="pages-hint">
                  Up to {maxAllowed}, a few seconds each
                </p>
                <input
                  ref={pagesInput}
                  type="number"
                  id="max_pages"
                  name="max_pages"
                  value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value)}
                  min={1}
                  max={maxAllowed}
                  aria-describedby={invalid("max_pages") ? "pages-hint form-error" : "pages-hint"}
                  aria-invalid={invalid("max_pages") || undefined}
                />
              </div>
              <fieldset aria-describedby="level-hint">
                <legend>Level</legend>
                <p className="hint" id="level-hint">
                  Most laws require AA
                </p>
                <div className="levels">
                  {LEVELS.map((l) => (
                    <label key={l}>
                      <input type="radio" name="level" value={l} checked={level === l} onChange={() => setLevel(l)} /> {l}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div>
                <p className="field-label" aria-hidden="true">
                  AI review
                </p>
                <p className="hint" id="ai-hint">
                  {aiAvailable ? "Claude reads alt text, links and headings on 5 pages" : "Set ANTHROPIC_API_KEY to enable"}
                </p>
                <label className="check">
                  <input
                    type="checkbox"
                    name="ai"
                    checked={ai}
                    onChange={(e) => setAi(e.target.checked)}
                    disabled={!aiAvailable}
                    aria-describedby="ai-hint"
                  />{" "}
                  Add AI review
                </label>
              </div>
            </div>
          </form>

          <p className="demo-line">
            <span>First time?</span>
            <button
              className="text-button"
              type="button"
              onClick={() => config.data && submit({ url: config.data.demo_url, max_pages: 5, level: "AA", ai: false })}
            >
              Audit the demo site, which has 20 planted problems
            </button>
          </p>
        </div>

        <Method />
      </div>

      <PastAudits />
    </div>
  );
}

const isField = (f: string | null): f is Field => f === "url" || f === "max_pages" || f === "level";

const STEPS: [string, string][] = [
  ["Rules", "axe-core checks contrast, names, labels and ARIA, on desktop and on a phone."],
  ["Keyboard", "A scripted user presses Tab through the page: traps, invisible focus, controls a mouse can reach and a keyboard can't."],
  ["Zoom and reflow", "200% zoom, wider text spacing and a 320 px screen. Does anything get cut off?"],
  ["Across the site", "Same navigation, same names, same help, unique titles, more than one way in."],
  ["Judgement", 'Optionally, Claude decides what rules can\'t: is this alt text useful? Is "click here" clear?'],
];

function Method() {
  const id = useId();
  return (
    <section className="method" aria-labelledby={id}>
      <h2 id={id}>What every page goes through</h2>
      <ol>
        {STEPS.map(([title, text], i) => (
          <li key={title}>
            <span className="num" aria-hidden="true">
              0{i + 1}
            </span>
            <div>
              <strong>{title}</strong>
              <p>{text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function PastAudits() {
  const scans = useRecentScans();
  return (
    <section className="ledger" id="recent" aria-labelledby="recent-h">
      <div className="ledger-head">
        <h2 id="recent-h">Past audits</h2>
        {scans.data && scans.data.length > 0 && <p>Last {scans.data.length}</p>}
      </div>
      {scans.isPending && <p className="empty">Loading…</p>}
      {scans.isError && <p className="empty">{scans.error.message}</p>}
      {scans.data?.length === 0 && <p className="empty">Nothing yet. Your audits will be listed here.</p>}
      {scans.data && scans.data.length > 0 && (
        <div className="table-wrap" role="region" tabIndex={0} aria-labelledby="recent-cap">
          <table>
            <caption id="recent-cap" className="visually-hidden">
              Past audits, newest first
            </caption>
            <thead>
              <tr>
                <th scope="col">Website</th>
                <th scope="col">Date</th>
                <th scope="col">Pages</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {scans.data.map((s) => (
                <tr key={s.id}>
                  <th scope="row">
                    <Link to={`/scans/${s.id}`}>{hostOf(s.url)}</Link>
                  </th>
                  <td className="num">{formatDate(s.created_at)}</td>
                  <td className="num">{s.status === "done" ? s.pages : "–"}</td>
                  <td>
                    <Outcome scan={s} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Outcome({ scan }: { scan: RecentScan }) {
  if (scan.status === "error") return <span className="badge badge-na">Scan failed</span>;
  if (scan.status !== "done") return <span className="badge badge-info">{scan.status === "running" ? "Running" : "Waiting"}</span>;
  if (scan.verdict === "error")
    return (
      <span className="badge badge-na">
        <Icon name="error" /> Couldn&apos;t scan
      </span>
    );
  if (scan.fails) return <Badge status="fail">{scan.fails} criteria fail</Badge>;
  return <Badge status="pass">No failures</Badge>;
}

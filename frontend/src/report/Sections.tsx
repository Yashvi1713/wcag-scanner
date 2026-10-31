import { screenshotUrl } from "../api";
import { Badge } from "../components/Icon";
import { pathOf, plural } from "../format";
import type { CriterionRow, Instance, Issue, PageRow, Report, RuleGroup } from "../types";

const SHOWN_INSTANCES = 10;

export function CriteriaTables({ report }: { report: Report }) {
  return (
    <>
      {report.principles.map((p) => {
        const caption = `crit-cap-${p.number}`;
        return (
          <div key={p.name} className="table-wrap" role="region" tabIndex={0} aria-labelledby={caption}>
            <table>
              <caption id={caption}>
                {p.number}. {p.name}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Success criterion</th>
                  <th scope="col">Level</th>
                  <th scope="col">Result</th>
                  <th scope="col">Tested by</th>
                  <th scope="col">Fail / review</th>
                  <th scope="col">Pages</th>
                </tr>
              </thead>
              <tbody>
                {p.criteria.map((row) => (
                  <CriterionTableRow key={row.criterion.id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}

function CriterionTableRow({ row }: { row: CriterionRow }) {
  const { criterion: c } = row;
  const tested =
    row.methods.length === 0
      ? "Manual check only"
      : row.status === "manual"
        ? `${row.methods.join(", ")}: nothing to test on these pages`
        : row.methods.join(", ");
  return (
    <tr>
      <th scope="row">
        <span className="sc">{c.id}</span>
        {row.has_issues ? <a href={`#c-${c.id}`}>{c.name}</a> : c.name}
      </th>
      <td className="num">{c.level}</td>
      <td>
        <Badge status={row.status} />
      </td>
      <td className="methods">{tested}</td>
      <td className="num">{row.fails || row.reviews ? `${row.fails} / ${row.reviews}` : <span className="zero">–</span>}</td>
      <td className="num">{row.pages_failing || <span className="zero">–</span>}</td>
    </tr>
  );
}

export function Pages({ report }: { report: Report }) {
  const principles = report.principles.map((p) => p.name);
  return (
    <>
      <div className="table-wrap" role="region" tabIndex={0} aria-labelledby="pages-cap">
        <table>
          <caption id="pages-cap" className="visually-hidden">
            Failures on each page, by WCAG principle (items to review in brackets)
          </caption>
          <thead>
            <tr>
              <th scope="col">Page</th>
              {principles.map((p) => (
                <th scope="col" key={p}>
                  {p}
                </th>
              ))}
              <th scope="col">Total</th>
            </tr>
          </thead>
          <tbody>
            {report.pages.map((page) => (
              <tr key={page.index}>
                <th scope="row" className="page-cell">
                  <a href={`#page-${page.index + 1}`}>{page.title || pathOf(page.url)}</a>
                  <br />
                  <span className="muted">{pathOf(page.url)}</span>
                </th>
                {page.error ? (
                  <td colSpan={principles.length + 1}>Not scanned: {page.error}</td>
                ) : (
                  <>
                    {principles.map((p) => (
                      <td className="num" key={p}>
                        {page.fails_by_principle[p] ? (
                          <Badge status="fail">{page.fails_by_principle[p]}</Badge>
                        ) : (
                          <span className="zero">0</span>
                        )}
                        {page.reviews_by_principle[p] ? <span className="muted"> ({page.reviews_by_principle[p]})</span> : null}
                      </td>
                    ))}
                    <td className="num">
                      <strong>{page.fails}</strong>
                      {page.reviews > 0 && <span className="muted"> ({page.reviews})</span>}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Page by page</h3>
      <div className="pages-list">
        {report.pages.map((page) => (
          <PageDetails key={page.index} reportId={report.id} page={page} />
        ))}
      </div>
    </>
  );
}

function PageDetails({ reportId, page }: { reportId: string; page: PageRow }) {
  return (
    <details id={`page-${page.index + 1}`}>
      <summary>
        <span className="summary-title">{page.title || pathOf(page.url)}</span>
        {page.error ? (
          <span className="badge badge-na">Not scanned</span>
        ) : page.fails ? (
          <Badge status="fail">{plural(page.fails, "failure")}</Badge>
        ) : (
          <Badge status="pass">No failures</Badge>
        )}
        {page.reviews > 0 && <Badge status="review">{page.reviews} to review</Badge>}
      </summary>
      <div className="detail-body">
        <p className="page-facts">
          <a href={page.url}>{page.url}</a>
        </p>
        {page.error ? (
          <p>{page.error}</p>
        ) : (
          <>
            <p className="page-facts">
              Failed:{" "}
              {page.failed_criteria.length
                ? page.failed_criteria.map((c, i) => (
                    <span key={c}>
                      {i > 0 && ", "}
                      <a href={`#c-${c}`}>{c}</a>
                    </span>
                  ))
                : "none"}{" "}
              · {page.tab_stops} tab stops
            </p>
            {page.notes.map((n) => (
              <p className="muted" key={n}>
                {n}
              </p>
            ))}
            {page.has_screenshot && (
              <img
                className="page-shot"
                loading="lazy"
                src={screenshotUrl(reportId, page.index)}
                alt={`Screenshot of ${pathOf(page.url)} with elements that fail outlined in red`}
              />
            )}
          </>
        )}
      </div>
    </details>
  );
}

export function Issues({ report }: { report: Report }) {
  if (report.issues.length === 0) return <p className="empty">No issues were found.</p>;
  return (
    <>
      {report.issues.map((issue) => (
        <IssueArticle key={issue.criterion.id} issue={issue} />
      ))}
    </>
  );
}

function IssueArticle({ issue }: { issue: Issue }) {
  const { criterion: c } = issue;
  const headingId = `c-${c.id}-h`;
  return (
    <article id={`c-${c.id}`} className="issue" aria-labelledby={headingId}>
      <div className="issue-head">
        <h3 id={headingId}>
          <span className="sc">
            {c.id} · Level {c.level} · {c.principle}
          </span>
          {c.name}
        </h3>
        <Badge status={issue.status} />
      </div>
      <p className="crit-meta">
        {c.what_to_check}{" "}
        <a href={c.understanding_url}>
          Understanding {c.id}
          <span className="visually-hidden"> (W3C)</span>
        </a>
      </p>
      {issue.groups.map((g, i) => (
        <GroupDetails key={`${g.rule}-${g.status}`} group={g} open={i === 0 && g.status === "fail"} />
      ))}
    </article>
  );
}

function GroupDetails({ group: g, open }: { group: RuleGroup; open: boolean }) {
  const extra = g.elements - Math.min(g.instances.length, SHOWN_INSTANCES);
  return (
    <details className="rule-group" open={open}>
      <summary>
        <Badge status={g.status} /> <span>{g.title}</span>{" "}
        <span className="count">
          {plural(g.elements, "element")}
          {g.elements !== g.occurrences && `, ${g.occurrences} occurrences`}
          {g.impact && ` · ${g.impact}`}
        </span>
      </summary>
      {g.fix && (
        <p className="fix">
          <span className="label">Fix</span> {g.fix}
        </p>
      )}
      {g.help_url && (
        <p className="where">
          <a href={g.help_url}>Rule documentation: {g.rule}</a>
        </p>
      )}
      <ol className="instances">
        {g.instances.slice(0, SHOWN_INSTANCES).map((inst, i) => (
          <InstanceItem key={`${inst.selector ?? inst.message}-${i}`} instance={inst} />
        ))}
      </ol>
      {extra > 0 && <p className="muted">And {plural(extra, "more element")}. The JSON download lists every occurrence.</p>}
    </details>
  );
}

function InstanceItem({ instance: inst }: { instance: Instance }) {
  const many = inst.pages.length > 1;
  return (
    <li>
      <p className="where">
        {inst.pages.length === 0 ? (
          "Whole site"
        ) : (
          <>
            {many && <strong>On {inst.pages.length} pages: </strong>}
            {inst.pages.slice(0, 4).map((u, i) => (
              <span key={u}>
                {i > 0 && ", "}
                <a href={u}>{pathOf(u)}</a>
              </span>
            ))}
            {inst.pages.length > 4 && ` and ${inst.pages.length - 4} more`}
          </>
        )}
        {inst.viewport && ` · ${inst.viewport}`}
        {inst.confidence && ` · AI confidence: ${inst.confidence}`}
      </p>
      {inst.source !== "axe" && <p>{inst.message}</p>}
      {inst.selector && (
        <p>
          <span className="label">Element</span>
          <code>{inst.selector}</code>
        </p>
      )}
      {inst.html && (
        <pre>
          <code>{inst.html}</code>
        </pre>
      )}
      {inst.fix && (
        <p className="fix">
          <span className="label">Fix</span> {inst.fix}
        </p>
      )}
    </li>
  );
}

export function ManualChecks({ report }: { report: Report }) {
  const rows = report.principles.flatMap((p) => p.criteria).filter((r) => r.status === "manual" || r.status === "review");
  return (
    <div className="table-wrap" role="region" tabIndex={0} aria-labelledby="manual-cap">
      <table>
        <caption id="manual-cap" className="visually-hidden">
          Criteria needing human judgement
        </caption>
        <thead>
          <tr>
            <th scope="col">Success criterion</th>
            <th scope="col">Status</th>
            <th scope="col">What to check</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.criterion.id}>
              <th scope="row">
                <span className="sc">{r.criterion.id}</span>
                <a href={r.criterion.understanding_url}>{r.criterion.name}</a>
              </th>
              <td>
                <Badge status={r.status} />
              </td>
              <td>{r.criterion.what_to_check}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HowTested({ report }: { report: Report }) {
  return (
    <>
      <ol className="method-steps">
        <li>
          <strong>Automated rules.</strong> The axe-core {report.axe_version} engine ran on every page at desktop (1280px) and phone (375px)
          sizes. It covers {report.axe_criteria} of the criteria at this level.
        </li>
        <li>
          <strong>Interaction tests.</strong> A scripted keyboard user pressed Tab through each page to find keyboard traps, missing focus
          indicators, hidden or obscured focus and controls the keyboard can&apos;t reach. The page was also tested at 200% zoom, with
          increased text spacing and at 320px wide (reflow), and checked for autoplaying media and endless animation.
        </li>
        <li>
          <strong>Cross-page tests.</strong> Pages were compared for unique titles, consistent navigation, consistent link names, consistent
          help and more than one way to find pages.
        </li>
        <li>
          <strong>AI review.</strong>{" "}
          {report.ai_enabled
            ? "Claude reviewed screenshots and content on up to 5 pages for meaningful alt text, clear link text, descriptive headings and use of colour. These findings are marked with a confidence level and should be confirmed by a person."
            : "Not used for this scan."}
        </li>
        <li>
          <strong>Manual checks.</strong> Criteria that no test covers are listed above for a person to check.
        </li>
      </ol>
      <div className="notes">
        <div>
          <h3>Limitations</h3>
          <p>
            Automated testing finds roughly a third to a half of accessibility issues. &ldquo;Pass&rdquo; means no problems were detected,
            not that the criterion is met. Content behind logins, forms after submission, and states that need interaction (menus, dialogs,
            errors) were not tested.
          </p>
          {report.notes.length > 0 && (
            <>
              <h3>Scan notes</h3>
              <ul>
                {report.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div>
          <h3>Pages scanned</h3>
          <ol className="mono">
            {report.pages.map((p) => (
              <li key={p.index}>
                <a href={p.url}>{pathOf(p.url)}</a>
                {p.error && `: ${p.error}`}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </>
  );
}

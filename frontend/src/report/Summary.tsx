import { Icon } from "../components/Icon";
import { STATUS_LABEL, STATUSES } from "../format";
import type { Report, Status } from "../types";

const FIGURE_LABEL: Record<Status, string> = {
  fail: "Fail",
  review: "Need review",
  pass: "Pass",
  manual: "Manual check",
  na: "Not applicable",
};

export function Summary({ report }: { report: Report }) {
  const { verdict, counts } = report;
  const total = STATUSES.reduce((sum, s) => sum + counts[s], 0);

  return (
    <>
      <div className={`verdict verdict-${verdict.status}`}>
        <p className="verdict-title">
          <Icon name={verdict.status === "error" ? "error" : verdict.status} /> {verdict.title}
        </p>
        <p className="verdict-detail">{verdict.detail}</p>
      </div>

      <ul className="figures" aria-label={`Results for the ${total} success criteria`}>
        {STATUSES.map((s) => (
          <li key={s}>
            <span className="figure-num">{counts[s]}</span>
            <span className="figure-label">
              <span className={`key key-${s}`} aria-hidden="true" />
              {FIGURE_LABEL[s]}
            </span>
          </li>
        ))}
      </ul>
      <p className="aside-figures">
        <span>
          <strong>{report.fail_findings}</strong> failures found
        </span>
        <span>
          <strong>{report.review_findings}</strong> items to review
        </span>
        <span>
          <strong>
            {report.pages_with_failures}/{report.pages_scanned}
          </strong>{" "}
          pages with failures
        </span>
      </p>

      <CriteriaMap report={report} />
    </>
  );
}

/** One square per success criterion, grouped by principle. Squares with problems link to the details. */
function CriteriaMap({ report }: { report: Report }) {
  return (
    <div className="map">
      <h3>Every criterion, at a glance</h3>
      <p>One square per success criterion. Squares with problems link to the details.</p>
      {report.principles.map((p) => (
        <div className="map-row" key={p.name}>
          <p className="map-name">
            {p.number}. {p.name}
            <span>
              {p.counts.fail} fail · {p.counts.review} review · {p.counts.pass} pass
            </span>
          </p>
          <ul className="cells" aria-label={`${p.name} criteria`}>
            {p.criteria.map((row) => {
              const label = `${row.criterion.id} ${row.criterion.name}: ${STATUS_LABEL[row.status]}`;
              const content = (
                <>
                  <span>
                    {/* The space sits outside the hidden text: leading spaces inside it are dropped from the name. */}
                    {row.criterion.id}{" "}
                    <span className="visually-hidden">
                      {row.criterion.name}: {STATUS_LABEL[row.status]}
                    </span>
                  </span>
                  <Icon name={row.status} />
                </>
              );
              return (
                <li key={row.criterion.id}>
                  {row.has_issues ? (
                    <a className={`cell cell-${row.status}`} href={`#c-${row.criterion.id}`} title={label}>
                      {content}
                    </a>
                  ) : (
                    <span className={`cell cell-${row.status}`} title={label}>
                      {content}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

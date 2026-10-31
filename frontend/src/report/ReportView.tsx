import { downloads } from "../api";
import { Icon } from "../components/Icon";
import { usePageTitle } from "../components/Layout";
import { formatDate } from "../format";
import type { Report } from "../types";
import { Chapter } from "./Chapter";
import { CriteriaTables, HowTested, Issues, ManualChecks, Pages } from "./Sections";
import { Summary } from "./Summary";

const CONTENTS = [
  ["summary", "Summary"],
  ["criteria", "Criteria"],
  ["pages", "Pages"],
  ["issues", "Issues"],
  ["manual", "Manual checks"],
  ["method", "Method"],
] as const;

export function ReportView({ report }: { report: Report }) {
  usePageTitle(`Accessibility report: ${report.host}`);
  const files = downloads(report.id);

  return (
    <div className="wrap">
      <header className="cover">
        <p className="kicker">Accessibility audit · WCAG 2.2 Level {report.level}</p>
        <h1>{report.host}</h1>
        <dl className="facts">
          <div>
            <dt>Date</dt>
            <dd>{formatDate(report.finished_at)}</dd>
          </div>
          <div>
            <dt>Pages</dt>
            <dd>{report.pages_scanned} scanned</dd>
          </div>
          <div>
            <dt>Standard</dt>
            <dd>WCAG 2.2 {report.level}</dd>
          </div>
          <div>
            <dt>Engine</dt>
            <dd>axe-core {report.axe_version}</dd>
          </div>
          <div>
            <dt>AI review</dt>
            <dd>{report.ai_enabled ? "On" : "Off"}</dd>
          </div>
        </dl>
        <p className="downloads">
          <span>Download</span>
          <a href={files.pdf} download>
            <Icon name="down" /> PDF
          </a>
          <a href={files.html} download>
            <Icon name="down" /> HTML
          </a>
          <a href={files.json} download>
            <Icon name="down" /> JSON
          </a>
        </p>
      </header>

      <div className="report-layout">
        <nav className="toc" aria-labelledby="toc-h">
          <h2 id="toc-h">Contents</h2>
          <ol>
            {CONTENTS.map(([id, name], i) => (
              <li key={id}>
                <a href={`#${id}`}>
                  <span className="num mono" aria-hidden="true">
                    0{i + 1}
                  </span>
                  <span>{name}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="report-body">
          <Chapter id="summary" number={1} title="Summary">
            <Summary report={report} />
          </Chapter>
          <Chapter
            id="criteria"
            number={2}
            title="Results by criterion"
            intro={
              <>
                <strong>Fail</strong>: a test found a definite violation. <strong>Needs review</strong>: something a person must judge.{" "}
                <strong>Pass</strong>: every test for it ran and found nothing, which is not proof of conformance.{" "}
                <strong>Manual check</strong>: no automated test exists.
              </>
            }
          >
            <CriteriaTables report={report} />
          </Chapter>
          <Chapter
            id="pages"
            number={3}
            title="Results by page"
            intro="Failures on each page by WCAG principle. Items to review are in brackets."
          >
            <Pages report={report} />
          </Chapter>
          <Chapter
            id="issues"
            number={4}
            title="Issues in detail"
            intro="Failures first, then items to review. Each shows the page, the element, its HTML and the fix."
          >
            <Issues report={report} />
          </Chapter>
          <Chapter
            id="manual"
            number={5}
            title="Manual checks"
            intro={`No tool can fully verify these ${report.counts.manual + report.counts.review} criteria. A person should check each one, ideally with a keyboard and a screen reader (NVDA, JAWS or VoiceOver).`}
          >
            <ManualChecks report={report} />
          </Chapter>
          <Chapter id="method" number={6} title="How this was tested">
            <HowTested report={report} />
          </Chapter>
        </div>
      </div>
    </div>
  );
}

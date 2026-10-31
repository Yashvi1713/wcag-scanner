// The shapes returned by the JSON API. They mirror the Pydantic schemas in wcag_scanner/api.py
// (see /docs on a running server); a Python test checks the report fixture used by these tests
// still matches what the server produces.

export type Status = "fail" | "review" | "pass" | "manual" | "na";
export type VerdictStatus = "fail" | "review" | "pass" | "error";
export type ScanState = "queued" | "running" | "done" | "error";
export type Level = "A" | "AA" | "AAA";

export interface Config {
  max_pages: number;
  ai_available: boolean;
  demo_url: string;
}

export interface RecentScan {
  id: string;
  url: string;
  status: ScanState;
  created_at: string;
  pages: number | null;
  fails: number | null;
  verdict: string | null;
}

export interface ScanRequest {
  url: string;
  max_pages: number | string;
  level: Level;
  ai: boolean;
}

export interface Progress {
  stage: "crawl" | "page" | "sitewide" | null;
  message: string;
  done: number;
  total: number;
}

export interface ScanStatus {
  id: string;
  url: string;
  status: ScanState;
  progress: Progress;
  error: string | null;
}

export interface Criterion {
  id: string;
  name: string;
  level: Level;
  principle: string;
  what_to_check: string;
  understanding_url: string;
}

export interface CriterionRow {
  criterion: Criterion;
  status: Status;
  methods: string[];
  fails: number;
  reviews: number;
  pages_failing: number;
  has_issues: boolean;
}

export interface Principle {
  number: number;
  name: string;
  counts: Record<Status, number>;
  criteria: CriterionRow[];
}

export interface Instance {
  pages: string[];
  selector: string | null;
  html: string | null;
  message: string;
  fix: string | null;
  viewport: string | null;
  confidence: string | null;
  source: string;
}

export interface RuleGroup {
  rule: string;
  title: string;
  status: "fail" | "review";
  impact: string | null;
  help_url: string | null;
  fix: string | null;
  occurrences: number;
  elements: number;
  instances: Instance[];
}

export interface Issue {
  criterion: Criterion;
  status: Status;
  groups: RuleGroup[];
}

export interface PageRow {
  index: number;
  url: string;
  title: string;
  error: string | null;
  fails: number;
  reviews: number;
  fails_by_principle: Record<string, number>;
  reviews_by_principle: Record<string, number>;
  failed_criteria: string[];
  tab_stops: number;
  notes: string[];
  has_screenshot: boolean;
}

export interface Report {
  id: string;
  start_url: string;
  host: string;
  level: Level;
  ai_enabled: boolean;
  finished_at: string | null;
  axe_version: string;
  axe_criteria: number;
  notes: string[];
  verdict: { status: VerdictStatus; title: string; detail: string };
  counts: Record<Status, number>;
  fail_findings: number;
  review_findings: number;
  pages_scanned: number;
  pages_with_failures: number;
  principles: Principle[];
  pages: PageRow[];
  issues: Issue[];
}

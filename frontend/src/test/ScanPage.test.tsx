import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Report, ScanStatus } from "../types";
import reportFixture from "./report.json";
import { axeViolations, mockApi, renderApp } from "./utils";

const report = reportFixture as Report;
const status = (over: Partial<ScanStatus>): ScanStatus => ({
  id: "0123456789ab",
  url: "https://library.example/",
  status: "running",
  progress: { stage: "page", message: "Scanning https://library.example/events", done: 1, total: 3 },
  error: null,
  ...over,
});

describe("Scan page while running", () => {
  it("shows progress, the current stage and a polite live status", async () => {
    mockApi({ "GET /api/scans/0123456789ab": { body: status({}) } });
    const { container } = renderApp("/scans/0123456789ab");

    expect(await screen.findByRole("heading", { level: 1, name: "library.example" })).toBeInTheDocument();
    expect(document.title).toBe("Scanning library.example | WCAG Scanner");
    expect(screen.getByRole("progressbar", { name: "Pages tested" })).toHaveAttribute("value", "1");
    expect(screen.getByText("33%")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Scanning https://library.example/events (1 of 3 pages)");
    const stages = within(screen.getByRole("list", { name: "Stages" })).getAllByRole("listitem");
    expect(stages.map((s) => s.dataset.state)).toEqual(["done", "active", "todo"]);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Scan page outcomes", () => {
  it("says so when a scan doesn't exist", async () => {
    mockApi({ "GET /api/scans/ffffffffffff": { status: 404, body: { error: "There's no scan with that ID." } } });
    renderApp("/scans/ffffffffffff");
    expect(await screen.findByRole("heading", { level: 1, name: "Scan not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start a new audit" })).toHaveAttribute("href", "/");
  });

  it("explains a failed scan", async () => {
    mockApi({ "GET /api/scans/0123456789ab": { body: status({ status: "error", error: "The browser crashed repeatedly." }) } });
    renderApp("/scans/0123456789ab");
    expect(await screen.findByRole("heading", { level: 1, name: "The scan failed" })).toBeInTheDocument();
    expect(screen.getByText("The browser crashed repeatedly.")).toBeInTheDocument();
  });

  it("shows an unknown route as not found", async () => {
    renderApp("/no/such/page");
    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  });
});

describe("Report", () => {
  const renderReport = async () => {
    mockApi({
      "GET /api/scans/0123456789ab": { body: status({ status: "done" }) },
      "GET /api/scans/0123456789ab/report": { body: report },
    });
    const view = renderApp("/scans/0123456789ab");
    await screen.findByRole("heading", { level: 1, name: "library.example" });
    return view;
  };

  it("leads with the verdict and the count of criteria in each result", async () => {
    await renderReport();
    expect(document.title).toBe("Accessibility report: library.example | WCAG Scanner");
    expect(screen.getByText(report.verdict.title)).toBeInTheDocument();
    const figures = within(screen.getByRole("list", { name: /Results for the 55 success criteria/ })).getAllByRole("listitem");
    expect(figures.map((f) => f.textContent)).toEqual([
      `${report.counts.fail}Fail`,
      `${report.counts.review}Need review`,
      `${report.counts.pass}Pass`,
      `${report.counts.manual}Manual check`,
      `${report.counts.na}Not applicable`,
    ]);
  });

  it("maps every criterion, and only problem squares are links to their details", async () => {
    await renderReport();
    const cells = screen
      .getAllByRole("list", { name: /^(Perceivable|Operable|Understandable|Robust) criteria$/ })
      .flatMap((list) => within(list).getAllByRole("listitem"));
    expect(cells).toHaveLength(55);
    const failing = screen.getByRole("link", { name: "1.1.1 Non-text Content: Fail" });
    expect(failing).toHaveAttribute("href", "#c-1.1.1");
    expect(screen.queryByRole("link", { name: /1\.2\.1 .*Not applicable/ })).not.toBeInTheDocument();
    expect(document.getElementById("c-1.1.1")).toBeInTheDocument();
  });

  it("groups the same element across pages and names every page it's on", async () => {
    await renderReport();
    const contrast = document.getElementById("c-1.4.3") as HTMLElement;
    expect(within(contrast).getByText(/On 2 pages:/)).toBeInTheDocument();
    expect(within(contrast).getByText("1 element, 2 occurrences · serious")).toBeInTheDocument();
  });

  it("shows pages that couldn't be scanned, with the reason", async () => {
    await renderReport();
    const row = screen.getByRole("row", { name: /members/ });
    expect(row).toHaveTextContent("Not scanned: Needs a login (HTTP 401)");
  });

  it("opens page details with an annotated screenshot", async () => {
    await renderReport();
    const user = userEvent.setup();
    await user.click(screen.getByText("Maple Grove Library", { selector: ".summary-title" }));
    expect(screen.getByRole("img", { name: "Screenshot of / with elements that fail outlined in red" })).toHaveAttribute(
      "src",
      "/api/scans/0123456789ab/pages/0/screenshot",
    );
  });

  it("offers the three downloads", async () => {
    await renderReport();
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/scans/0123456789ab/report.pdf");
    expect(screen.getByRole("link", { name: "HTML" })).toHaveAttribute("href", "/scans/0123456789ab/report.html");
    expect(screen.getByRole("link", { name: "JSON" })).toHaveAttribute("href", "/scans/0123456789ab/report.json");
  });

  it("has no accessibility violations", async () => {
    const { container } = await renderReport();
    expect(await axeViolations(container)).toEqual([]);
  });
});

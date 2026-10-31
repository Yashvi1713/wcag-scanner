import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { RecentScan } from "../types";
import { axeViolations, mockApi, renderApp } from "./utils";

const config = { max_pages: 50, ai_available: false, demo_url: "http://localhost/demo-site/" };
const scan = (over: Partial<RecentScan>): RecentScan => ({
  id: "aaaaaaaaaaaa",
  url: "https://www.gov.uk/",
  status: "done",
  created_at: "2026-10-31T09:00:00+00:00",
  pages: 5,
  fails: 0,
  verdict: "pass",
  ...over,
});

describe("Home page", () => {
  it("renders the form and past audits, with no accessibility violations", async () => {
    mockApi({
      "GET /api/config": { body: config },
      "GET /api/scans": {
        body: [
          scan({ id: "a1", fails: 3, verdict: "fail", url: "https://shop.example/" }),
          scan({ id: "a2", verdict: "error", url: "https://blocked.example/" }),
          scan({ id: "a3", status: "running", pages: null, fails: null, verdict: null }),
          scan({ id: "a4" }),
        ],
      },
    });
    const { container } = renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Can everyone use this website?" })).toBeInTheDocument();
    expect(document.title).toBe("Check a website for accessibility | WCAG Scanner");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([
      "shop.example31 Oct 2026, 09:00 UTC5 3 criteria fail",
      "blocked.example31 Oct 2026, 09:00 UTC5 Couldn't scan",
      "www.gov.uk31 Oct 2026, 09:00 UTC–Running",
      "www.gov.uk31 Oct 2026, 09:00 UTC5 No failures",
    ]);
    expect(screen.getByRole("checkbox", { name: "Add AI review" })).toBeDisabled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("starts a scan with the chosen options and opens it", async () => {
    const calls = mockApi({
      "GET /api/config": { body: { ...config, ai_available: true } },
      "GET /api/scans": { body: [] },
      "POST /api/scans": { status: 201, body: { id: "bbbbbbbbbbbb" } },
      "GET /api/scans/bbbbbbbbbbbb": {
        body: {
          id: "bbbbbbbbbbbb",
          url: "https://www.gov.uk",
          status: "queued",
          progress: { stage: null, message: "", done: 0, total: 1 },
          error: null,
        },
      },
    });
    const { router } = renderApp("/");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Website address"), "https://www.gov.uk");
    await user.clear(screen.getByLabelText("Pages"));
    await user.type(screen.getByLabelText("Pages"), "7");
    await user.click(screen.getByRole("radio", { name: "AAA" }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Add AI review" })).toBeEnabled());
    await user.click(screen.getByRole("checkbox", { name: "Add AI review" }));
    await user.click(screen.getByRole("button", { name: "Run audit" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/scans/bbbbbbbbbbbb"));
    expect(calls.find((c) => c.key === "POST /api/scans")?.body).toEqual({
      url: "https://www.gov.uk",
      max_pages: "7",
      level: "AAA",
      ai: true,
    });
  });

  it("announces a server-side error, marks the field invalid and moves focus to it", async () => {
    mockApi({
      "GET /api/config": { body: config },
      "GET /api/scans": { body: [] },
      "POST /api/scans": { status: 400, body: { error: "Choose between 1 and 50 pages.", field: "max_pages" } },
    });
    renderApp("/");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Website address"), "example.com");
    await user.click(screen.getByRole("button", { name: "Run audit" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Choose between 1 and 50 pages.");
    const pages = screen.getByLabelText("Pages");
    expect(pages).toHaveAttribute("aria-invalid", "true");
    expect(pages).toHaveAccessibleDescription("Up to 50, a few seconds each Choose between 1 and 50 pages.");
    expect(pages).toHaveFocus();
    expect(screen.getByLabelText("Website address")).not.toHaveAttribute("aria-invalid");
  });

  it("explains when the server can't be reached", async () => {
    mockApi({ "GET /api/config": { body: config }, "GET /api/scans": { body: [] } });
    renderApp("/");
    globalThis.fetch = (() => Promise.reject(new TypeError("Failed to fetch"))) as typeof fetch;
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Website address"), "example.com");
    await user.click(screen.getByRole("button", { name: "Run audit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the scanner");
    expect(screen.getByLabelText("Website address")).toHaveFocus();
  });

  it("runs the demo site in one click", async () => {
    const calls = mockApi({
      "GET /api/config": { body: config },
      "GET /api/scans": { body: [] },
      "POST /api/scans": { status: 201, body: { id: "cccccccccccc" } },
    });
    const { router } = renderApp("/");
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(calls.some((c) => c.key === "GET /api/config")).toBe(true));
    await user.click(screen.getByRole("button", { name: /Audit the demo site/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/scans/cccccccccccc"));
    expect(calls.find((c) => c.key === "POST /api/scans")?.body).toEqual({ url: config.demo_url, max_pages: 5, level: "AA", ai: false });
  });
});

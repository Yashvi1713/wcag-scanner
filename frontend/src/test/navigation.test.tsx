import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderApp } from "./utils";

const config = { max_pages: 50, ai_available: false, demo_url: "http://localhost/demo-site/" };

describe("Navigation in a single-page app", () => {
  it("moves focus to the new page's heading and updates the tab title", async () => {
    mockApi({
      "GET /api/config": { body: config },
      "GET /api/scans": { body: [] },
      "GET /api/scans/0123456789ab": { status: 404, body: { error: "There's no scan with that ID." } },
    });
    const { router } = renderApp("/");
    await screen.findByRole("heading", { level: 1, name: "Can everyone use this website?" });
    expect(document.body).toHaveFocus(); // a fresh load leaves focus where the browser puts it

    await act(() => router.navigate("/scans/0123456789ab"));
    const heading = await screen.findByRole("heading", { level: 1, name: "Scan not found" });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(document.title).toBe("Scan not found | WCAG Scanner");
  });

  it("moves focus to a section when a link targets it", async () => {
    mockApi({ "GET /api/config": { body: config }, "GET /api/scans": { body: [] } });
    const { router } = renderApp("/");
    await screen.findByRole("heading", { level: 1 });
    await act(() => router.navigate("/#recent"));
    await waitFor(() => expect(document.getElementById("recent")).toHaveFocus());
  });

  it("has a skip link to the main content", async () => {
    mockApi({ "GET /api/config": { body: config }, "GET /api/scans": { body: [] } });
    renderApp("/");
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });
});

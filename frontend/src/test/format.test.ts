import { describe, expect, it } from "vitest";

import { ApiError, api } from "../api";
import { formatDate, hostOf, pathOf, plural } from "../format";
import { mockApi } from "./utils";

describe("formatting", () => {
  it("formats dates in UTC regardless of the viewer's time zone", () => {
    expect(formatDate("2026-10-31T23:30:00+00:00")).toBe("31 Oct 2026, 23:30 UTC");
    expect(formatDate(null)).toBe("");
    expect(formatDate("not a date")).toBe("not a date");
  });

  it("shortens URLs to what identifies the page", () => {
    expect(pathOf("https://s.example/a/b?x=1#top")).toBe("/a/b?x=1");
    expect(hostOf("https://s.example:8443/a")).toBe("s.example:8443");
    expect(pathOf("not a url")).toBe("not a url");
  });

  it("pluralises", () => {
    expect(plural(1, "page")).toBe("1 page");
    expect(plural(3, "page")).toBe("3 pages");
    expect(plural(2, "more element")).toBe("2 more elements");
  });
});

describe("API client", () => {
  it("turns an error response into an ApiError naming the field", async () => {
    mockApi({ "POST /api/scans": { status: 400, body: { error: "Enter a full web address.", field: "url" } } });
    const error = await api.createScan({ url: "x", max_pages: 5, level: "AA", ai: false }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ message: "Enter a full web address.", status: 400, field: "url" });
  });

  it("explains a response that isn't JSON", async () => {
    globalThis.fetch = (async () => new Response("<html>Bad gateway</html>", { status: 502 })) as typeof fetch;
    await expect(api.config()).rejects.toMatchObject({ status: 502, message: "The server returned an error (502)." });
  });
});

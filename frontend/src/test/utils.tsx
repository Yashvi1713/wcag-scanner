import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import axe from "axe-core";
import { RouterProvider, createMemoryRouter } from "react-router";
import { vi } from "vitest";

import { routes } from "../routes";

type Handler = (init: RequestInit | undefined) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>;

/**
 * Replace fetch with canned API responses, keyed by "METHOD /path". Every request is recorded so
 * tests can assert what the app sent.
 */
export function mockApi(handlers: Record<string, Handler | { status?: number; body: unknown }>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const handler = handlers[key];
    if (!handler) return new Response(JSON.stringify({ error: `No mock for ${key}` }), { status: 404 });
    const { status = 200, body } = typeof handler === "function" ? await handler(init) : handler;
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

/** Render the real routes at a URL, as the app does in the browser. */
export function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router };
}

/** axe-core in jsdom. Contrast needs real layout, so it's covered by the browser tests instead. */
export async function axeViolations(container: Element) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

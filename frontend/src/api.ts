import { useQuery } from "@tanstack/react-query";

import type { Config, RecentScan, Report, ScanRequest, ScanStatus } from "./types";

/** An error the API explained, such as a bad address. `field` names the form field it belongs to. */
export class ApiError extends Error {
  readonly status: number;
  readonly field: string | null;

  constructor(message: string, status: number, field: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.field = field;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch {
    throw new ApiError("Can't reach the scanner. Check that the server is running.", 0);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body as { error?: string; field?: string } | null;
    throw new ApiError(detail?.error ?? `The server returned an error (${response.status}).`, response.status, detail?.field ?? null);
  }
  return body as T;
}

export const api = {
  config: () => request<Config>("/api/config"),
  recentScans: () => request<RecentScan[]>("/api/scans"),
  createScan: (input: ScanRequest) => request<{ id: string }>("/api/scans", { method: "POST", body: JSON.stringify(input) }),
  scan: (id: string) => request<ScanStatus>(`/api/scans/${encodeURIComponent(id)}`),
  report: (id: string) => request<Report>(`/api/scans/${encodeURIComponent(id)}/report`),
};

export const downloads = (id: string) => ({
  pdf: `/scans/${id}/report.pdf`,
  html: `/scans/${id}/report.html`,
  json: `/scans/${id}/report.json`,
});

export const screenshotUrl = (id: string, index: number) => `/api/scans/${id}/pages/${index}/screenshot`;

const POLL_MS = 2000;

export const useConfig = () => useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });

export const useRecentScans = () => useQuery({ queryKey: ["scans"], queryFn: api.recentScans });

/** Polls while the scan is queued or running, and stops once it's finished. */
export const useScan = (id: string) =>
  useQuery({
    queryKey: ["scan", id],
    queryFn: () => api.scan(id),
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return state === "done" || state === "error" ? false : POLL_MS;
    },
  });

/** A finished report never changes, so it's fetched once. */
export const useReport = (id: string, enabled: boolean) =>
  useQuery({ queryKey: ["report", id], queryFn: () => api.report(id), enabled, staleTime: Infinity });

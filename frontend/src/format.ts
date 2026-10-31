import type { Status } from "./types";

export const STATUS_LABEL: Record<Status, string> = {
  fail: "Fail",
  review: "Needs review",
  pass: "Pass",
  manual: "Manual check",
  na: "Not applicable",
};

export const STATUSES: Status[] = ["fail", "review", "pass", "manual", "na"];

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** "31 Oct 2026, 03:19 UTC", the same everywhere regardless of the viewer's locale. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : `${dateFormat.format(date)} UTC`;
}

/** "/about?x=1" from a full URL: the part that identifies the page within the site. */
export function pathOf(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname + u.search;
  } catch {
    return url;
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

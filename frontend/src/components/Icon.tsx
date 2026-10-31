import type { ReactNode } from "react";

import { STATUS_LABEL } from "../format";
import type { Status } from "../types";

const PATHS = {
  fail: "M4 4l8 8M12 4l-8 8",
  error: "M8 2.5L14 13H2zM8 6.5v3M8 11.5v.2",
  review: "M8 3v6M8 12.5v.5",
  pass: "M3 8.5l3.2 3L13 4.5",
  manual: "M5.8 6a2.3 2.3 0 1 1 3.2 2.1c-.6.3-1 .8-1 1.5v.4M8 12.5v.5",
  na: "M4 8h8",
  arrow: "M3 8h10M9 4l4 4-4 4",
  down: "M8 2.5v9M4 8l4 4 4-4M3 14h10",
} as const;

export type IconName = keyof typeof PATHS;

/** Decorative: every icon sits next to text that says the same thing. */
export function Icon({ name }: { name: IconName }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" />
    </svg>
  );
}

/** A result, always shown as icon + text so it never relies on colour alone. */
export function Badge({ status, children }: { status: Status; children?: ReactNode }) {
  return (
    <span className={`badge badge-${status}`}>
      <Icon name={status} /> {children ?? STATUS_LABEL[status]}
    </span>
  );
}

import type { ReactNode } from "react";

/** A numbered report section with a heading that sections and the contents list link to. */
export function Chapter({
  id,
  number,
  title,
  intro,
  children,
}: {
  id: string;
  number: number;
  title: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  const headingId = `${id}-h`;
  return (
    <section id={id} className="chapter" aria-labelledby={headingId}>
      <div className="chapter-head">
        <span className="num" aria-hidden="true">
          0{number}
        </span>
        <h2 id={headingId}>{title}</h2>
        {intro && <p>{intro}</p>}
      </div>
      {children}
    </section>
  );
}

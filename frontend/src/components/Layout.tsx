import { useEffect, useRef } from "react";
import { Link, Outlet, useLocation } from "react-router";

/**
 * The page frame. In a single-page app the browser doesn't announce navigation, so after every
 * route change focus moves to the new page's heading: screen reader users hear where they are,
 * and keyboard users continue from the top of the new page.
 */
let navigatedInApp = false; // after a fresh page load the browser's own focus handling is right

export function Layout() {
  const location = useLocation();
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    navigatedInApp = true;
    if (location.hash) {
      const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (target) {
        focusElement(target);
        return;
      }
    }
    window.scrollTo(0, 0);
    focusHeading();
  }, [location.pathname, location.hash]);

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="site-header">
        <div className="wrap">
          <Link className="brand" to="/">
            <span className="brand-mark" aria-hidden="true" /> WCAG Scanner <small>2.2</small>
          </Link>
          <nav aria-label="Main">
            <ul>
              <li>
                <Link to="/">New audit</Link>
              </li>
              <li>
                <Link to="/#recent">Past audits</Link>
              </li>
            </ul>
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="wrap">
          <p>
            Checks against the Web Content Accessibility Guidelines (WCAG) 2.2. Automated testing finds many issues, but not all: a human
            must complete the manual checks before claiming conformance.
          </p>
          <p className="mono">axe-core · Playwright · Claude</p>
        </div>
      </footer>
    </>
  );
}

/**
 * After a page swaps its content (loading → progress → report), focus on the removed heading is
 * lost to <body>. Put it back on the new heading, but never take it from somewhere the user chose.
 */
export function restoreLostFocus() {
  if (navigatedInApp && (!document.activeElement || document.activeElement === document.body)) focusHeading();
}

/** Move focus to the main heading (falling back to <main>), without scrolling it out of place. */
export function focusHeading() {
  const heading = document.querySelector<HTMLElement>("main h1");
  focusElement(heading ?? document.getElementById("main"));
}

function focusElement(el: HTMLElement | null) {
  if (!el) return;
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: false });
}

/** Sets the browser tab title, which is also the first thing a screen reader reads on a new page. */
export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} | WCAG Scanner` : "WCAG Scanner";
  }, [title]);
}

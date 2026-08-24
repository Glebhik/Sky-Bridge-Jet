import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Production auth visual shell (Phase 9.2.B2.1, visual polish V1) — the "Midnight Aviation"
 * surface shared by the real `/register`, `/login`, and `/verify-email` pages.
 * Presentational only: no business logic, no client state, no demo coupling (it imports
 * nothing from `/demo` and needs no feature flag), so it composes inside server components.
 * All styling is class-scoped under `.sbj-auth` in globals.css so it can never alter
 * `/portal` or `/demo`.
 *
 * There is no canonical production emblem asset, so the brand is a text wordmark only; the
 * mark slot is reserved (and hidden) for a future approved emblem — no invented symbol.
 * Background atmosphere is abstract (horizon, coordinate grid, route geometry), decorative,
 * and aria-hidden — no aircraft, map, operator, or flight data.
 */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="sbj-auth">
      <div className="sbj-auth__atmosphere" aria-hidden="true">
        <div className="sbj-auth__grid" />
        <div className="sbj-auth__glow" />
        <div className="sbj-auth__horizon" />
        <svg
          className="sbj-auth__route"
          viewBox="0 0 1200 800"
          focusable="false"
        >
          <path
            d="M90 560 C 310 240, 740 200, 1110 500"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.1"
          />
          <circle cx="90" cy="560" r="3.2" fill="currentColor" />
          <circle cx="1110" cy="500" r="3.2" fill="currentColor" />
          <circle
            cx="560"
            cy="268"
            r="2.1"
            fill="currentColor"
            opacity="0.75"
          />
        </svg>
      </div>
      <section className="sbj-auth__panel">
        <Link
          href="/"
          className="sbj-auth__brand"
          aria-label="Sky Bridge Jet — home"
        >
          <span className="sbj-auth__mark" aria-hidden="true" />
          <span className="sbj-auth__wordmark">Sky Bridge Jet</span>
        </Link>
        {children}
      </section>
    </main>
  );
}

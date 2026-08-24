import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Production auth visual shell (Phase 9.2.B2.1) — the "Midnight Aviation" surface shared by
 * the real `/register` and `/login` pages. Presentational only: no business logic, no client
 * state, no demo coupling (it imports nothing from `/demo` and needs no feature flag), so it
 * composes inside server components. All styling is class-scoped under `.sbj-auth` in
 * globals.css so it can never alter `/portal` or `/demo`.
 *
 * There is no canonical production emblem asset, so the brand is a text wordmark only; the
 * mark slot is reserved (and hidden) for a future approved emblem — no invented symbol.
 */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="sbj-auth">
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

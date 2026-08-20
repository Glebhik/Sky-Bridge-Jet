"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useState, type ReactNode } from "react";

import { Alert, Container } from "@/components/ui/primitives";
import { DEMO_DATA_BANNER, demoFixtures } from "@/lib/demo/fixtures";

const DEMO_NAV_ITEMS = [
  { href: "/demo", label: "Dashboard" },
  { href: "/demo/bookings", label: "Bookings" },
  { href: "/demo/offers", label: "Offers" },
  { href: "/demo/account", label: "Account" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/demo"
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * A presentational shell exclusively for the public synthetic demonstration. It has no
 * session provider, organization provider, authentication cookie access, API client, or
 * persistence. Its only client state controls the accessible mobile navigation menu.
 */
export function DemoPortalShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/demo";
  const [menuOpen, setMenuOpen] = useState(false);
  const navPanelId = useId();

  return (
    <div className="portal demo-portal">
      <a className="skip-link" href="#demo-main">
        Skip to main content
      </a>
      <header className="portal-header">
        <div className="portal-header__bar">
          <div className="demo-portal__identity">
            <Link href="/demo" className="brand portal-header__brand">
              Sky Bridge Jet
            </Link>
            <span className="demo-portal__label">
              Customer Portal Demonstration
            </span>
          </div>
          <button
            type="button"
            className="portal-header__menu-toggle"
            aria-expanded={menuOpen}
            aria-controls={navPanelId}
            aria-label={
              menuOpen ? "Close navigation menu" : "Open navigation menu"
            }
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
          </button>
          <div
            className="demo-portal__organization"
            aria-label="Active organization"
          >
            <span className="org-switcher__label">
              Demonstration organization
            </span>
            <span className="org-switcher__value">
              {demoFixtures.customer.organization}
            </span>
          </div>
        </div>
        <nav
          id={navPanelId}
          aria-label="Customer Portal Demonstration"
          className={`portal-nav${menuOpen ? " portal-nav--open" : ""}`}
        >
          <ul className="portal-nav__list">
            {DEMO_NAV_ITEMS.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={`portal-nav__link${active ? " portal-nav__link--active" : ""}`}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setMenuOpen(false)}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      <main id="demo-main" className="portal-main" tabIndex={-1}>
        <Container>
          <div className="demo-portal__banner">
            <Alert tone="warning" title={DEMO_DATA_BANNER} />
          </div>
          {children}
        </Container>
      </main>
    </div>
  );
}

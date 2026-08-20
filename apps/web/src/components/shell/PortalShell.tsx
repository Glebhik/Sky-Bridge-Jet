"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useState, type ReactNode } from "react";

import { OrganizationSwitcher } from "@/components/shell/OrganizationSwitcher";
import { UserMenu } from "@/components/shell/UserMenu";
import { useActiveOrganization } from "@/components/session/org-context";
import { Alert, Container } from "@/components/ui/primitives";
import { PORTAL_NAV_ITEMS, isActiveNavItem } from "@/lib/portal/navigation";

/**
 * The responsive Customer Portal application shell: a header with the brand, primary
 * navigation (a horizontal bar on desktop, a toggled panel on mobile), the active
 * organization presentation/selector, and the user/session menu, wrapping the main content
 * region. Navigation is keyboard-accessible with visible focus and `aria-current` on the
 * active item; the mobile toggle exposes `aria-expanded`/`aria-controls`.
 */
export function PortalShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/portal";
  const [menuOpen, setMenuOpen] = useState(false);
  const navPanelId = useId();
  const { hasCustomerContext } = useActiveOrganization();

  return (
    <div className="portal">
      <a className="skip-link" href="#portal-main">
        Skip to main content
      </a>
      <header className="portal-header">
        <div className="portal-header__bar">
          <Link href="/portal" className="brand portal-header__brand">
            Sky Bridge Jet
          </Link>
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
          <div className="portal-header__account">
            <OrganizationSwitcher />
            <UserMenu />
          </div>
        </div>
        <nav
          id={navPanelId}
          aria-label="Portal"
          className={`portal-nav${menuOpen ? " portal-nav--open" : ""}`}
        >
          <ul className="portal-nav__list">
            {PORTAL_NAV_ITEMS.map((item) => {
              const active = isActiveNavItem(pathname, item.href);
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

      <main id="portal-main" className="portal-main" tabIndex={-1}>
        <Container>
          {hasCustomerContext ? null : (
            <Alert tone="warning" title="No active customer account">
              This sign-in isn’t linked to a customer account yet. You can
              recover a personal account from the Account page.
            </Alert>
          )}
          {children}
        </Container>
      </main>
    </div>
  );
}

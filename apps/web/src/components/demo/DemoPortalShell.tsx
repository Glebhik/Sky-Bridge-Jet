"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Atmosphere } from "@/components/demo/Atmosphere";
import { BrandLockup } from "@/components/demo/BrandLockup";
import { DemoNotice } from "@/components/demo/DemoNotice";
import {
  DEMO_NAV_DESKTOP_LABEL,
  DEMO_NAV_MOBILE_LABEL,
  DEMO_READ_ONLY_LABEL,
} from "@/lib/demo/copy";
import { demoFixtures } from "@/lib/demo/fixtures";
import { DEMO_NAV_ITEMS, isDemoNavActive } from "@/lib/demo/navigation";

/**
 * Presentational shell for the public synthetic demonstration only. It has no session
 * provider, organization provider, authentication cookie access, API client, or persistence.
 */
export function DemoPortalShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/demo";

  return (
    <div className="sbj-demo">
      <Atmosphere />
      <a className="sbj-demo__skip" href="#demo-main">
        Skip to main content
      </a>
      <div className="sbj-demo__frame">
        <aside className="sbj-demo__rail">
          <BrandLockup />
          <nav
            aria-label={DEMO_NAV_DESKTOP_LABEL}
            className="sbj-demo__rail-nav"
          >
            <NavList pathname={pathname} variant="rail" />
          </nav>
          <div className="sbj-demo__rail-foot">
            <strong>{demoFixtures.customer.name}</strong>
            <span>{demoFixtures.customer.organization}</span>
            <span className="sbj-demo__chip">{DEMO_READ_ONLY_LABEL}</span>
          </div>
        </aside>

        <div className="sbj-demo__column">
          <header className="sbj-demo__topbar">
            <BrandLockup compact />
            <span className="sbj-demo__chip">{DEMO_READ_ONLY_LABEL}</span>
          </header>
          <main id="demo-main" className="sbj-demo__main" tabIndex={-1}>
            <DemoNotice />
            {children}
          </main>
        </div>
      </div>
      <nav aria-label={DEMO_NAV_MOBILE_LABEL} className="sbj-demo__dock">
        <NavList pathname={pathname} variant="dock" />
      </nav>
    </div>
  );
}

function NavList({
  pathname,
  variant,
}: {
  pathname: string;
  variant: "rail" | "dock";
}) {
  return (
    <ul
      className={
        variant === "rail" ? "sbj-demo__nav-list" : "sbj-demo__dock-list"
      }
    >
      {DEMO_NAV_ITEMS.map((item) => {
        const active = isDemoNavActive(pathname, item.href);
        return (
          <li key={`${variant}-${item.href}`}>
            <Link
              href={item.href}
              className={`${variant === "rail" ? "sbj-demo__nav-link" : "sbj-demo__dock-link"}${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              {variant === "rail" ? (
                <span className="sbj-demo__nav-mark" aria-hidden="true" />
              ) : null}
              {item.label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

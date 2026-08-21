import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { DemoPortalShell } from "@/components/demo/DemoPortalShell";
import {
  DEMO_NAV_DESKTOP_LABEL,
  DEMO_NAV_MOBILE_LABEL,
} from "@/lib/demo/copy";

let currentPath = "/demo/bookings";

vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("DemoPortalShell", () => {
  it("renders semantic demonstration navigation and synthetic-data banner", () => {
    render(
      <DemoPortalShell>
        <p>Demo page</p>
      </DemoPortalShell>,
    );
    const desktopNav = screen.getByRole("navigation", {
      name: DEMO_NAV_DESKTOP_LABEL,
    });
    const mobileNav = screen.getByRole("navigation", {
      name: DEMO_NAV_MOBILE_LABEL,
    });
    expect(DEMO_NAV_DESKTOP_LABEL).not.toBe(DEMO_NAV_MOBILE_LABEL);
    for (const nav of [desktopNav, mobileNav]) {
      for (const label of ["Dashboard", "Bookings", "Offers", "Account"]) {
        expect(
          within(nav).getByRole("link", { name: label }),
        ).toBeInTheDocument();
      }
    }
    expect(
      screen.getByText(
        "Demonstration Preview — synthetic data only. No booking or transaction is created.",
      ),
    ).toBeInTheDocument();
  });

  it("marks the current demonstration route with aria-current", () => {
    currentPath = "/demo/bookings";
    render(<DemoPortalShell>Demo page</DemoPortalShell>);
    for (const link of screen.getAllByRole("link", { name: "Bookings" })) {
      expect(link).toHaveAttribute("aria-current", "page");
    }
    for (const link of screen.getAllByRole("link", { name: "Dashboard" })) {
      expect(link).not.toHaveAttribute("aria-current");
    }
  });

  it("provides desktop rail and mobile destinations without a hamburger menu", () => {
    render(<DemoPortalShell>Demo page</DemoPortalShell>);
    expect(
      screen.queryByRole("button", { name: /navigation menu/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: DEMO_NAV_DESKTOP_LABEL }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: DEMO_NAV_MOBILE_LABEL }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("navigation")).toHaveLength(2);
  });

  it("provides a skip link and readable main-content target", () => {
    render(<DemoPortalShell>Demo page</DemoPortalShell>);
    expect(
      screen.getByRole("link", { name: "Skip to main content" }),
    ).toHaveAttribute("href", "#demo-main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "demo-main");
  });
});

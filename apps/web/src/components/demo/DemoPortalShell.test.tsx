import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { DemoPortalShell } from "@/components/demo/DemoPortalShell";

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
    const nav = screen.getByRole("navigation", {
      name: "Customer Portal Demonstration",
    });
    for (const label of ["Dashboard", "Bookings", "Offers", "Account"]) {
      expect(
        within(nav).getByRole("link", { name: label }),
      ).toBeInTheDocument();
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
    expect(screen.getByRole("link", { name: "Bookings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("exposes an accessible toggleable mobile menu", () => {
    render(<DemoPortalShell>Demo page</DemoPortalShell>);
    const toggle = screen.getByRole("button", {
      name: "Open navigation menu",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls");
    fireEvent.click(toggle);
    expect(
      screen.getByRole("button", { name: "Close navigation menu" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("provides a skip link and readable main-content target", () => {
    render(<DemoPortalShell>Demo page</DemoPortalShell>);
    expect(
      screen.getByRole("link", { name: "Skip to main content" }),
    ).toHaveAttribute("href", "#demo-main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "demo-main");
  });
});

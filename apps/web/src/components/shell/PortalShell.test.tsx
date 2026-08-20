import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { OrganizationProvider } from "@/components/session/org-context";
import { SessionProvider } from "@/components/session/session-context";
import { PortalShell } from "@/components/shell/PortalShell";
import type { SessionSnapshot } from "@/lib/session/model";

let currentPath = "/portal/bookings";

vi.mock("next/navigation", () => ({
  usePathname: () => currentPath,
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
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

function session(orgIds: string[]): SessionSnapshot {
  return {
    status: "authenticated",
    user: {
      id: "u1",
      email: "flyer@example.com",
      display_name: null,
      status: "ACTIVE",
      email_verified_at: null,
      created_at: "2026-01-01T00:00:00Z",
    },
    memberships: orgIds.map((id) => ({
      organization_id: id,
      organization_type: "CUSTOMER" as const,
      role: "CUSTOMER_OWNER",
    })),
    customerOrganizations: orgIds.map((id) => ({
      organizationId: id,
      role: "CUSTOMER_OWNER",
    })),
    permissions: [],
  };
}

function renderShell(orgIds: string[]) {
  return render(
    <SessionProvider initialSession={session(orgIds)}>
      <OrganizationProvider>
        <PortalShell>
          <p>Page content</p>
        </PortalShell>
      </OrganizationProvider>
    </SessionProvider>,
  );
}

describe("PortalShell", () => {
  it("renders labelled primary navigation with all shell destinations", () => {
    renderShell(["a"]);
    const nav = screen.getByRole("navigation", { name: "Portal" });
    for (const label of ["Dashboard", "Bookings", "Offers", "Account"]) {
      expect(
        within(nav).getByRole("link", { name: label }),
      ).toBeInTheDocument();
    }
  });

  it("marks the current route with aria-current", () => {
    currentPath = "/portal/bookings";
    renderShell(["a"]);
    const active = screen.getByRole("link", { name: "Bookings" });
    expect(active).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("exposes an accessible, toggleable mobile menu button", () => {
    renderShell(["a"]);
    const toggle = screen.getByRole("button", { name: "Open navigation menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls");
    fireEvent.click(toggle);
    expect(
      screen.getByRole("button", { name: "Close navigation menu" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("provides a skip link to the main content", () => {
    renderShell(["a"]);
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveAttribute("href", "#portal-main");
  });

  it("shows the no-customer-context notice only when there is no customer organization", () => {
    const { unmount } = renderShell(["a"]);
    expect(
      screen.queryByText("No active customer account"),
    ).not.toBeInTheDocument();
    unmount();

    renderShell([]);
    expect(screen.getByText("No active customer account")).toBeInTheDocument();
  });
});

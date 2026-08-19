import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PortalLayout from "@/app/portal/layout";
import type { SessionSnapshot } from "@/lib/session/model";

const getServerSession = vi.fn<() => Promise<SessionSnapshot>>();

vi.mock("@/lib/session/server", () => ({
  getServerSession: () => getServerSession(),
}));

vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
  usePathname: () => "/portal",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
}));

vi.mock("next/headers", () => ({
  headers: () =>
    Promise.resolve({
      get: (key: string) =>
        key === "x-portal-pathname" ? "/portal/bookings" : null,
    }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function authenticated(): SessionSnapshot {
  return {
    status: "authenticated",
    user: {
      id: "u1",
      email: "a@b.co",
      display_name: null,
      status: "ACTIVE",
      email_verified_at: null,
      created_at: "2026-01-01T00:00:00Z",
    },
    memberships: [],
    customerOrganizations: [],
    permissions: [],
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("protected portal layout boundary", () => {
  it("redirects an unauthenticated request to login with a safe return path", async () => {
    getServerSession.mockResolvedValueOnce({ status: "unauthenticated" });
    await expect(PortalLayout({ children: <p>Protected</p> })).rejects.toThrow(
      "REDIRECT:/login?next=%2Fportal%2Fbookings",
    );
  });

  it("shows a recoverable error (not a logout) on a transient backend failure", async () => {
    getServerSession.mockResolvedValueOnce({
      status: "error",
      transient: true,
    });
    const ui = await PortalLayout({ children: <p>Protected</p> });
    render(ui);
    expect(
      screen.getByText("We couldn’t load your account"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Protected")).not.toBeInTheDocument();
  });

  it("renders the shell and protected content for an authenticated session", async () => {
    getServerSession.mockResolvedValueOnce(authenticated());
    const ui = await PortalLayout({ children: <p>Protected</p> });
    render(ui);
    expect(
      screen.getByRole("navigation", { name: "Portal" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Protected")).toBeInTheDocument();
  });
});

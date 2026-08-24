import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";

// The login page is an async server component; mock its server-only dependencies so it can
// be awaited and rendered under jsdom. This asserts the shell + register link WITHOUT
// changing any login behaviour (session/CSRF/redirect logic is untouched by B2.1).
vi.mock("@/lib/session/server", () => ({
  getServerSession: vi.fn(async () => ({ status: "unauthenticated" })),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/api/client", () => ({
  portalApi: { login: vi.fn() },
}));

describe("LoginPage — B2.1 register integration", () => {
  it("renders the sign-in form and a link to create an account", async () => {
    const ui = await LoginPage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByLabelText("Email")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();

    const createLink = screen.getByRole("link", { name: "Create an account" });
    expect(createLink.getAttribute("href")).toBe("/register");
  });
});

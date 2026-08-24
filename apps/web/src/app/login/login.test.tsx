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

const VERIFIED_BANNER = "Your email is verified. Sign in to continue.";

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

describe("LoginPage — B2.2 verified banner", () => {
  it("shows the banner only for the exact flag verified=1", async () => {
    const ui = await LoginPage({
      searchParams: Promise.resolve({ verified: "1" }),
    });
    render(ui);
    expect(screen.getByText(VERIFIED_BANNER)).toBeTruthy();
  });

  it("does not show the banner for verified=0, other values, or when absent", async () => {
    for (const verified of [
      undefined,
      "0",
      "true",
      "yes",
      "1x",
      "<script>x</script>",
    ]) {
      const ui = await LoginPage({
        searchParams: Promise.resolve(
          verified === undefined ? {} : { verified },
        ),
      });
      const { unmount } = render(ui);
      expect(screen.queryByText(VERIFIED_BANNER)).toBeNull();
      // Arbitrary query content is never reflected into the page.
      if (typeof verified === "string") {
        expect(document.body.textContent).not.toContain(verified);
      }
      unmount();
    }
  });

  it("coexists with a sanitized next and still shows the register link", async () => {
    const ui = await LoginPage({
      searchParams: Promise.resolve({ next: "/portal", verified: "1" }),
    });
    render(ui);
    expect(screen.getByText(VERIFIED_BANNER)).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Create an account" })
        .getAttribute("href"),
    ).toBe("/register");
  });
});
